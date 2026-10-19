from flakipype.agent.workcopy import FileChange
from flakipype.config.settings import FixSettings
from flakipype.flaky.model import WorkflowRun
from flakipype.github.runs import CommitRun
from flakipype.store.database import ScanCache
from flakipype.unattended.limits import RunLimits
from flakipype.unattended.service import FixOutcomeKind, RunReport

from support.builders import job, run
from support.fake_fix import CHANGE, FIX_COMMIT, PROSE, FakeFixer, fixed
from support.fake_investigation import APP, LOG
from support.fake_run import RunWorld, limits
from support.fake_runs import passed_job, state

CI = ".github/workflows/ci.yml"
SECOND_COMMIT = "5eed000" + "0" * 33
REVISED = FileChange("docs/testing.md", "Wait 500 ms for the rows.\n", "Wait for all rows.\n")


def retrying_world(
    cache: ScanCache, *, revised: FileChange = REVISED, run_limits: RunLimits | None = None
) -> RunWorld:
    """Finding 1's fix fails on its branch with the finding's error; the revised fix passes."""
    world = RunWorld(
        cache, fixer=FakeFixer([fixed((PROSE,)), fixed((revised,))]),
        fix_settings=FixSettings(verify_runs=1), limits=run_limits or limits(),
    )  # fmt: skip
    github = world.github
    github.files[CI] = b"on: pull_request\njobs: {}\n"
    github.keep_opened = True
    github.commit_shas = [FIX_COMMIT, SECOND_COMMIT]
    github.runs_by_commit[FIX_COMMIT] = [CommitRun(91, "pull_request")]
    github.runs_by_commit[SECOND_COMMIT] = [CommitRun(92, "pull_request")]
    world.runs.states[91] = [state(91, name="CI")]
    world.runs.states[92] = [state(92, name="CI", conclusion="success")]
    world.source.jobs_by_attempt[91, 1] = [job(911, run_id=91)]
    world.source.jobs_by_attempt[92, 1] = [passed_job(92, name="test")]
    world.source.logs[911] = LOG
    return world


def listed_runs(world: RunWorld) -> list[WorkflowRun]:
    runs = world.source.runs_by_repository[APP]
    assert isinstance(runs, list)
    return runs


def finding_one(report: RunReport) -> list[tuple[FixOutcomeKind, str]]:
    return [(fix.kind, fix.text) for fix in report.fixes if fix.finding == 1]


def test_a_fix_that_did_not_hold_is_revised_and_verified_again(cache: ScanCache) -> None:
    world = retrying_world(cache)

    report = world.service().run()

    (first, retried) = finding_one(report)
    assert first[1].startswith("Opened draft pull request #12")
    assert retried == (
        FixOutcomeKind.OPENED,
        (
            "Pushed a revised fix to draft pull request #12: "
            "https://github.com/octo-org/app/pull/12 (attempt 2 of 2, commit 5eed000)."
        ),
    )
    assert world.fixer.requests[1].failed_verification is not None
    assert world.fixer.requests[1].failed_verification.jobs == (911,)
    assert [commit.branch for commit in world.github.commits] == [world.github.drafts[0].head] * 2
    (pull,) = report.pulls
    assert (pull.attempt, pull.verified) == (2, True)
    assert pull.verification.outcome.startswith("flakipype verification: CI passed 1 of 1 runs")
    assert (report.pull_requests, report.complete) == (1, True)


def test_a_revised_fix_of_code_is_kept_for_a_person(cache: ScanCache) -> None:
    world = retrying_world(cache, revised=CHANGE)

    report = world.service().run()

    (_, (kind, text)) = finding_one(report)
    assert kind is FixOutcomeKind.KEPT
    assert text.startswith("not pushed: it changes files that can run as code")
    assert len(world.github.commits) == 1
    assert report.pulls[0].attempt == 1


def test_the_token_limit_leaves_a_fix_that_did_not_hold(cache: ScanCache) -> None:
    world = retrying_world(cache, run_limits=limits(tokens=3_000))

    report = world.service().run()

    assert len(world.fixer.requests) == 1
    assert report.stops == ("the token limit (3,000 for this run); fixes that did not hold wait",)


def taken_over(cache: ScanCache) -> RunWorld:
    """The last run left pull request #12 unverified; this run finds the finding's error."""
    first = retrying_world(cache, run_limits=limits(minutes=10))
    first.runs.states[91] = [state(91, name="CI", status="in_progress", conclusion=None)]
    first.service().run()
    later = retrying_world(cache)
    later.github.open = list(first.github.open)
    later.github.commit_shas = [SECOND_COMMIT]
    later.fixer.results = [fixed((REVISED,))]
    return later


def test_a_pull_request_taken_over_from_the_last_run_is_retried(cache: ScanCache) -> None:
    later = taken_over(cache)

    report = later.service().run()

    (still_running, retried) = finding_one(report)
    assert still_running[1].endswith("; its verification is still running.")
    assert retried[1].startswith("Pushed a revised fix to draft pull request #12")
    assert later.fixer.requests[0].failed_verification is not None
    assert report.pulls[0].attempt == 2


def test_a_finding_no_longer_fixable_is_not_retried(cache: ScanCache) -> None:
    later = taken_over(cache)
    # A newer flake of the CI test makes the run investigate it again; now it is a real bug.
    later.source.runs_by_repository[APP] = [
        *listed_runs(later),
        run(7, attempt=2),
    ]
    later.source.jobs_by_attempt[7, 1] = [job(71, run_id=7)]
    later.source.logs[71] = LOG
    later.agent.flaky = frozenset()

    report = later.service().run()

    (_, (kind, text)) = finding_one(report)
    assert kind is FixOutcomeKind.SKIPPED
    assert text == (
        "its fix did not hold; not tried again: not fixed: real bug, which flakipype does not fix"
    )
    assert later.fixer.requests == []


def test_a_finding_missing_from_the_scan_is_not_retried(cache: ScanCache) -> None:
    later = taken_over(cache)
    later.source.runs_by_repository[APP] = [
        listed for listed in listed_runs(later) if listed.run_id in {5, 6}
    ]

    later.service().run()

    assert later.fixer.requests == []
    stored = cache.sessions.latest_run(before=10**6)
    assert stored is not None
    assert (
        "Pull request #12: its fix did not hold, but its finding is not among this run's "
        "verdicts, so it was not tried again"
    ) in stored
