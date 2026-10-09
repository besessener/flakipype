from flakipype.flaky.detection import Signal, attempts_to_inspect, find_flaky_failures
from flakipype.flaky.model import AttemptRef

from support.builders import job, run


def test_failed_attempts_of_a_run_that_passed_on_rerun() -> None:
    runs = [run(1, conclusion="success", attempt=3)]

    assert attempts_to_inspect(runs) == {
        AttemptRef(1, 1): Signal.RERUN_PASSED,
        AttemptRef(1, 2): Signal.RERUN_PASSED,
    }


def test_rerun_that_still_fails_is_not_flaky() -> None:
    assert attempts_to_inspect([run(1, conclusion="failure", attempt=2)]) == {}


def test_failed_run_on_a_commit_that_also_passed() -> None:
    runs = [
        run(1, conclusion="failure", sha="b" * 40),
        run(2, conclusion="success", sha="b" * 40),
        run(3, conclusion="failure", sha="c" * 40),
    ]

    assert attempts_to_inspect(runs) == {AttemptRef(1, 1): Signal.SAME_COMMIT}


def test_same_commit_needs_the_same_workflow_and_repository() -> None:
    runs = [
        run(1, conclusion="failure"),
        run(2, conclusion="success", workflow=".github/workflows/lint.yml"),
        run(3, conclusion="success", repository="octo-org/other"),
    ]

    assert attempts_to_inspect(runs) == {}


def test_rerun_signal_wins_over_same_commit() -> None:
    runs = [run(1, conclusion="success", attempt=2), run(2, conclusion="timed_out")]

    inspect = attempts_to_inspect(runs)

    assert inspect[AttemptRef(1, 1)] is Signal.RERUN_PASSED
    assert inspect[AttemptRef(2, 1)] is Signal.SAME_COMMIT


def test_generated_workflows_are_ignored() -> None:
    runs = [run(1, attempt=2, workflow="dynamic/dependabot/dependabot-updates")]

    assert attempts_to_inspect(runs) == {}


def test_cancelled_and_running_runs_are_ignored() -> None:
    runs = [run(1, conclusion="cancelled"), run(2, conclusion=None), run(3)]

    assert attempts_to_inspect(runs) == {}


def test_flaky_failures_are_the_failed_jobs_of_inspected_attempts() -> None:
    runs = [run(1, conclusion="success", attempt=2)]
    jobs = {
        AttemptRef(1, 1): [
            job(10, run_id=1, conclusion="failure", name="test"),
            job(11, run_id=1, conclusion="success", name="lint"),
            job(12, run_id=1, attempt=2, conclusion="failure", name="reused from other attempt"),
        ],
        AttemptRef(1, 2): [job(13, run_id=1, attempt=2, conclusion="success")],
    }

    failures = find_flaky_failures(runs, jobs)

    assert [(f.job.job_id, f.signal) for f in failures] == [(10, Signal.RERUN_PASSED)]
    assert failures[0].run.run_id == 1


def test_missing_jobs_give_no_failures() -> None:
    assert find_flaky_failures([run(1, attempt=2)], {}) == []
