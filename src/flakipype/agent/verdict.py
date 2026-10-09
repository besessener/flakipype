"""What an investigation concludes, how its citations are checked and how a review applies."""

import re
from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

_WHITESPACE = re.compile(r"\s+")
_MIN_QUOTE = 3


class Classification(StrEnum):
    FLAKY_TEST = "flaky_test"
    FLAKY_INFRASTRUCTURE = "flaky_infrastructure"
    REAL_BUG = "real_bug"
    CONFIGURATION = "configuration"
    FIXED = "fixed"
    UNCLEAR = "unclear"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_CONFIDENCE_ORDER = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}


class EvidenceKind(StrEnum):
    LOG = "log"
    COMMIT = "commit"
    FILE = "file"
    HISTORY = "history"
    SCAN = "scan"


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: EvidenceKind
    tool_call_id: str = Field(description="id of the tool call whose result contains the quote")
    location: str = Field(description="job and lines, commit sha, or path and lines")
    quote: str = Field(description="exact text copied from that tool result")
    why_it_matters: str


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    classification: Classification
    confidence: Confidence
    summary: str = Field(description="two or three sentences for a human")
    cause: str
    evidence: list[EvidenceItem] = Field(min_length=1)
    counter_evidence: list[EvidenceItem] = Field(default_factory=list)
    suggested_fix: str = Field(description="what to change and where, or 'none' for outages")
    open_questions: list[str] = Field(default_factory=list)


class Decision(StrEnum):
    ACCEPT = "accept"
    REVISE = "revise"
    DOWNGRADE = "downgrade"


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Decision
    reason: str
    questions: list[str] = Field(default_factory=list, description="for revise")
    confidence: Confidence | None = Field(default=None, description="for downgrade")
    make_unclear: bool = Field(default=False, description="for downgrade: evidence is too weak")


def _normalise(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def citation_problems(verdict: Verdict, results: Mapping[str, str]) -> list[str]:
    """Quotes that do not appear in the tool result they claim to come from."""
    problems = []
    for item in [*verdict.evidence, *verdict.counter_evidence]:
        result = results.get(item.tool_call_id)
        quote = _normalise(item.quote)
        if result is None:
            problems.append(f"{item.tool_call_id} is not a tool call of this investigation")
        elif len(quote) < _MIN_QUOTE:
            problems.append(f"the quote for {item.location} is too short to check")
        elif quote not in _normalise(result):
            problems.append(
                f"the quote for {item.location} is not in the result of {item.tool_call_id}"
            )
    return problems


def apply_review(verdict: Verdict, review: Review) -> Verdict:
    """Accept or lower confidence; a review never raises it.

    A revise that can no longer be sent back (the round trip is used) counts as low confidence.
    """
    if review.decision is Decision.ACCEPT:
        return verdict
    if review.make_unclear:
        return verdict.model_copy(
            update={"classification": Classification.UNCLEAR, "confidence": Confidence.LOW}
        )
    lowered = Confidence.LOW if review.decision is Decision.REVISE else review.confidence
    lowered = lowered or Confidence.LOW
    if _CONFIDENCE_ORDER[lowered] >= _CONFIDENCE_ORDER[verdict.confidence]:
        return verdict
    return verdict.model_copy(update={"confidence": lowered})
