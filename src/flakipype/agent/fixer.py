"""The fixer: edits a working copy until the verdict's cause is fixed, then submits the fix."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from anthropic import Anthropic
from anthropic.types import Message, TextBlock
from pydantic import BaseModel, ConfigDict, Field

from flakipype.agent.budget import InvestigationBudget
from flakipype.agent.masking import Masker
from flakipype.agent.messages import ModelSettings
from flakipype.agent.prompts import FIXER_SYSTEM
from flakipype.agent.tool_loop import LoopModel, LoopOutcome, LoopStatus, Submission, ToolLoop
from flakipype.agent.tools import Mode, PolicyGate, Tool, deny_all

SUBMIT_FIX = "submit_fix"
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


_STATUSES = {
    LoopStatus.SUBMITTED: FixStatus.PROPOSED,
    LoopStatus.BUDGET: FixStatus.BUDGET,
    LoopStatus.LOOP: FixStatus.LOOP,
    LoopStatus.STOPPED: FixStatus.NO_FIX,
    LoopStatus.MODEL_ERROR: FixStatus.MODEL_ERROR,
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
        self._masker = masker
        self._check = check
        submission = Submission(
            name=SUBMIT_FIX,
            description="Submit the working copy's edits as the fix; code checks the diff.",
            model=FixProposal,
            noun="fix",
            problems=self._problems,
            nudge=_NUDGE,
            stopped=_stopped,
        )
        model = LoopModel(client, settings, FIXER_SYSTEM, budget, masker)
        # Every fixer tool only reads or edits memory; anything else is refused.
        gate = PolicyGate(Mode.ASK, deny_all)
        self._loop = ToolLoop(model=model, tools=tools, gate=gate, submission=submission)

    def start(self, task: str) -> FixOutcome:
        return _outcome(self._loop.start(self._masker.mask(task)))

    def revise(self, points: list[str]) -> FixOutcome:
        asked = "\n".join(f"- {point}" for point in points)
        return _outcome(
            self._loop.revise(
                f"A reviewer sent the fix back:\n{asked}\nChange the working copy and submit again."
            )
        )

    def _problems(self, _proposal: FixProposal, results: list[dict[str, Any]]) -> list[str]:
        failed = sum(1 for result in results if result.get("is_error"))
        if failed:
            return [f"{failed} other call(s) in this response failed; fix them first."]
        return self._check()


def _outcome(outcome: LoopOutcome[FixProposal]) -> FixOutcome:
    return FixOutcome(_STATUSES[outcome.status], outcome.submitted, outcome.detail)


def _stopped(response: Message) -> str:
    said = " ".join(block.text for block in response.content if isinstance(block, TextBlock))
    reason = said.strip()[:_REASON_LENGTH]
    return f"The fixer stopped without a fix: {reason}" if reason else "The fixer stopped."
