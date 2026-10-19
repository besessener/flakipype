from dataclasses import replace

import pytest

from flakipype.config.settings import ActionSettings
from flakipype.fix.verify import Stage, Verification
from flakipype.flaky.model import JobResult
from flakipype.flaky.signature import signature_from_log
from flakipype.github.actions import ApiRateLimitError, GitHubApiError
from flakipype.github.runs import CommitRun
from flakipype.store.database import ScanCache

from support.builders import job
from support.fake_fix import FIX_COMMIT, FixWorld, verification
from support.fake_runs import DISPATCHABLE, FakeRuns, passed_job, state

STAMP = "2026-10-07T09:27:35.3592891Z "
SAME_LOG = f"{STAMP}##[error]Process completed with exit code 1.\n"
OTHER_LOG = f"{STAMP}upload failed, retrying\n{SAME_LOG}"
SERVER_ERROR = GitHubApiError("Server Error (HTTP 500)", 500)
CANNOT = "flakipype verification: cannot verify automatically: "


def same_fingerprint() -> str:
    signature = signature_from_log(SAME_LOG)
    assert signature is not None
    return signature.fingerprint


class Setup(FixWorld):
    def watching(self, current: Verification, run_id: int = 91) -> Verification:
        """Begins on a pull request's run and finds it."""
        self.github.runs_by_commit[FIX_COMMIT] = [
            CommitRun(90, "schedule"),
            CommitRun(run_id, "pull_request"),
        ]
        waiting = self.verifier.begin(current, "on: pull_request\njobs: {}\n")
        found = self.verifier.poll(waiting)
        assert found.stage is Stage.WATCHING
        return found


def test_a_pull_request_run_is_waited_for(cache: ScanCache) -> None:
    setup = Setup(cache)

    begun = setup.verifier.begin(verification(), "on:\n  push:\njobs: {}\n")

    assert begun == verification()
    assert setup.github.calls == []


def test_a_filtered_push_workflow_is_dispatched_when_no_run_starts(cache: ScanCache) -> None:
    setup = Setup(cache, runs=FakeRuns(dispatch_ids=[80]))
    workflow = "on:\n  push:\n    branches: [main]\n  workflow_dispatch:\njobs: {}\n"
    waiting = setup.verifier.begin(verification(), workflow)

    setup.clock.advance(minutes=10, seconds=1)
    dispatched = setup.verifier.poll(waiting)

    assert dispatched.stage is Stage.WATCHING
    assert f"dispatch octo-org/app .github/workflows/e2e.yml {verification().branch}" in (
        setup.runs.calls
    )
    assert setup.actions.watched[0].run_id == 80
    assert setup.github.comments == []


def test_the_run_on_the_fix_commit_is_found_and_watched(cache: ScanCache) -> None:
    setup = Setup(cache)

    found = setup.watching(verification())

    (watched,) = setup.actions.watched
    assert found.watched == (watched.number,)
    assert (watched.run_id, watched.ref, watched.label) == (91, verification().branch, "verify 1/3")
    assert setup.actions.used == 0


def test_no_run_within_ten_minutes_cannot_be_verified(cache: ScanCache) -> None:
    setup = Setup(cache)
    waiting = setup.verifier.begin(verification(), "on: push\njobs: {}\n")

    setup.clock.advance(minutes=10)
    assert setup.verifier.poll(waiting) == waiting
    setup.clock.advance(seconds=1)
    done = setup.verifier.poll(waiting)

    assert done.stage is Stage.DONE
    assert done.outcome == (
        f"{CANNOT}no run of the workflow started on the fix branch in 10 minutes."
    )
    assert setup.github.comments == [done.outcome]


def test_a_lookup_that_keeps_failing_ends_the_wait_after_ten_minutes(cache: ScanCache) -> None:
    setup = Setup(cache)
    waiting = setup.verifier.begin(verification(), "on: push\njobs: {}\n")
    setup.github.errors["commit_runs"] = GitHubApiError("Not Found (HTTP 404)", 404)

    still = setup.verifier.poll(waiting)
    setup.clock.advance(minutes=10, seconds=1)
    done = setup.verifier.poll(still)

    assert still == replace(waiting, detail="GitHub did not answer: Not Found (HTTP 404)")
    assert done.stage is Stage.DONE
    assert done.outcome.startswith(f"{CANNOT}GitHub did not answer: Not Found (HTTP 404).")
    assert done.detail == ""
    setup.github.errors["commit_runs"] = ApiRateLimitError("API rate limit exceeded", 403)
    with pytest.raises(ApiRateLimitError):
        setup.verifier.poll(waiting)


def test_a_dispatch_only_workflow_is_dispatched_on_the_fix_branch(cache: ScanCache) -> None:
    setup = Setup(cache, runs=FakeRuns(dispatch_ids=[80]))

    begun = setup.verifier.begin(verification(), "on: workflow_dispatch\njobs: {}\n")

    assert begun.stage is Stage.WATCHING
    assert f"dispatch octo-org/app .github/workflows/e2e.yml {verification().branch}" in (
        setup.runs.calls
    )
    assert setup.actions.used == 1
    assert setup.actions.watched[0].run_id == 80


@pytest.mark.parametrize(
    ("workflow", "reason"),
    [
        ("on: schedule\njobs: {}\n", "the workflow does not declare workflow_dispatch"),
        ("on:\n  workflow_dispatch:\n    inputs:\n      environment: {required: true}\n",
         "the workflow needs inputs flakipype does not send: environment"),
    ],
)  # fmt: skip
def test_a_workflow_that_nothing_starts_cannot_be_verified(
    cache: ScanCache, workflow: str, reason: str
) -> None:
    setup = Setup(cache)

    begun = setup.verifier.begin(verification(), workflow)

    assert begun.outcome == (
        f"{CANNOT}the workflow runs on neither push nor pull_request, and {reason}."
    )


def test_a_refused_dispatch_ends_the_verification_once(cache: ScanCache) -> None:
    forbidden = GitHubApiError("Resource not accessible by integration (HTTP 403)", 403)
    setup = Setup(cache, runs=FakeRuns(dispatch_ids=[forbidden, 81]))
    workflow = "on:\n  push:\n    branches: [main]\n  workflow_dispatch:\njobs: {}\n"
    current = setup.verifier.begin(verification(), workflow)

    setup.clock.advance(minutes=10, seconds=1)
    for _ in range(3):
        current = setup.verifier.poll(current)

    assert current.stage is Stage.DONE
    assert current.outcome == (
        f"{CANNOT}GitHub refused the dispatch: Resource not accessible by integration (HTTP 403)."
    )
    assert len([call for call in setup.runs.calls if call.startswith("dispatch")]) == 1
    assert setup.github.comments == [current.outcome]


def test_a_rate_limited_dispatch_keeps_the_verification_waiting(cache: ScanCache) -> None:
    limited = ApiRateLimitError("API rate limit exceeded", 403)
    setup = Setup(cache, runs=FakeRuns(dispatch_ids=[limited]))
    waiting = setup.verifier.begin(verification(), DISPATCHABLE)

    setup.clock.advance(minutes=10, seconds=1)
    with pytest.raises(ApiRateLimitError):
        setup.verifier.poll(waiting)

    assert setup.github.comments == []


def test_no_dispatch_when_the_budget_is_used_up(cache: ScanCache) -> None:
    setup = Setup(cache, settings=ActionSettings(max_per_session=1))
    setup.actions.used = 1

    begun = setup.verifier.begin(verification(), DISPATCHABLE.replace("  push:\n", ""))

    assert begun.outcome == f"{CANNOT}the action budget of this session is used up."
    assert not [call for call in setup.runs.calls if call.startswith("dispatch")]


def test_three_passes_are_rerun_and_reported(cache: ScanCache) -> None:
    runs = FakeRuns(
        states={91: [state(91, conclusion="success", attempt=attempt) for attempt in (1, 2, 3)]}
    )
    setup = Setup(cache, runs=runs)
    for attempt in (1, 2, 3):
        setup.logs.jobs_by_attempt[91, attempt] = [passed_job(91, attempt=attempt)]
    current = setup.watching(verification())

    for _ in range(2):
        current = setup.step(current)
        assert current.stage is Stage.WATCHING
    current = setup.step(current)

    assert current.results == ("passed", "passed", "passed")
    assert current.stage is Stage.DONE
    assert current.outcome.startswith("flakipype verification: E2E passed 3 of 3 runs")
    assert "Three passes in a row would also happen by chance 66%" in current.outcome
    assert [run.label for run in setup.actions.watched] == [
        "verify 1/3",
        "verify 2/3",
        "verify 3/3",
    ]
    assert setup.runs.calls.count("rerun octo-org/app 91") == 2
    assert setup.actions.used == 2
    assert setup.github.comments == [current.outcome]


def test_an_unfinished_or_unknown_run_waits(cache: ScanCache) -> None:
    runs = FakeRuns(states={91: [state(91, status="in_progress", conclusion=None)]})
    setup = Setup(cache, runs=runs)
    current = setup.watching(verification())

    assert setup.step(current) == current
    unknown = replace(current, watched=(9,))
    assert setup.verifier.poll(unknown) == unknown


def test_a_finished_verification_stays_finished(cache: ScanCache) -> None:
    setup = Setup(cache)
    done = setup.verifier.begin(verification(), "on: schedule\njobs: {}\n")

    assert setup.verifier.poll(done) == done


def failing(setup: Setup, jobs: list[JobResult] | Exception) -> None:
    setup.runs.states[91] = [state(91)]
    setup.logs.jobs_by_attempt[91, 1] = jobs


@pytest.mark.parametrize(
    ("jobs", "log", "result"),
    [
        ([job(5, run_id=91, name="e2e")], SAME_LOG,
         "failed with the same error as before: the fix did not hold"),
        ([job(5, run_id=91, name="e2e")], OTHER_LOG,
         "failed with another error: upload failed, retrying"),
        ([job(5, run_id=91, name="lint"), job(6, run_id=91, name="e2e", conclusion="success")],
         None, "failed in lint, not in e2e"),
        ([], None, "failed in another job, not in e2e"),
        ([job(5, run_id=91, name="e2e")], None, "failed (its log could not be read)"),
        ([job(5, run_id=91, name="e2e")], f"{STAMP}fine\n", "failed (its log could not be read)"),
        (SERVER_ERROR, None, "failed (its log could not be read)"),
    ],
)  # fmt: skip
def test_failures_are_classified(
    cache: ScanCache, jobs: list[JobResult] | Exception, log: str | None, result: str
) -> None:
    setup = Setup(cache)
    failing(setup, jobs)
    setup.logs.logs[5] = log
    current = setup.watching(verification(wanted=1, fingerprints=(same_fingerprint(),)))

    done = setup.step(current)

    assert done.results == (result,)
    assert f"Run 1 {result}." in done.outcome
    assert "by chance" not in done.outcome


@pytest.mark.parametrize(("log", "jobs"), [(SAME_LOG, (5,)), (OTHER_LOG, ())])
def test_only_the_findings_error_marks_the_job_for_a_retry(
    cache: ScanCache, log: str, jobs: tuple[int, ...]
) -> None:
    setup = Setup(cache)
    failing(setup, [job(5, run_id=91, name="e2e")])
    setup.logs.logs[5] = log
    current = setup.watching(verification(wanted=1, fingerprints=(same_fingerprint(),)))

    done = setup.step(current)

    assert done.same_error_jobs == jobs
    assert Verification.from_dict(done.to_dict()) == done


def test_a_restarted_verification_follows_the_new_commit_from_the_start(cache: ScanCache) -> None:
    setup = Setup(cache)
    failing(setup, [job(5, run_id=91, name="e2e")])
    setup.logs.logs[5] = SAME_LOG
    done = setup.step(setup.watching(verification(wanted=1, fingerprints=(same_fingerprint(),))))

    restarted = done.restarted("5eed" + "0" * 36, setup.clock.now)

    assert restarted == replace(verification(wanted=1, fingerprints=(same_fingerprint(),)),
                                commit="5eed" + "0" * 36)  # fmt: skip


def test_a_success_without_the_findings_job_is_no_pass(cache: ScanCache) -> None:
    setup = Setup(cache, runs=FakeRuns(states={91: [state(91, conclusion="success")]}))
    setup.logs.jobs_by_attempt[91, 1] = [
        passed_job(91, name="lint"),
        job(7, run_id=91, name="e2e", conclusion="skipped"),
    ]
    current = setup.watching(verification())

    done = setup.step(current)

    assert done.results == ("passed, but e2e did not run",)
    assert "passed 0 of 1 runs" in done.outcome
    assert (
        "Stopped after 1 of 3 runs: a rerun replays the same event, so e2e would not run either."
    ) in done.outcome
    assert "by chance" not in done.outcome
    assert "rerun octo-org/app 91" not in setup.runs.calls


def test_a_success_whose_jobs_cannot_be_read_is_no_pass(cache: ScanCache) -> None:
    setup = Setup(cache, runs=FakeRuns(states={91: [state(91, conclusion="success")]}))
    setup.logs.jobs_by_attempt[91, 1] = SERVER_ERROR
    current = setup.watching(verification(wanted=1))

    done = setup.step(current)

    assert done.results == ("passed, but whether e2e ran could not be read",)
    assert "by chance" not in done.outcome


def test_a_cancelled_run_stops_the_verification(cache: ScanCache) -> None:
    setup = Setup(cache, runs=FakeRuns(states={91: [state(91, conclusion="cancelled")]}))
    current = setup.watching(verification())

    done = setup.step(current)

    assert done.results == ("cancelled",)
    assert "Stopped after 1 of 3 runs: a run ended as cancelled." in done.outcome


def test_a_run_that_does_not_finish_while_watched(cache: ScanCache) -> None:
    runs = FakeRuns(states={91: [state(91, status="in_progress", conclusion=None)]})
    setup = Setup(cache, runs=runs)
    current = setup.watching(verification())

    setup.clock.advance(hours=7)
    done = setup.step(current)

    assert done.outcome == f"{CANNOT}a run did not finish while it was watched."


def test_a_run_github_keeps_refusing_ends_the_verification(cache: ScanCache) -> None:
    setup = Setup(cache, runs=FakeRuns(states={91: [GitHubApiError("Not Found (HTTP 404)", 404)]}))
    current = setup.watching(verification())

    assert setup.step(current) == current
    setup.clock.advance(hours=7)
    done = setup.step(current)

    assert done.outcome == (
        f"{CANNOT}a run did not finish while it was watched; cannot read it: Not Found (HTTP 404)."
    )
    assert setup.github.comments == [done.outcome]


@pytest.mark.parametrize(
    ("used", "error", "stopped"),
    [
        (10, None, "the action budget of this session is used up"),
        (0, SERVER_ERROR, "GitHub refused the rerun: Server Error (HTTP 500)"),
    ],
)
def test_a_rerun_that_cannot_start_stops_the_verification(
    cache: ScanCache, used: int, error: Exception | None, stopped: str
) -> None:
    setup = Setup(cache, runs=FakeRuns(states={91: [state(91, conclusion="success")]}))
    setup.logs.jobs_by_attempt[91, 1] = [passed_job(91)]
    if error is not None:
        setup.runs.errors["rerun"] = error
    current = setup.watching(verification())
    setup.actions.used = used

    done = setup.step(current)

    assert done.results == ("passed",)
    assert f"Stopped after 1 of 3 runs: {stopped}." in done.outcome


def test_a_rate_limited_rerun_pauses_the_verification(cache: ScanCache) -> None:
    setup = Setup(cache, runs=FakeRuns(states={91: [state(91, conclusion="success")]}))
    setup.logs.jobs_by_attempt[91, 1] = [passed_job(91)]
    setup.runs.errors["rerun"] = ApiRateLimitError("API rate limit exceeded", 403)
    current = setup.watching(verification())
    setup.actions.poll()

    with pytest.raises(ApiRateLimitError):
        setup.verifier.poll(current)

    assert setup.github.comments == []


def test_a_comment_that_cannot_be_posted_is_reported(cache: ScanCache) -> None:
    setup = Setup(cache)
    setup.github.errors["comment"] = SERVER_ERROR

    done = setup.verifier.begin(verification(), "on: schedule\njobs: {}\n")

    assert done.outcome.endswith(
        "\n(The comment could not be posted on the pull request: Server Error (HTTP 500))"
    )


def test_a_verification_survives_a_resume(cache: ScanCache) -> None:
    setup = Setup(cache, runs=FakeRuns(states={91: [state(91, conclusion="success")]}))
    current = setup.step(setup.watching(verification(fingerprints=("abc",))))

    assert Verification.from_dict(current.to_dict()) == current


def test_a_verification_stored_before_dispatchable_existed_loads() -> None:
    stored = verification().to_dict()
    del stored["dispatchable"]
    del stored["same_error_jobs"]

    assert Verification.from_dict(stored) == verification()
