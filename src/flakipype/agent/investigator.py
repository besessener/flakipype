"""One investigation: a tool loop over the Messages API that ends in a checked verdict."""

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from anthropic import Anthropic, APIError
from anthropic.types import Message, ToolUseBlock
from pydantic import ValidationError

from flakipype.agent.budget import BudgetExceededError, InvestigationBudget
from flakipype.agent.masking import Masker
from flakipype.agent.prompts import INVESTIGATOR_SYSTEM
from flakipype.agent.tools import PolicyGate, Tool, ToolError
from flakipype.agent.verdict import Verdict, citation_problems

SUBMIT_VERDICT = "submit_verdict"
FINDING_REFERENCE = "finding"
_CORRECTIONS = 2
_NUDGES = 1
_NUDGE = "Continue the investigation and finish by calling submit_verdict."


class Status(StrEnum):
    COMPLETED = "completed"
    BUDGET = "budget"
    LOOP = "loop"
    NO_VERDICT = "no_verdict"
    MODEL_ERROR = "model_error"


@dataclass(frozen=True)
class ModelSettings:
    model: str
    max_tokens: int = 16_000
    # "adaptive", "enabled" (with thinking_budget) or "off".
    thinking: str = "adaptive"
    thinking_budget: int = 8_000

    def thinking_parameter(self) -> dict[str, Any]:
        if self.thinking == "adaptive":
            return {"thinking": {"type": "adaptive"}}
        if self.thinking == "enabled":
            return {"thinking": {"type": "enabled", "budget_tokens": self.thinking_budget}}
        return {}


@dataclass(frozen=True)
class Outcome:
    status: Status
    verdict: Verdict | None = None
    detail: str = ""


@dataclass
class _Turn:
    results: list[dict[str, Any]] = field(default_factory=list)
    verdict: Verdict | None = None
    submit_id: str = ""


def _submit_tool() -> dict[str, Any]:
    return {
        "name": SUBMIT_VERDICT,
        "description": "Submit the verdict; ends the investigation. Quotes are checked.",
        "input_schema": Verdict.model_json_schema(),
    }


class Investigator:
    def __init__(  # noqa: PLR0913 - collaborators of one investigation, all keyword-only
        self,
        *,
        client: Anthropic,
        settings: ModelSettings,
        tools: list[Tool],
        gate: PolicyGate,
        budget: InvestigationBudget,
        masker: Masker,
    ) -> None:
        self._client = client
        self._settings = settings
        self._tools = {tool.name: tool for tool in tools}
        self._gate = gate
        self._budget = budget
        self._masker = masker
        self._messages: list[dict[str, Any]] = []
        self._results: dict[str, str] = {}
        self._pending: _Turn = _Turn()
        self._corrections = _CORRECTIONS
        self._last_call = ""

    @property
    def results(self) -> dict[str, str]:
        """Masked tool results by tool call id, for citations and the reviewer."""
        return dict(self._results)

    def start(self, finding_text: str) -> Outcome:
        masked = self._masker.mask(finding_text)
        self._results[FINDING_REFERENCE] = masked
        opening = (
            f"{masked}\n\nThe finding above can be cited with tool_call_id "
            f'"{FINDING_REFERENCE}". Investigate it and submit your verdict.'
        )
        self._messages.append({"role": "user", "content": opening})
        return self._loop()

    def revise(self, questions: list[str]) -> Outcome:
        asked = "\n".join(f"- {question}" for question in questions)
        reply = {
            "type": "tool_result",
            "tool_use_id": self._pending.submit_id,
            "content": f"A reviewer sent the verdict back with these questions:\n{asked}\n"
            "Investigate further and submit a revised verdict.",
        }
        self._messages.append({"role": "user", "content": [*self._pending.results, reply]})
        self._pending = _Turn()
        return self._loop()

    def _loop(self) -> Outcome:
        nudges = _NUDGES
        while True:
            try:
                self._budget.check()
                response = self._call()
            except BudgetExceededError as error:
                return Outcome(Status.BUDGET, detail=f"Stopped at {error}.")
            except APIError as error:
                return Outcome(Status.MODEL_ERROR, detail=str(error))
            self._budget.record(response.usage)
            self._messages.append({"role": "assistant", "content": _content(response)})
            uses = [block for block in response.content if isinstance(block, ToolUseBlock)]
            if not uses:
                if nudges == 0:
                    return Outcome(Status.NO_VERDICT, detail="The model stopped without a verdict.")
                nudges -= 1
                self._messages.append({"role": "user", "content": _NUDGE})
                continue
            turn = _Turn()
            for use in uses:
                outcome = self._handle(use, turn)
                if outcome is not None:
                    return outcome
            if turn.verdict is not None:
                self._pending = turn
                return Outcome(Status.COMPLETED, turn.verdict)
            self._messages.append({"role": "user", "content": turn.results})

    def _call(self) -> Message:
        definitions = [tool.definition() for tool in self._tools.values()] + [_submit_tool()]
        definitions[-1] = {**definitions[-1], "cache_control": {"type": "ephemeral"}}
        request: dict[str, Any] = {
            "model": self._settings.model,
            "max_tokens": self._settings.max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": INVESTIGATOR_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "tools": definitions,
            "messages": self._messages,
            **self._settings.thinking_parameter(),
        }
        response: Message = self._client.messages.create(**request)
        return response

    def _handle(self, use: ToolUseBlock, turn: _Turn) -> Outcome | None:
        if use.name == SUBMIT_VERDICT:
            return self._submit(use, turn)
        call = f"{use.name} {json.dumps(use.input, sort_keys=True)}"
        if call == self._last_call:
            return Outcome(Status.LOOP, detail=f"Repeated the same call: {use.name}.")
        self._last_call = call
        text, failed = self._run_tool(use)
        turn.results.append(_tool_result(use.id, text, failed=failed))
        return None

    def _run_tool(self, use: ToolUseBlock) -> tuple[str, bool]:
        tool = self._tools.get(use.name)
        if tool is None:
            return f"There is no tool named {use.name}.", True
        if not self._gate.permits(tool):
            return f"{use.name} is not permitted in this mode.", True
        try:
            text = self._masker.mask(tool.invoke(dict(use.input)))
        except ToolError as error:
            return self._masker.mask(str(error)), True
        self._results[use.id] = text
        return text, False

    def _submit(self, use: ToolUseBlock, turn: _Turn) -> Outcome | None:
        try:
            verdict = Verdict.model_validate(use.input)
        except ValidationError as error:
            return self._reject(use, turn, [f"The verdict does not match the schema: {error}"])
        problems = citation_problems(verdict, self._results)
        if problems:
            return self._reject(use, turn, problems)
        turn.submit_id = use.id
        turn.verdict = verdict
        return None

    def _reject(self, use: ToolUseBlock, turn: _Turn, problems: list[str]) -> Outcome | None:
        if self._corrections == 0:
            return Outcome(Status.NO_VERDICT, detail="Verdict rejected: " + "; ".join(problems))
        self._corrections -= 1
        text = "Rejected. Fix these and submit again:\n" + "\n".join(f"- {p}" for p in problems)
        turn.results.append(_tool_result(use.id, text, failed=True))
        return None


def _content(response: Message) -> list[dict[str, Any]]:
    return [block.model_dump(exclude_none=True) for block in response.content]


def _tool_result(tool_use_id: str, text: str, *, failed: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "tool_result", "tool_use_id": tool_use_id, "content": text}
    if failed:
        result["is_error"] = True
    return result
