import pytest

from flakipype.agent.budget import InvestigationBudget, Limits, RunBudget
from flakipype.agent.investigator import ModelSettings, Status
from flakipype.agent.masking import Masker
from flakipype.agent.pipeline import AgentConfig, FindingResult, investigate_finding
from flakipype.agent.reviewer import Reviewer, ReviewUnavailableError
from flakipype.agent.verdict import Decision, Verdict

from support.fake_anthropic import (
    ScriptedModel,
    call,
    message,
    review_input,
    text,
    verdict_input,
)
from support.fake_sources import FakeContents, FakeLogs, evidence, finding

QUOTE = "Test timed out after 5000ms"
EXCERPT = call("toolu_1", "failure_excerpt", {"job_id": 11})


def submit(call_id: str) -> dict[str, object]:
    return call(call_id, "submit_verdict", verdict_input(QUOTE, "toolu_1"))


def review(decision: str, **extra: object) -> dict[str, object]:
    return message(call("toolu_r", "submit_review", review_input(decision, **extra)))


def investigate(model: ScriptedModel, limits: Limits | None = None) -> FindingResult:
    config = AgentConfig(
        client=model.client(),
        settings=ModelSettings(model="m-1"),
        limits=limits or Limits(),
        masker=Masker(),
        logs=FakeLogs(),
        contents=FakeContents(),
        clock=lambda: 0.0,
    )
    return investigate_finding(config, finding(), evidence=evidence(), run_budget=RunBudget(10**7))


def test_accepted_verdict() -> None:
    model = ScriptedModel([message(EXCERPT), message(submit("toolu_2")), review("accept")])

    result = investigate(model)

    assert result.status is Status.COMPLETED
    assert result.verdict is not None
    assert result.verdict.confidence.value == "high"
    assert result.review == "accepted: checked"
    assert (result.rounds, result.tokens) == (3, 3_600)
    reviewer_request = model.requests[2]
    assert reviewer_request["tool_choice"] == {"type": "tool", "name": "submit_review"}
    assert "thinking" not in reviewer_request
    assert QUOTE in reviewer_request["messages"][0]["content"]


def test_downgrade() -> None:
    model = ScriptedModel(
        [message(EXCERPT), message(submit("toolu_2")), review("downgrade", confidence="medium")]
    )

    result = investigate(model)

    assert result.verdict is not None
    assert result.verdict.confidence.value == "medium"
    assert result.review == "downgrade: checked"


def test_sent_back_once_then_accepted() -> None:
    model = ScriptedModel(
        [
            message(EXCERPT),
            message(submit("toolu_2")),
            review("revise", questions=["Which commit?"]),
            message(submit("toolu_3")),
            review("accept"),
        ]
    )

    result = investigate(model)

    assert result.review == "revised, then accepted: checked"
    assert result.verdict is not None
    assert result.verdict.confidence.value == "high"


def test_a_second_revise_counts_as_low_confidence() -> None:
    model = ScriptedModel(
        [
            message(EXCERPT, submit("toolu_2")),
            review("revise", questions=["?"]),
            message(submit("toolu_3")),
            review("revise", questions=["?"]),
        ]
    )

    result = investigate(model)

    assert result.verdict is not None
    assert result.verdict.confidence.value == "low"
    assert result.review.startswith("revised, then revise")


def test_revision_that_ends_without_verdict_keeps_the_first_at_low_confidence() -> None:
    model = ScriptedModel(
        [message(EXCERPT, submit("toolu_2")), review("revise", questions=["?"]), 500]
    )

    result = investigate(model)

    assert result.status is Status.COMPLETED
    assert result.verdict is not None
    assert result.verdict.confidence.value == "low"
    assert result.review.startswith("sent back, revision ended")


def test_unavailable_reviews_leave_the_verdict_unreviewed() -> None:
    first = investigate(ScriptedModel([message(EXCERPT, submit("toolu_2")), 500]))
    second = investigate(
        ScriptedModel(
            [
                message(EXCERPT, submit("toolu_2")),
                review("revise", questions=["?"]),
                message(submit("toolu_3")),
                500,
            ]
        )
    )

    assert first.review.startswith("not reviewed")
    assert second.review.startswith("revised, second review unavailable")
    assert second.verdict is not None


def test_failed_investigation_is_not_reviewed() -> None:
    result = investigate(ScriptedModel([message(text("no idea")), message(text("still none"))]))

    assert (result.status, result.verdict, result.review) == (Status.NO_VERDICT, None, "")


@pytest.mark.parametrize(
    "answer",
    [
        message(text("Looks fine to me.")),
        message(call("toolu_r", "submit_review", {"decision": "approve"})),
    ],
)
def test_unusable_reviews_raise(answer: dict[str, object]) -> None:
    model = ScriptedModel([answer])
    budget = InvestigationBudget(Limits(), RunBudget(10**6), lambda: 0.0)
    reviewer = Reviewer(client=model.client(), settings=ModelSettings(model="m-1"), budget=budget)
    verdict = Verdict.model_validate(verdict_input(QUOTE, "toolu_1"))

    with pytest.raises(ReviewUnavailableError):
        reviewer.review("finding", verdict, Masker())


def test_review_decisions_are_complete() -> None:
    assert {decision.value for decision in Decision} == {"accept", "revise", "downgrade"}
