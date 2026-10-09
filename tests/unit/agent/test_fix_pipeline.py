from typing import Any

from flakipype.agent.budget import Limits
from flakipype.agent.fix_pipeline import FixConfig, FixRequest, FixResult, propose_fix
from flakipype.agent.fixer import FixStatus
from flakipype.agent.investigator import ModelSettings
from flakipype.agent.masking import Masker
from flakipype.agent.verdict import Verdict
from flakipype.agent.workcopy import FileChange

from support.fake_anthropic import ScriptedModel, call, message, text, verdict_input
from support.fake_files import E2E_TEST, FakeFiles
from support.fake_sources import FakeContents, FakeLogs, evidence, finding

COMMIT = "3f2a9c1" + "0" * 33
EDIT = call(
    "toolu_1", "replace_in_file", {"path": E2E_TEST, "old": "waitForTimeout(500)", "new": "x()"}
)
PROPOSAL = {"title": "Wait for the rows", "explanation": "Waits for the rows instead of 500 ms."}


def submit(call_id: str) -> dict[str, Any]:
    return message(call(call_id, "submit_fix", PROPOSAL))


def review(decision: str, **extra: object) -> dict[str, Any]:
    return message(
        call("toolu_r", "submit_review", {"decision": decision, "reason": "ok", **extra})
    )


def propose(
    model: ScriptedModel,
    *,
    check: list[list[str]] | None = None,
    limits: Limits | None = None,
    earlier: tuple[FileChange, ...] = (),
    instructions: str = "",
) -> FixResult:
    answers = iter(check or [])
    config = FixConfig(
        client=model.client(),
        settings=ModelSettings(model="m-1"),
        limits=limits or Limits(rounds=20, tokens=300_000, seconds=600),
        masker=Masker.with_secrets(["sk-hidden-value"]),
        logs=FakeLogs(),
        contents=FakeContents(),
        files=FakeFiles(),
        clock=lambda: 0.0,
    )
    request = FixRequest(
        finding=finding(),
        evidence=evidence(),
        verdict=Verdict.model_validate(verdict_input("timed out", "toolu_9")),
        commit=COMMIT,
        default_branch="main",
        check=lambda changes: next(answers, []) if changes else ["no changes"],
        earlier=earlier,
        instructions=instructions,
    )
    return propose_fix(config, request)


def test_an_accepted_fix() -> None:
    model = ScriptedModel([message(EDIT), submit("toolu_2"), review("accept")])

    result = propose(model)

    assert result.status is FixStatus.PROPOSED
    assert result.accepted
    assert result.review == "accepted: ok"
    assert result.proposal is not None
    assert result.proposal.title == "Wait for the rows"
    (change,) = result.changes
    assert change.added == ["  await page.x();"]
    assert result.tokens == 3_600
    fixer_tools = {tool["name"] for tool in model.requests[0]["tools"]}
    assert {"replace_in_file", "show_diff", "failure_excerpt", "submit_fix"} <= fixer_tools
    assert "compare_commits" in fixer_tools
    review_text = model.requests[2]["messages"][0]["content"]
    assert "+  await page.x();" in review_text
    assert "Wait for the rows" in review_text
    task = model.requests[0]["messages"][0]["content"]
    assert f"at commit {COMMIT[:12]} of main" in task
    assert "<verdict" in task


def test_failed_checks_go_back_to_the_fixer() -> None:
    model = ScriptedModel([message(EDIT), submit("toolu_2"), submit("toolu_3"), review("accept")])

    result = propose(model, check=[["too many lines"]])

    assert result.accepted
    rejected = model.tool_results(2)["toolu_2"]
    assert rejected["is_error"]
    assert "- too many lines" in rejected["content"]


def test_checks_end_the_fix_after_two_corrections() -> None:
    model = ScriptedModel([submit("toolu_1"), submit("toolu_2"), submit("toolu_3")])

    result = propose(model)

    assert result.status is FixStatus.NO_FIX
    assert result.detail == "Fix rejected: no changes"
    assert result.proposal is None


def test_an_invalid_proposal_is_sent_back() -> None:
    bad = message(call("toolu_1", "submit_fix", {"title": "x"}))
    model = ScriptedModel([message(EDIT), bad, submit("toolu_3"), review("accept")])

    result = propose(model)

    assert result.accepted
    assert "does not match the schema" in model.tool_results(2)["toolu_1"]["content"]


def test_sent_back_once_then_accepted() -> None:
    model = ScriptedModel(
        [
            message(EDIT),
            submit("toolu_2"),
            review("revise", points=["keep the assertion"]),
            submit("toolu_3"),
            review("accept"),
        ]
    )

    result = propose(model)

    assert result.accepted
    assert result.review == "revised, then accepted: ok"
    sent_back = model.tool_results(3)["toolu_2"]
    assert "- keep the assertion" in sent_back["content"]
    assert "is_error" not in sent_back


def test_a_second_revise_is_not_accepted() -> None:
    model = ScriptedModel(
        [message(EDIT), submit("toolu_2"), review("revise"), submit("toolu_3"), review("revise")]
    )

    result = propose(model)

    assert not result.accepted
    assert result.review == "revised, then sent back again: ok"
    assert "- ok" in model.tool_results(3)["toolu_2"]["content"]


def test_a_rejected_fix_keeps_its_diff_for_the_user() -> None:
    model = ScriptedModel([message(EDIT), submit("toolu_2"), review("reject")])

    result = propose(model)

    assert not result.accepted
    assert result.review == "rejected: ok"
    assert result.changes


def test_reviews_that_do_not_come_back() -> None:
    first = propose(ScriptedModel([message(EDIT), submit("toolu_2"), 500]))
    second = propose(
        ScriptedModel([message(EDIT), submit("toolu_2"), review("revise"), submit("toolu_3"), 500])
    )

    assert first.review.startswith("not reviewed:")
    assert not first.accepted
    assert second.review.startswith("revised, not reviewed again:")


def test_a_revision_that_ends_without_a_fix() -> None:
    model = ScriptedModel(
        [message(EDIT), submit("toolu_2"), review("revise"), message(text("No.")), 500]
    )

    result = propose(model)

    assert result.status is FixStatus.MODEL_ERROR
    assert result.review.startswith("sent back, revision ended: Error code: 500")


def test_a_fixer_that_gives_up_says_why() -> None:
    model = ScriptedModel([message(text("Cannot fix.")), message(text("It is upstream."))])
    silent = ScriptedModel([message(text("")), message(text(""))])

    result = propose(model)

    assert result.status is FixStatus.NO_FIX
    assert result.detail == "The fixer stopped without a fix: It is upstream."
    assert propose(silent).detail == "The fixer stopped."
    assert model.requests[1]["messages"][-1]["content"].startswith("Continue and finish")


def test_limits_loops_and_model_errors_end_the_fix() -> None:
    looping = ScriptedModel([message(EDIT), message(EDIT)])
    budget = ScriptedModel([message(EDIT)])
    failing = ScriptedModel([529])

    assert propose(looping).status is FixStatus.LOOP
    assert propose(budget, limits=Limits(rounds=1)).detail == "Stopped at the limit of 1 rounds."
    assert propose(failing).status is FixStatus.MODEL_ERROR


def test_unknown_and_failing_tools_answer_with_errors() -> None:
    model = ScriptedModel(
        [
            message(
                call("toolu_1", "push", {}),
                call("toolu_2", "read_file", {"path": "missing.txt"}),
            ),
            submit("toolu_3"),
            submit("toolu_4"),
            submit("toolu_5"),
        ]
    )

    propose(model)

    results = model.tool_results(1)
    assert results["toolu_1"]["content"] == "There is no tool named push."
    assert "does not exist in the working copy" in results["toolu_2"]["content"]


def test_an_earlier_proposal_and_the_users_wishes_are_the_starting_point() -> None:
    earlier = FileChange("NOTES.md", None, "sk-hidden-value\n")
    model = ScriptedModel([submit("toolu_1"), review("accept")])

    result = propose(model, earlier=(earlier,), instructions="Keep the assertion.")

    assert result.changes == (earlier,)
    task = model.requests[0]["messages"][0]["content"]
    assert "asked in the chat for these changes to it:\nKeep the assertion." in task
    assert "sk-hidden-value" not in model.requests[1]["messages"][0]["content"]
