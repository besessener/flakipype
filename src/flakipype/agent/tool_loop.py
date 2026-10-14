"""The tool loop investigators and fixers share: call, run tools, check the submission, repeat."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from anthropic.types import Message, ToolUseBlock
from pydantic import BaseModel, ValidationError

from flakipype.agent.budget import BudgetExceededError, InvestigationBudget
from flakipype.agent.masking import Masker
from flakipype.agent.messages import (
    DECLINED,
    ModelSettings,
    cached_messages,
    cached_system,
    cached_tools,
    content_blocks,
    declined,
    tool_result,
)
from flakipype.agent.tools import PolicyGate, Tool, ToolError
from flakipype.llm.client import ModelClient, ModelError

_CORRECTIONS = 2
_NUDGES = 1


class LoopStatus(StrEnum):
    SUBMITTED = "submitted"
    BUDGET = "budget"
    LOOP = "loop"
    STOPPED = "stopped"
    MODEL_ERROR = "model_error"


@dataclass(frozen=True)
class LoopOutcome[Submitted]:
    status: LoopStatus
    submitted: Submitted | None = None
    detail: str = ""


@dataclass(frozen=True)
class Submission[Submitted: BaseModel]:
    """The tool that ends the loop, and what code checks before it is accepted."""

    name: str
    description: str
    model: type[Submitted]
    # "verdict" or "fix": names it in the texts the model and the user see.
    noun: str
    # Problems with a valid submission, given the other results of the same response.
    problems: Callable[[Submitted, list[dict[str, Any]]], list[str]]
    nudge: str
    stopped: Callable[[Message], str]

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.model.model_json_schema(),
        }


@dataclass(frozen=True)
class LoopModel:
    """How the loop reaches the model, and what limits and masks it."""

    client: ModelClient
    settings: ModelSettings
    system: str
    budget: InvestigationBudget
    masker: Masker


@dataclass
class _Turn[Submitted]:
    results: list[dict[str, Any]] = field(default_factory=list)
    submitted: Submitted | None = None
    submit_id: str = ""


def _plain(_use: ToolUseBlock, text: str) -> str:
    return text


class ToolLoop[Submitted: BaseModel]:
    def __init__(  # noqa: PLR0913 - collaborators of one loop, all keyword-only
        self,
        *,
        model: LoopModel,
        tools: list[Tool],
        gate: PolicyGate,
        submission: Submission[Submitted],
        # Turns a tool's masked result into what the model gets, e.g. with a citation id.
        on_result: Callable[[ToolUseBlock, str], str] = _plain,
    ) -> None:
        self._model = model
        self._tools = {tool.name: tool for tool in tools}
        self._gate = gate
        self._submission = submission
        self._on_result = on_result
        self._messages: list[dict[str, Any]] = []
        self._pending: _Turn[Submitted] = _Turn()
        self._corrections = _CORRECTIONS
        self._last_call = ""

    def start(self, opening: str) -> LoopOutcome[Submitted]:
        self._messages.append({"role": "user", "content": opening})
        return self._loop()

    def revise(self, request: str) -> LoopOutcome[Submitted]:
        """Sends the last submission back with the reviewer's request."""
        reply = tool_result(self._pending.submit_id, request, failed=False)
        self._messages.append({"role": "user", "content": [*self._pending.results, reply]})
        self._pending = _Turn()
        return self._loop()

    def _loop(self) -> LoopOutcome[Submitted]:
        nudges = _NUDGES
        budget = self._model.budget
        while True:
            try:
                budget.check()
                response = self._call()
            except BudgetExceededError as error:
                return LoopOutcome(LoopStatus.BUDGET, detail=f"Stopped at {error}.")
            except ModelError as error:
                return LoopOutcome(LoopStatus.MODEL_ERROR, detail=str(error))
            budget.record(response.usage)
            if declined(response):
                return LoopOutcome(LoopStatus.STOPPED, detail=DECLINED)
            self._messages.append({"role": "assistant", "content": content_blocks(response)})
            uses = [block for block in response.content if isinstance(block, ToolUseBlock)]
            if not uses:
                if nudges == 0:
                    detail = self._submission.stopped(response)
                    return LoopOutcome(LoopStatus.STOPPED, detail=detail)
                nudges -= 1
                self._messages.append({"role": "user", "content": self._submission.nudge})
                continue
            outcome = self._answer(uses)
            if outcome is not None:
                return outcome

    def _answer(self, uses: list[ToolUseBlock]) -> LoopOutcome[Submitted] | None:
        turn: _Turn[Submitted] = _Turn()
        # The submission runs last, so its check sees every other result of the response.
        for use in sorted(uses, key=lambda use: use.name == self._submission.name):
            outcome = self._handle(use, turn)
            if outcome is not None:
                return outcome
        order = [use.id for use in uses]
        turn.results.sort(key=lambda result: order.index(result["tool_use_id"]))
        if turn.submitted is not None:
            self._pending = turn
            return LoopOutcome(LoopStatus.SUBMITTED, turn.submitted)
        self._messages.append({"role": "user", "content": turn.results})
        return None

    def _call(self) -> Message:
        definitions = [tool.definition() for tool in self._tools.values()]
        request = self._model.settings.request(
            system=cached_system(self._model.system),
            tools=cached_tools([*definitions, self._submission.definition()]),
            messages=cached_messages(self._messages),
        )
        response: Message = self._model.client.message(request)
        return response

    def _handle(self, use: ToolUseBlock, turn: _Turn[Submitted]) -> LoopOutcome[Submitted] | None:
        if use.name == self._submission.name:
            return self._submit(use, turn)
        call = f"{use.name} {json.dumps(use.input, sort_keys=True)}"
        if call == self._last_call:
            return LoopOutcome(LoopStatus.LOOP, detail=f"Repeated the same call: {use.name}.")
        self._last_call = call
        turn.results.append(self._run_tool(use))
        return None

    def _run_tool(self, use: ToolUseBlock) -> dict[str, Any]:
        tool = self._tools.get(use.name)
        if tool is None:
            return tool_result(use.id, f"There is no tool named {use.name}.", failed=True)
        masker = self._model.masker
        try:
            text = masker.mask(tool.invoke(dict(use.input), self._gate))
        except ToolError as error:
            return tool_result(use.id, masker.mask(str(error)), failed=True)
        return tool_result(use.id, self._on_result(use, text), failed=False)

    def _submit(self, use: ToolUseBlock, turn: _Turn[Submitted]) -> LoopOutcome[Submitted] | None:
        noun = self._submission.noun
        if turn.submitted is not None:
            # The API rejects a tool_use without a result, so an extra submission gets one too.
            text = f"Ignored: the first valid {noun} of this response counts; submit only one."
            turn.results.append(tool_result(use.id, text, failed=True))
            return None
        try:
            submitted = self._submission.model.model_validate(use.input)
        except ValidationError as error:
            return self._reject(use, turn, [f"The {noun} does not match the schema: {error}"])
        problems = self._submission.problems(submitted, turn.results)
        if problems:
            return self._reject(use, turn, problems)
        turn.submit_id = use.id
        turn.submitted = submitted
        return None

    def _reject(
        self, use: ToolUseBlock, turn: _Turn[Submitted], problems: list[str]
    ) -> LoopOutcome[Submitted] | None:
        if self._corrections == 0:
            detail = f"{self._submission.noun.capitalize()} rejected: " + "; ".join(problems)
            return LoopOutcome(LoopStatus.STOPPED, detail=detail)
        self._corrections -= 1
        text = "Rejected. Fix these and submit again:\n" + "\n".join(f"- {p}" for p in problems)
        turn.results.append(tool_result(use.id, text, failed=True))
        return None
