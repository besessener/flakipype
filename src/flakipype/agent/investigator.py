"""One investigation: a tool loop over the Messages API that ends in a checked verdict."""

from dataclasses import dataclass
from enum import StrEnum

from anthropic import Anthropic
from anthropic.types import Message, ToolUseBlock

from flakipype.agent.budget import InvestigationBudget
from flakipype.agent.masking import Masker
from flakipype.agent.messages import ModelSettings
from flakipype.agent.prompts import INVESTIGATOR_SYSTEM
from flakipype.agent.tool_loop import LoopModel, LoopOutcome, LoopStatus, Submission, ToolLoop
from flakipype.agent.tools import PolicyGate, Tool
from flakipype.agent.verdict import FINDING_REFERENCE, Verdict, citation_problems

SUBMIT_VERDICT = "submit_verdict"
_NUDGE = "Continue the investigation and finish by calling submit_verdict."
_RESULT_PREFIX = "r"


class Status(StrEnum):
    COMPLETED = "completed"
    BUDGET = "budget"
    LOOP = "loop"
    NO_VERDICT = "no_verdict"
    MODEL_ERROR = "model_error"
    FAILED = "failed"


@dataclass(frozen=True)
class Outcome:
    status: Status
    verdict: Verdict | None = None
    detail: str = ""


_STATUSES = {
    LoopStatus.SUBMITTED: Status.COMPLETED,
    LoopStatus.BUDGET: Status.BUDGET,
    LoopStatus.LOOP: Status.LOOP,
    LoopStatus.STOPPED: Status.NO_VERDICT,
    LoopStatus.MODEL_ERROR: Status.MODEL_ERROR,
}


def _stopped(_response: Message) -> str:
    return "The model stopped without a verdict."


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
        self._masker = masker
        self._results: dict[str, str] = {}
        self._citable = 0
        submission = Submission(
            name=SUBMIT_VERDICT,
            description="Submit the verdict; ends the investigation. Quotes are checked.",
            model=Verdict,
            noun="verdict",
            problems=lambda verdict, _: citation_problems(verdict, self._results),
            nudge=_NUDGE,
            stopped=_stopped,
        )
        model = LoopModel(client, settings, INVESTIGATOR_SYSTEM, budget, masker)
        self._loop = ToolLoop(
            model=model,
            tools=tools,
            gate=gate,
            submission=submission,
            on_result=self._citable_result,
        )

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
        return _outcome(self._loop.start(opening))

    def revise(self, questions: list[str]) -> Outcome:
        asked = "\n".join(f"- {question}" for question in questions)
        return _outcome(
            self._loop.revise(
                f"A reviewer sent the verdict back with these questions:\n{asked}\n"
                "Investigate further and submit a revised verdict."
            )
        )

    def _citable_result(self, use: ToolUseBlock, text: str) -> str:
        # Models do not reliably copy the random tool_use ids; a short id they can see, they do.
        self._citable += 1
        reference = f"{_RESULT_PREFIX}{self._citable}"
        self._results[use.id] = text
        self._results[reference] = text
        return f'Cite this result with tool_call_id "{reference}".\n{text}'


def _outcome(outcome: LoopOutcome[Verdict]) -> Outcome:
    return Outcome(_STATUSES[outcome.status], outcome.submitted, outcome.detail)
