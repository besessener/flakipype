"""The fixer: edits a working copy until the verdict's cause is fixed, then submits the fix."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from anthropic import Anthropic, APIError
from anthropic.types import Message, TextBlock, ToolUseBlock
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from flakipype.agent.budget import BudgetExceededError, InvestigationBudget
from flakipype.agent.investigator import ModelSettings
from flakipype.agent.masking import Masker
from flakipype.agent.messages import cached_system, cached_tools, content_blocks, tool_result
from flakipype.agent.prompts import FIXER_SYSTEM
from flakipype.agent.tools import Mode, PolicyGate, Tool, ToolError, deny_all

SUBMIT_FIX = "submit_fix"
_CORRECTIONS = 2
_NUDGES = 1
_NUDGE = "Continue and finish by calling submit_fix, or say why the cause cannot be fixed."
_REASON_LENGTH = 400

type DiffCheck = Callable[[], list[str]]


class FixProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=5, max_length=72, description="pull request title, imperative")
    explanation: str = Field(
        min_length=20,
        max_length=4_000,
        description="for the pull request: what changes, why it removes the cause, how to check",
    )


class FixDecision(StrEnum):
    ACCEPT = "accept"
    REVISE = "revise"
    REJECT = "reject"


class FixReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: FixDecision
    reason: str
    points: list[str] = Field(default_factory=list, description="for revise: what to change")


class FixStatus(StrEnum):
    PROPOSED = "proposed"
    BUDGET = "budget"
    LOOP = "loop"
    NO_FIX = "no_fix"
    MODEL_ERROR = "model_error"


@dataclass(frozen=True)
class FixOutcome:
    status: FixStatus
    proposal: FixProposal | None = None
    detail: str = ""


@dataclass
class _Turn:
    results: list[dict[str, Any]] = field(default_factory=list)
    proposal: FixProposal | None = None
    submit_id: str = ""


def _submit_tool() -> dict[str, Any]:
    return {
        "name": SUBMIT_FIX,
        "description": "Submit the working copy's edits as the fix; code checks the diff.",
        "input_schema": FixProposal.model_json_schema(),
    }


class Fixer:
    def __init__(  # noqa: PLR0913 - collaborators of one fix, all keyword-only
        self,
        *,
        client: Anthropic,
        settings: ModelSettings,
        tools: list[Tool],
        budget: InvestigationBudget,
        masker: Masker,
        check: DiffCheck,
    ) -> None:
        self._client = client
        self._settings = settings
        self._tools = {tool.name: tool for tool in tools}
        # Every fixer tool only reads or edits memory; anything else is refused.
        self._gate = PolicyGate(Mode.ASK, deny_all)
        self._budget = budget
        self._masker = masker
        self._check = check
        self._messages: list[dict[str, Any]] = []
        self._pending = _Turn()
        self._corrections = _CORRECTIONS
        self._last_call = ""

    def start(self, task: str) -> FixOutcome:
        self._messages.append({"role": "user", "content": self._masker.mask(task)})
        return self._loop()

    def revise(self, points: list[str]) -> FixOutcome:
        asked = "\n".join(f"- {point}" for point in points)
        reply = tool_result(
            self._pending.submit_id,
            f"A reviewer sent the fix back:\n{asked}\nChange the working copy and submit again.",
            failed=False,
        )
        self._messages.append({"role": "user", "content": [*self._pending.results, reply]})
        self._pending = _Turn()
        return self._loop()

    def _loop(self) -> FixOutcome:
        nudges = _NUDGES
        while True:
            try:
                self._budget.check()
                response = self._call()
            except BudgetExceededError as error:
                return FixOutcome(FixStatus.BUDGET, detail=f"Stopped at {error}.")
            except APIError as error:
                return FixOutcome(FixStatus.MODEL_ERROR, detail=str(error))
            self._budget.record(response.usage)
            self._messages.append({"role": "assistant", "content": content_blocks(response)})
            uses = [block for block in response.content if isinstance(block, ToolUseBlock)]
            if not uses:
                if nudges == 0:
                    return FixOutcome(FixStatus.NO_FIX, detail=_stopped(response))
                nudges -= 1
                self._messages.append({"role": "user", "content": _NUDGE})
                continue
            turn = _Turn()
            for use in uses:
                outcome = self._handle(use, turn)
                if outcome is not None:
                    return outcome
            if turn.proposal is not None:
                self._pending = turn
                return FixOutcome(FixStatus.PROPOSED, turn.proposal)
            self._messages.append({"role": "user", "content": turn.results})

    def _call(self) -> Message:
        definitions = [tool.definition() for tool in self._tools.values()] + [_submit_tool()]
        request: dict[str, Any] = {
            "model": self._settings.model,
            "max_tokens": self._settings.max_tokens,
            "system": cached_system(FIXER_SYSTEM),
            "tools": cached_tools(definitions),
            "messages": self._messages,
            **self._settings.thinking_parameter(),
        }
        response: Message = self._client.messages.create(**request)
        return response

    def _handle(self, use: ToolUseBlock, turn: _Turn) -> FixOutcome | None:
        if use.name == SUBMIT_FIX:
            return self._submit(use, turn)
        call = f"{use.name} {json.dumps(use.input, sort_keys=True)}"
        if call == self._last_call:
            return FixOutcome(FixStatus.LOOP, detail=f"Repeated the same call: {use.name}.")
        self._last_call = call
        turn.results.append(self._run_tool(use))
        return None

    def _run_tool(self, use: ToolUseBlock) -> dict[str, Any]:
        tool = self._tools.get(use.name)
        if tool is None:
            return tool_result(use.id, f"There is no tool named {use.name}.", failed=True)
        try:
            text = tool.invoke(dict(use.input), self._gate)
        except ToolError as error:
            return tool_result(use.id, self._masker.mask(str(error)), failed=True)
        return tool_result(use.id, self._masker.mask(text), failed=False)

    def _submit(self, use: ToolUseBlock, turn: _Turn) -> FixOutcome | None:
        try:
            proposal = FixProposal.model_validate(use.input)
        except ValidationError as error:
            return self._reject(use, turn, [f"The proposal does not match the schema: {error}"])
        problems = self._check()
        if problems:
            return self._reject(use, turn, problems)
        turn.submit_id = use.id
        turn.proposal = proposal
        return None

    def _reject(self, use: ToolUseBlock, turn: _Turn, problems: list[str]) -> FixOutcome | None:
        if self._corrections == 0:
            return FixOutcome(FixStatus.NO_FIX, detail="Fix rejected: " + "; ".join(problems))
        self._corrections -= 1
        text = "Rejected. Fix these and submit again:\n" + "\n".join(f"- {p}" for p in problems)
        turn.results.append(tool_result(use.id, text, failed=True))
        return None


def _stopped(response: Message) -> str:
    said = " ".join(block.text for block in response.content if isinstance(block, TextBlock))
    reason = said.strip()[:_REASON_LENGTH]
    return f"The fixer stopped without a fix: {reason}" if reason else "The fixer stopped."
