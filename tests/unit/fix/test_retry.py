from dataclasses import replace

import pytest

from flakipype.agent.tools import Answer, ToolError
from flakipype.agent.verdict import ReviewState
from flakipype.config.settings import FixSettings
from flakipype.fix.delivery import DeliveryError
from flakipype.fix.service import FixDeliveryError, FixTarget
from flakipype.fix.state import OpenedPull
from flakipype.fix.verify import Stage
from flakipype.flaky.signature import signature_from_log
from flakipype.github.actions import GitHubApiError
from flakipype.github.runs import CommitRun
from flakipype.store.audit import AuditStatus
from flakipype.store.database import ScanCache

from support.builders import job
from support.fake_fix import (
    EXPLANATION,
    FIX_COMMIT,
    PROSE,
    TITLE,
    FakeFixer,
    FixWorld,
    fixed,
    verdict,
)
from support.fake_runs import E2E, e2e_evidence, e2e_finding, state

STAMP = "2026-10-07T09:27:35.3592891Z "
SAME_LOG = f"{STAMP}##[error]Process completed with exit code 1.\n"
SECOND_COMMIT = "5eed000" + "0" * 33
SERVER_ERROR = GitHubApiError("Server Error (HTTP 500)", 500)


def target() -> FixTarget:
    signature = signature_from_log(SAME_LOG)
    assert signature is not None
    evidence = replace(e2e_evidence(), signatures={41: signature})
    return FixTarget(e2e_finding(), evidence, verdict(), ReviewState.ANSWERED, "accepted")


def opened(world: FixWorld) -> OpenedPull:
    """A fix pushed as pull request #12, whose first verification run is the finding's job."""
    world.github.files[E2E] = b"on: pull_request\njobs: {}\n"
    world.github.keep_opened = True
    world.github.commit_shas = [FIX_COMMIT, SECOND_COMMIT]
    world.fixes.prepare(target()).run(Answer.CONFIRMED)
    world.github.runs_by_commit[FIX_COMMIT] = [CommitRun(91, "pull_request")]
    world.runs.states[91] = [state(91)]
    world.logs.jobs_by_attempt[91, 1] = [job(5, run_id=91, name="e2e")]
    world.logs.logs[5] = SAME_LOG
    return world.fixes.pulls[0]


def did_not_hold(world: FixWorld) -> list[str]:
    opened(world)
    world.fixes.poll()
    world.actions.poll()
    return world.fixes.poll()


def single_run() -> FixSettings:
    return FixSettings(verify_runs=1)


def test_a_verification_that_shows_the_error_again_offers_a_retry(cache: ScanCache) -> None:
    world = FixWorld(cache, fix_settings=single_run())

    (note,) = did_not_hold(world)

    assert note.endswith(
        "\nThe fix did not hold: /fix 2 tries again with the failure log (attempt 2 of 2)."
    )
    (pull,) = world.fixes.retries_pending()
    assert pull.verification.same_error_jobs == (5,)


def test_a_retry_revises_the_pushed_fix_with_the_failure_log(cache: ScanCache) -> None:
    world = FixWorld(cache, fix_settings=single_run())
    did_not_hold(world)
    pull = world.fixes.pulls[0]

    request = world.fixes.prepare(target()).request

    assert request.title == "Push a revised fix to draft pull request #12?"
    assert request.details[:2] == (
        f"octo-org/app · branch {pull.branch} @ c0ffee1",
        "one more commit on draft pull request #12, attempt 2 of 2",
    )
    assert request.details[3:] == (
        "then reruns E2E on the fix branch 1 times",
        "Actions: 0 of 10",
        "The pull request stays a draft; merging stays with you.",
        "Warnings: none",
    )
    retry = world.fixer.requests[-1]
    assert (retry.commit, retry.default_branch, retry.earlier) == (FIX_COMMIT, pull.branch, ())
    assert retry.failed_verification is not None
    assert retry.failed_verification.jobs == (5,)
    assert "the fix did not hold" in retry.failed_verification.outcome


def test_a_confirmed_retry_is_one_more_commit_on_the_same_branch(cache: ScanCache) -> None:
    world = FixWorld(cache, fix_settings=single_run())
    did_not_hold(world)
    branch = world.fixes.pulls[0].branch
    prepared = world.fixes.prepare(target())
    world.github.calls.clear()

    outcome = prepared.run(Answer.CONFIRMED)

    assert outcome.startswith(
        "Pushed a revised fix to draft pull request #12: https://github.com/octo-org/app/pull/12 "
        "(attempt 2 of 2, commit 5eed000).\nVerification: 1 runs of E2E"
    )
    assert world.github.calls[:2] == [
        "open_pulls octo-org/app",
        f"commit_files octo-org/app {branch}",
    ]
    assert not [
        call for call in world.github.calls if call.split()[0] in {"create_branch", "open_draft"}
    ]
    commit = world.github.commits[-1]
    assert (commit.branch, commit.expected_head) == (branch, FIX_COMMIT)
    comment = world.github.comments[-1]
    assert comment.startswith("flakipype pushed a revised fix as commit 5eed000 (attempt 2 of 2)")
    assert f"> {TITLE}\n>\n> {EXPLANATION}" in comment
    (pull,) = world.fixes.pulls
    assert (pull.attempt, pull.verification.commit, pull.verification.stage) == (
        2, SECOND_COMMIT, Stage.WAITING,
    )  # fmt: skip
    assert (pull.verification.results, pull.verification.same_error_jobs) == ((), ())
    assert world.fixes.retries_pending() == []
    assert world.fixes.opened == 1
    entry = cache.audit.entries(world.actions.session)[-1]
    assert entry.request.startswith("Push a revised fix to draft pull request #12?")
    assert (entry.status, entry.spent) == (AuditStatus.DONE, 0)


def test_the_last_attempt_is_not_retried(cache: ScanCache) -> None:
    world = FixWorld(cache, fix_settings=FixSettings(verify_runs=1, max_attempts=1))

    (note,) = did_not_hold(world)

    assert "/fix" not in note
    with pytest.raises(ToolError, match=r"holds attempt 1 of 1 \(fix.max_attempts\), so the rest"):
        world.fixes.prepare(target())


def test_a_pull_request_still_being_verified_is_not_retried(cache: ScanCache) -> None:
    world = FixWorld(cache, fix_settings=single_run())
    opened(world)

    with pytest.raises(ToolError, match=r"exists: .+/pull/12; its verification is still running"):
        world.fixes.prepare(target())


def test_a_verification_without_the_findings_error_is_not_retried(cache: ScanCache) -> None:
    world = FixWorld(cache, fix_settings=single_run())
    opened(world)
    world.logs.logs[5] = f"{STAMP}upload failed, retrying\n{SAME_LOG}"
    world.fixes.poll()
    world.actions.poll()
    world.fixes.poll()

    with pytest.raises(ToolError, match="did not show the finding's error again"):
        world.fixes.prepare(target())
    assert world.fixes.retries_pending() == []


def test_the_pull_request_budget_does_not_stop_a_retry(cache: ScanCache) -> None:
    world = FixWorld(cache, fix_settings=FixSettings(verify_runs=1, max_prs_per_session=1))
    did_not_hold(world)

    request = world.fixes.prepare(target()).request

    assert request.title.startswith("Push a revised fix")


def test_a_closed_pull_request_gets_no_commit(cache: ScanCache) -> None:
    world = FixWorld(cache, fix_settings=single_run())
    did_not_hold(world)
    prepared = world.fixes.prepare(target())
    world.github.open = []

    with pytest.raises(ToolError, match="Pull request #12 is no longer open; nothing was pushed"):
        prepared.run(Answer.CONFIRMED)

    assert len(world.github.commits) == 1
    entry = cache.audit.entries(world.actions.session)[-1]
    assert entry.status is AuditStatus.REFUSED


def test_a_branch_someone_else_pushed_to_gets_no_commit(cache: ScanCache) -> None:
    world = FixWorld(cache, fix_settings=single_run())
    did_not_hold(world)
    prepared = world.fixes.prepare(target())
    world.github.errors["commit_files"] = GitHubApiError("Expected branch to point to c0ffee1", 422)

    with pytest.raises(
        FixDeliveryError, match="Nothing was pushed to flakipype/fix-e2e-"
    ) as raised:
        prepared.run(Answer.CONFIRMED)

    assert "only while the branch still ends at its own commit c0ffee1" in str(raised.value)
    assert world.fixes.pulls[0].attempt == 1


def test_a_comment_that_cannot_be_posted_is_reported_after_the_push(cache: ScanCache) -> None:
    world = FixWorld(cache, fix_settings=single_run())
    did_not_hold(world)
    prepared = world.fixes.prepare(target())
    world.github.errors["comment"] = SERVER_ERROR

    outcome = prepared.run(Answer.CONFIRMED)

    assert outcome.endswith(
        "\n(The comment could not be posted on the pull request: Server Error (HTTP 500))"
    )
    assert world.fixes.pulls[0].attempt == 2


def test_a_declined_retry_is_kept_across_a_resume(cache: ScanCache) -> None:
    world = FixWorld(cache, fix_settings=single_run(), fixer=FakeFixer([fixed(), fixed((PROSE,))]))
    did_not_hold(world)
    world.fixes.prepare(target()).declined(Answer.DECLINED)

    resumed = FixWorld(cache, fix_settings=single_run())
    resumed.github.open = world.github.open
    resumed.fixes.restore(world.fixes.state())
    request = resumed.fixes.prepare(target()).request

    assert resumed.fixes.state() == world.fixes.state()
    assert request.title == "Push a revised fix to draft pull request #12?"
    assert resumed.fixer.requests == []
    assert "+Wait for the rows." in request.diff


def test_wishes_for_a_retry_start_from_the_revised_fix(cache: ScanCache) -> None:
    world = FixWorld(cache, fix_settings=single_run(), fixer=FakeFixer([fixed(), fixed((PROSE,))]))
    did_not_hold(world)
    world.fixes.prepare(target())

    world.fixes.prepare(target(), "Keep the comment.")

    later = world.fixer.requests[-1]
    assert (later.earlier, later.commit, later.instructions) == (
        (PROSE,), FIX_COMMIT, "Keep the comment.",
    )  # fmt: skip
    assert later.failed_verification is not None


def test_wishes_for_a_retry_never_start_from_a_fix_for_the_default_branch(
    cache: ScanCache,
) -> None:
    kept = FixWorld(cache)
    kept.fixes.prepare(target())
    world = FixWorld(cache, fix_settings=single_run())
    did_not_hold(world)
    state = world.fixes.state()
    world.fixes.restore({**state, "proposals": kept.fixes.state()["proposals"]})

    world.fixes.prepare(target(), "Keep the comment.")

    later = world.fixer.requests[-1]
    assert (later.earlier, later.commit) == ((), FIX_COMMIT)
    assert later.failed_verification is not None


def test_a_retry_pushed_after_the_session_started_over_is_still_followed(
    cache: ScanCache,
) -> None:
    world = FixWorld(cache, fix_settings=single_run())
    did_not_hold(world)
    prepared = world.fixes.prepare(target())
    world.fixes.reset()

    prepared.run(Answer.CONFIRMED)

    (pull,) = world.fixes.pulls
    assert (pull.attempt, pull.verification.commit) == (2, SECOND_COMMIT)


def test_only_a_retry_proposal_is_delivered_as_one(cache: ScanCache) -> None:
    world = FixWorld(cache)
    world.fixes.prepare(target())
    proposal = world.fixes.kept(e2e_finding())

    with pytest.raises(DeliveryError, match="the proposal is not a retry"):
        world.delivery.deliver_retry(proposal, max_attempts=2)
