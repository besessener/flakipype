from dataclasses import replace

import pytest

from flakipype.agent.tools import Answer, ToolError
from flakipype.agent.workcopy import FileChange
from flakipype.config.settings import FixSettings
from flakipype.fix.service import FixTarget
from flakipype.fix.texts import finding_marker
from flakipype.fix.verify import Stage
from flakipype.flaky.findings import Finding
from flakipype.flaky.signature import Category, ErrorSignature
from flakipype.github.actions import ApiRateLimitError, GitHubApiError
from flakipype.github.pulls import PullRequest
from flakipype.github.runs import CommitRun
from flakipype.store.database import ScanCache

from support.fake_fix import (
    CHANGE,
    COMMIT,
    FIX_COMMIT,
    TITLE,
    FakeFixer,
    FixWorld,
    fixed,
    no_fix,
    verdict,
)
from support.fake_runs import E2E, e2e_evidence, e2e_finding, state

FORBIDDEN = GitHubApiError("Resource not accessible by integration (HTTP 403)", 403)
SERVER_ERROR = GitHubApiError("Server Error (HTTP 500)", 500)
WORKFLOW_CHANGE = FileChange(E2E, "on: push\njobs: {}\n", "on:\n  push:\njobs: {}\n")


def target(
    finding: Finding | None = None, *, classification: str = "flaky_test", review: str = "accepted"
) -> FixTarget:
    signature = ErrorSignature(Category.TIMEOUT, "wait timed out", "f" * 12, "excerpt")
    evidence = replace(e2e_evidence(), signatures={41: signature})
    return FixTarget(finding or e2e_finding(), evidence, verdict(classification), review)


@pytest.mark.parametrize(
    ("fix_target", "problem"),
    [
        (target(classification="real_bug"), "#2 is real bug: flakipype fixes only flaky tests"),
        (target(review="not reviewed: HTTP 500"), r"not reviewed \(not reviewed: HTTP 500\)"),
        (target(review=""), r"not reviewed \(no review\); investigate it again with /investigate"),
        (target(e2e_finding(repository="other/app")), "does not belong to the configured owner"),
    ],
)  # fmt: skip
def test_findings_that_are_not_fixed(cache: ScanCache, fix_target: FixTarget, problem: str) -> None:
    world = FixWorld(cache)

    with pytest.raises(ToolError, match=problem):
        world.fixes.prepare(fix_target)
    assert world.github.calls == []
    assert world.fixer.requests == []


def test_the_pull_request_budget_is_checked_first(cache: ScanCache) -> None:
    world = FixWorld(cache, fix_settings=FixSettings(max_prs_per_session=1))
    world.fixes.opened = 1

    with pytest.raises(ToolError, match="Pull request budget used up: 1 of 1 in this session"):
        world.fixes.prepare(target())
    assert world.fixer.requests == []


def test_no_fix_without_push_access(cache: ScanCache) -> None:
    world = FixWorld(cache)
    world.github.can_push = False

    with pytest.raises(ToolError, match=r"You cannot push to octo-org/app.+not through forks"):
        world.fixes.prepare(target())
    assert world.fixer.requests == []


def test_github_errors_before_the_fixer_say_what_is_missing(cache: ScanCache) -> None:
    world = FixWorld(cache)
    world.github.errors["access"] = FORBIDDEN

    with pytest.raises(ToolError, match="'Workflows: read and write' for a fine-grained token"):
        world.fixes.prepare(target())


def test_an_open_flakipype_pull_request_is_linked_instead(cache: ScanCache) -> None:
    world = FixWorld(cache)
    marker = finding_marker(e2e_finding())
    world.github.open = [
        PullRequest(3, "https://github.com/octo-org/app/pull/3", "feature/x", marker),
        PullRequest(4, "https://github.com/octo-org/app/pull/4", "flakipype/fix-ci-1", "other"),
        PullRequest(5, "https://github.com/octo-org/app/pull/5", "flakipype/fix-e2e-1", marker),
    ]

    with pytest.raises(ToolError, match=r"An open flakipype pull request for #2 exists: .+/pull/5"):
        world.fixes.prepare(target())
    assert world.fixer.requests == []


def test_the_confirmation_shows_facts_the_model_text_and_the_diff(cache: ScanCache) -> None:
    world = FixWorld(cache)

    prepared = world.fixes.prepare(target())

    request = prepared.request
    branch = world.fixes.state()["proposals"][0]["verification"]["branch"]
    assert request.title == "Push fix and open a draft pull request?"
    assert request.details == (
        "octo-org/app · base main @ 3f2a9c1",
        f"new branch {branch}",
        "1 files · +1 −1 · tests/e2e/scan.spec.ts",
        "then reruns E2E on the fix branch 3 times",
        "Pull requests this session: 1 of 3 · Actions: 0 of 10",
        "Opens a draft pull request; merging stays with you.",
        "Warnings: none",
    )
    assert request.model_text == f"{TITLE}\n\nThe test counts rows before the import finished."
    assert "+await rows.waitFor()" in request.diff
    assert request.needs_person == ""
    assert (request.confirm_label, request.decline_label) == ("Push", "Don't push")
    (fix_request,) = world.fixer.requests
    assert (fix_request.commit, fix_request.default_branch) == (COMMIT, "main")
    assert fix_request.check([]) == ["The diff is empty: edit the working copy before submitting."]
    assert world.fixes.tokens == 1_000


def test_warnings_need_a_person(cache: ScanCache) -> None:
    changes = (CHANGE, WORKFLOW_CHANGE, FileChange("a.txt", None, "a\n"),
               FileChange("b.txt", None, "b\n"))  # fmt: skip
    world = FixWorld(cache, fixer=FakeFixer([fixed(changes)]))

    request = world.fixes.prepare(target()).request

    assert request.details[2] == (
        "4 files · +5 −2 · tests/e2e/scan.spec.ts, .github/workflows/e2e.yml, a.txt …"
    )
    assert request.details[-2:] == ("Warnings:", f"⚠ changes .github/: {E2E}")
    assert request.needs_person == "the diff has warnings"


def test_a_proposal_is_shown_again_until_it_is_discarded(cache: ScanCache) -> None:
    world = FixWorld(cache)

    first = world.fixes.prepare(target())
    second = world.fixes.prepare(target())
    world.fixes.discard(e2e_finding())
    world.fixes.prepare(target())

    assert first.request == second.request
    assert len(world.fixer.requests) == 2


def test_instructions_start_from_the_earlier_proposal(cache: ScanCache) -> None:
    world = FixWorld(cache)
    world.fixes.prepare(target())
    world.github.calls.clear()

    world.fixes.prepare(target(), "Keep the assertion.")

    later = world.fixer.requests[-1]
    assert (later.earlier, later.instructions, later.commit) == (
        (CHANGE,), "Keep the assertion.", COMMIT,
    )  # fmt: skip
    assert not [call for call in world.github.calls if call.startswith("branch_head")]


def test_no_fix_says_why(cache: ScanCache) -> None:
    world = FixWorld(cache, fixer=FakeFixer([no_fix("The fixer stopped.")]))

    with pytest.raises(ToolError, match=r"No fix for #2: The fixer stopped\."):
        world.fixes.prepare(target())
    assert world.fixes.tokens == 5


def test_a_rejected_fix_shows_the_review_and_the_diff(cache: ScanCache) -> None:
    rejected = fixed(accepted=False, review="rejected: it only waits longer")
    world = FixWorld(cache, fixer=FakeFixer([rejected]))

    with pytest.raises(ToolError) as raised:
        world.fixes.prepare(target())

    message = str(raised.value)
    assert message.startswith("No pull request for #2: the review rejected: it only waits longer.")
    assert "+await rows.waitFor()" in message


def test_a_confirmed_fix_is_delivered_and_audited(cache: ScanCache) -> None:
    world = FixWorld(cache)
    world.github.files[E2E] = b"on: pull_request\njobs: {}\n"
    prepared = world.fixes.prepare(target())

    outcome = prepared.run(Answer.CONFIRMED)

    (pull,) = world.fixes.pulls
    assert outcome == (
        f"Opened draft pull request #12: {pull.url} (branch {pull.branch}).\n"
        "Verification: 3 runs of E2E on the branch; the result follows here and on the "
        "pull request."
    )
    assert world.fixes.opened == 1
    assert world.fixes.state()["proposals"] == []
    (entry,) = cache.audit.entries(world.actions.session)
    assert (entry.action, entry.origin, entry.answer, entry.outcome) == (
        "fix", "model", "confirmed", outcome,
    )  # fmt: skip
    assert entry.request.startswith("Push fix and open a draft pull request?\nocto-org/app")


def test_a_fix_whose_verification_ends_at_once_says_so(cache: ScanCache) -> None:
    world = FixWorld(cache)

    outcome = world.fixes.prepare(target()).run(Answer.AUTO)

    assert outcome.endswith("cannot verify automatically: the workflow runs neither on push, "
                            "pull_request nor workflow_dispatch.")  # fmt: skip
    (entry,) = cache.audit.entries(world.actions.session)
    assert entry.answer == "auto"


def test_a_declined_fix_is_kept_and_audited(cache: ScanCache) -> None:
    world = FixWorld(cache)

    with world.actions.commanded():
        world.fixes.prepare(target()).declined(Answer.DECLINED)

    assert world.github.drafts == []
    assert len(world.fixes.state()["proposals"]) == 1
    (entry,) = cache.audit.entries(world.actions.session)
    assert (entry.origin, entry.answer, entry.outcome) == ("command", "declined", "not pushed")


def test_a_failed_delivery_is_reported_and_audited(cache: ScanCache) -> None:
    world = FixWorld(cache)
    world.github.errors["commit_files"] = SERVER_ERROR
    prepared = world.fixes.prepare(target())

    with pytest.raises(ToolError, match="created; the commit failed: GitHub: Server Error"):
        prepared.run(Answer.CONFIRMED)

    assert world.fixes.opened == 0
    (entry,) = cache.audit.entries(world.actions.session)
    assert entry.outcome.startswith("failed: Branch flakipype/fix-e2e-")


def opened_fix(world: FixWorld) -> None:
    world.github.files[E2E] = b"on: pull_request\njobs: {}\n"
    world.fixes.prepare(target()).run(Answer.CONFIRMED)


def test_poll_moves_verifications_and_notes_finished_ones(cache: ScanCache) -> None:
    world = FixWorld(cache, fix_settings=FixSettings(verify_runs=1))
    opened_fix(world)
    world.github.runs_by_commit[FIX_COMMIT] = [CommitRun(91, "pull_request")]
    world.runs.states[91] = [state(91, conclusion="success")]

    assert world.fixes.poll() == []
    world.actions.poll()
    (note,) = world.fixes.poll()

    assert note.startswith("Pull request #12: flakipype verification: E2E passed 1 of 1 runs")
    assert world.fixes.pulls[0].verification.stage is Stage.DONE
    assert world.fixes.poll() == []


def test_poll_waits_for_the_rate_limit_and_skips_errors(cache: ScanCache) -> None:
    world = FixWorld(cache)
    opened_fix(world)
    opened_fix(world)
    before = list(world.fixes.pulls)

    world.github.errors["commit_runs"] = ApiRateLimitError("rate limit", 403)
    assert world.fixes.poll() == []
    world.github.errors["commit_runs"] = SERVER_ERROR
    assert world.fixes.poll() == []

    assert world.fixes.pulls == before
    assert (
        world.github.calls.count("commit_runs octo-org/app .github/workflows/e2e.yml c0ffee1") == 3
    )


def test_the_session_state_survives_a_resume(cache: ScanCache) -> None:
    world = FixWorld(cache)
    opened_fix(world)
    world.fixes.discard(e2e_finding())
    world.fixes.prepare(target(e2e_finding(number=3)))

    resumed = FixWorld(cache)
    resumed.fixes.restore(world.fixes.state())

    assert resumed.fixes.state() == world.fixes.state()
    assert resumed.fixes.opened == 1
    assert resumed.fixes.prepare(target()).request.title.startswith("Push fix")
    assert len(resumed.fixer.requests) == 0
    resumed.fixes.reset()
    assert resumed.fixes.state() == {"opened": 0, "proposals": [], "pulls": []}
