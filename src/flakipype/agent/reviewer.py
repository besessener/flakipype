"""Second opinions: on a verdict (accept, send back once, downgrade) and on a fix's diff."""

from dataclasses import dataclass
from typing import Any

from anthropic import Anthropic, APIError
from anthropic.types import Message, ToolUseBlock
from pydantic import BaseModel, ValidationError

from flakipype.agent.budget import BudgetExceededError, InvestigationBudget
from flakipype.agent.investigator import ModelSettings
from flakipype.agent.masking import Masker
from flakipype.agent.messages import content_blocks
from flakipype.agent.prompts import REVIEWER_SYSTEM, data_block
from flakipype.agent.verdict import Review, Verdict

SUBMIT_REVIEW = "submit_review"
_NUDGE = "Answer by calling submit_review."


class ReviewUnavailableError(Exception):
    """No usable review came back; the verdict stays unreviewed."""


@dataclass(frozen=True)
class ReviewKind[Answer: BaseModel]:
    """What is reviewed: the reviewer's instructions and the shape of its answer."""

    system: str
    description: str
    answer: type[Answer]


VERDICT_REVIEW = ReviewKind(REVIEWER_SYSTEM, "Submit your review of the verdict.", Review)


def review_request(finding_text: str, verdict: Verdict) -> str:
    return (
        f"{finding_text}\n\n"
        + data_block("verdict", verdict.model_dump_json(indent=2))
        + "\n\nReview this verdict and answer with submit_review."
    )


class Reviewer:
    def __init__(
        self, *, client: Anthropic, settings: ModelSettings, budget: InvestigationBudget
    ) -> None:
        self._client = client
        self._settings = settings
        self._budget = budget

    def review(self, finding_text: str, verdict: Verdict, masker: Masker) -> Review:
        """Raises ReviewUnavailableError when the model call fails or the answer is unusable."""
        return self.ask(VERDICT_REVIEW, masker.mask(review_request(finding_text, verdict)))

    def ask[Answer: BaseModel](self, kind: ReviewKind[Answer], content: str) -> Answer:
        """One review of masked content; raises ReviewUnavailableError if none comes back."""
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
        # Some models refuse a forced tool_choice, so the reviewer is asked, and nudged once.
        response = self._call(kind, messages)
        uses = [block for block in response.content if isinstance(block, ToolUseBlock)]
        if not uses:
            messages.append({"role": "assistant", "content": content_blocks(response)})
            messages.append({"role": "user", "content": _NUDGE})
            response = self._call(kind, messages)
            uses = [block for block in response.content if isinstance(block, ToolUseBlock)]
        if not uses:
            message = "the reviewer answered without a review"
            raise ReviewUnavailableError(message)
        try:
            return kind.answer.model_validate(uses[0].input)
        except ValidationError as error:
            raise ReviewUnavailableError(str(error)) from error

    def _call(self, kind: ReviewKind[Any], messages: list[dict[str, Any]]) -> Message:
        tool = {
            "name": SUBMIT_REVIEW,
            "description": kind.description,
            "input_schema": kind.answer.model_json_schema(),
        }
        request: dict[str, Any] = {
            "model": self._settings.model,
            "max_tokens": self._settings.max_tokens,
            "system": kind.system,
            "tools": [tool],
            "messages": messages,
            **self._settings.thinking_parameter(),
        }
        try:
            self._budget.check()
            response: Message = self._client.messages.create(**request)
        except (APIError, BudgetExceededError) as error:
            raise ReviewUnavailableError(str(error)) from error
        self._budget.record(response.usage)
        return response
