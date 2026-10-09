"""The chat agent: answers the user and drives scans and investigations through tools."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from anthropic import Anthropic, APIError
from anthropic.types import Message, TextBlock, ToolUseBlock
from pydantic import BaseModel, Field

from flakipype.agent.budget import BudgetExceededError, InvestigationBudget, Limits, RunBudget
from flakipype.agent.investigator import ModelSettings
from flakipype.agent.masking import Masker
from flakipype.agent.messages import cached_system, cached_tools, content_blocks
from flakipype.agent.prompts import CHAT_SYSTEM, data_block
from flakipype.agent.tools import (
    PolicyGate,
    PreparedAction,
    RiskLevel,
    Tool,
    ToolDeclinedError,
    ToolError,
)

type StepListener = Callable[[str], None]


def ignore_steps(step: str) -> None:
    del step


class Workspace(Protocol):
    """What the chat can do; implemented on top of the scan and investigation services."""

    def scan(self, days: int | None, repositories: tuple[str, ...]) -> str: ...

    def findings(self) -> str: ...

    def investigate(self, numbers: tuple[int, ...], *, fresh: bool) -> str: ...

    def verdict(self, number: int) -> str: ...

    def rerun_failed(self, finding: int, run_id: int | None) -> PreparedAction: ...

    def rerun_run(self, finding: int, run_id: int | None) -> PreparedAction: ...

    def dispatch(self, finding: int, ref: str | None, repeats: int) -> PreparedAction: ...

    def cancel(self, run: int) -> PreparedAction: ...

    def watched_runs(self) -> str: ...


class ScanInput(BaseModel):
    days: int | None = Field(default=None, ge=1, le=400, description="default: configuration")
    repositories: list[str] = Field(default_factory=list, description="names; empty means all")


class NoInput(BaseModel):
    pass


class InvestigateInput(BaseModel):
    findings: list[int] = Field(min_length=1, max_length=10, description="finding numbers")
    fresh: bool = Field(default=False, description="ignore stored verdicts")


class VerdictInput(BaseModel):
    finding: int = Field(ge=1)


class RerunInput(BaseModel):
    finding: int = Field(ge=1)
    run_id: int | None = Field(default=None, description="default: the newest failed run")


class DispatchInput(BaseModel):
    finding: int = Field(ge=1)
    ref: str | None = Field(default=None, max_length=255, description="default: default branch")
    repeats: int = Field(default=1, ge=1, le=10)


class CancelInput(BaseModel):
    run: int = Field(ge=1, description="the R number of a started run")


def workspace_tools(workspace: Workspace) -> list[Tool]:
    read, write = RiskLevel.READ, RiskLevel.WRITE
    return [
        Tool("scan", "Scan the workflow runs and number the findings.", read, ScanInput,
             lambda given: workspace.scan(given.days, tuple(given.repositories))),
        Tool("list_findings", "The numbered findings of the current scan.", read, NoInput,
             lambda _: workspace.findings()),
        Tool("investigate", "Investigate findings by number; costs model tokens.", read,
             InvestigateInput,
             lambda given: workspace.investigate(tuple(given.findings), fresh=given.fresh)),
        Tool("show_verdict", "A stored verdict with its evidence.", read, VerdictInput,
             lambda given: workspace.verdict(given.finding)),
        Tool("rerun_failed", "Rerun the failed jobs of a finding's run.", write, RerunInput,
             lambda given: workspace.rerun_failed(given.finding, given.run_id)),
        Tool("rerun_run", "Rerun all jobs of a finding's run.", write, RerunInput,
             lambda given: workspace.rerun_run(given.finding, given.run_id)),
        Tool("dispatch", "Start a finding's workflow on a branch or tag.", write, DispatchInput,
             lambda given: workspace.dispatch(given.finding, given.ref, given.repeats)),
        Tool("cancel", "Cancel a run started in this session.", write, CancelInput,
             lambda given: workspace.cancel(given.run)),
        Tool("watched_runs", "Runs started in this session and their state.", read, NoInput,
             lambda _: workspace.watched_runs()),
    ]  # fmt: skip


@dataclass(frozen=True)
class Reply:
    text: str
    tokens: int
    # False when a limit or an error ended the turn; the turn is then not kept in the history.
    completed: bool


@dataclass(frozen=True)
class ChatSettings:
    model: ModelSettings
    limits: Limits
    turn_tokens: int


class ChatAgent:
    def __init__(  # noqa: PLR0913 - collaborators of the chat, all keyword-only
        self,
        *,
        client: Anthropic,
        settings: ChatSettings,
        tools: list[Tool],
        gate: PolicyGate,
        masker: Masker,
        clock: Callable[[], float],
    ) -> None:
        self._client = client
        self._settings = settings
        self._tools = {tool.name: tool for tool in tools}
        self._gate = gate
        self._masker = masker
        self._clock = clock
        self._messages: list[dict[str, Any]] = []
        self._tool_seconds = 0.0
        self._declined = False

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._messages)

    def restore(self, history: list[dict[str, Any]]) -> None:
        self._messages = list(history)

    def run_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """A tool asked for by the user directly; it passes the same gate as the model's calls."""
        return self._tools[name].invoke(arguments, self._gate)

    def ask(self, question: str, on_step: StepListener = ignore_steps) -> Reply:
        self._tool_seconds = 0.0
        self._declined = False
        budget = InvestigationBudget(
            self._settings.limits, RunBudget(self._settings.turn_tokens), self._model_clock
        )
        start = len(self._messages)
        self._messages.append({"role": "user", "content": self._masker.mask(question)})
        last_call = ""
        while True:
            try:
                budget.check()
                response = self._call()
            except BudgetExceededError as error:
                return self._abandon(start, f"Stopped at {error}.", budget.tokens)
            except APIError as error:
                return self._abandon(start, f"The model could not answer: {error}", budget.tokens)
            budget.record(response.usage)
            self._messages.append({"role": "assistant", "content": content_blocks(response)})
            uses = [block for block in response.content if isinstance(block, ToolUseBlock)]
            if not uses:
                return Reply(_text(response), budget.tokens, completed=True)
            calls = " ".join(f"{use.name} {json.dumps(use.input, sort_keys=True)}" for use in uses)
            if calls == last_call:
                return self._abandon(start, "Stopped: the same tool call repeated.", budget.tokens)
            last_call = calls
            results = [self._run(use, on_step) for use in uses]
            self._messages.append({"role": "user", "content": results})

    def _model_clock(self) -> float:
        # Investigations have their own limits; the turn's time limit counts only the chat itself.
        return self._clock() - self._tool_seconds

    def _abandon(self, start: int, reason: str, tokens: int) -> Reply:
        # An unfinished turn would leave tool calls without results, which the API rejects later.
        del self._messages[start:]
        return Reply(reason, tokens, completed=False)

    def _call(self) -> Message:
        definitions = [tool.definition() for tool in self._tools.values()]
        request: dict[str, Any] = {
            "model": self._settings.model.model,
            "max_tokens": self._settings.model.max_tokens,
            "system": cached_system(CHAT_SYSTEM),
            "tools": cached_tools(definitions),
            "messages": self._messages,
            **self._settings.model.thinking_parameter(),
        }
        response: Message = self._client.messages.create(**request)
        return response

    def _run(self, use: ToolUseBlock, on_step: StepListener) -> dict[str, Any]:
        tool = self._tools.get(use.name)
        result: dict[str, Any] = {"type": "tool_result", "tool_use_id": use.id}
        if tool is None:
            return {**result, "content": f"{use.name} is not available.", "is_error": True}
        if self._declined and tool.risk is not RiskLevel.READ:
            declined = "The user declined an action in this turn; do not ask for another one."
            return {**result, "content": declined, "is_error": True}
        on_step(use.name)
        started = self._clock()
        try:
            text = tool.invoke(dict(use.input), self._gate)
        except ToolDeclinedError as error:
            self._declined = True
            return {**result, "content": str(error), "is_error": True}
        except ToolError as error:
            return {**result, "content": self._masker.mask(str(error)), "is_error": True}
        finally:
            self._tool_seconds += self._clock() - started
        return {
            **result,
            "content": self._masker.mask(data_block("tool-result", text, tool=use.name)),
        }


def _text(response: Message) -> str:
    return "\n\n".join(block.text for block in response.content if isinstance(block, TextBlock))
