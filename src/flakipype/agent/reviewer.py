"""The second opinion on a verdict: accept, send back once, or downgrade."""

from typing import Any

from anthropic import Anthropic, APIError
from anthropic.types import Message, ToolUseBlock
from pydantic import ValidationError

from flakipype.agent.budget import BudgetExceededError, InvestigationBudget
from flakipype.agent.investigator import ModelSettings
from flakipype.agent.masking import Masker
from flakipype.agent.prompts import REVIEWER_SYSTEM, data_block
from flakipype.agent.verdict import Review, Verdict

SUBMIT_REVIEW = "submit_review"
_NUDGE = "Answer by calling submit_review."


class ReviewUnavailableError(Exception):
    """No usable review came back; the verdict stays unreviewed."""


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
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": masker.mask(review_request(finding_text, verdict))}
        ]
        # Some models refuse a forced tool_choice, so the reviewer is asked, and nudged once.
        response = self._call(messages)
        uses = [block for block in response.content if isinstance(block, ToolUseBlock)]
        if not uses:
            messages.append({"role": "assistant", "content": _content(response)})
            messages.append({"role": "user", "content": _NUDGE})
            response = self._call(messages)
            uses = [block for block in response.content if isinstance(block, ToolUseBlock)]
        if not uses:
            message = "the reviewer answered without a review"
            raise ReviewUnavailableError(message)
        try:
            return Review.model_validate(uses[0].input)
        except ValidationError as error:
            raise ReviewUnavailableError(str(error)) from error

    def _call(self, messages: list[dict[str, Any]]) -> Message:
        tool = {
            "name": SUBMIT_REVIEW,
            "description": "Submit your review of the verdict.",
            "input_schema": Review.model_json_schema(),
        }
        request: dict[str, Any] = {
            "model": self._settings.model,
            "max_tokens": self._settings.max_tokens,
            "system": REVIEWER_SYSTEM,
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


def _content(response: Message) -> list[dict[str, Any]]:
    return [block.model_dump(exclude_none=True) for block in response.content]
