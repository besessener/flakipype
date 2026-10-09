from flakipype.flaky.detection import find_flaky_failures
from flakipype.flaky.model import AttemptRef, WorkflowRun
from flakipype.flaky.recurring import (
    find_recurring_errors,
    latest_failed_attempts,
    unproven_failures,
)
from flakipype.flaky.signature import Category, ErrorSignature

from support.builders import job, run

TIMEOUT = ErrorSignature(Category.TIMEOUT, "wait timed out", "aaaaaaaaaaaa", "excerpt")
OTHER_TIMEOUT = ErrorSignature(Category.TIMEOUT, "another wait", "cccccccccccc", "excerpt")
EXIT = ErrorSignature(
    Category.EXIT_CODE, "Process completed with exit code N.", "eeeeeeeeeeee", "e"
)


def branch_run(run_id: int, branch: str, conclusion: str = "failure") -> WorkflowRun:
    built = run(run_id, conclusion=conclusion, sha=f"{run_id:040d}")
    return type(built)(**{**built.__dict__, "head_branch": branch})


def test_latest_attempts_of_failed_tracked_runs() -> None:
    runs = [
        run(1, conclusion="failure", attempt=2),
        run(2),
        run(3, conclusion="failure", workflow="dynamic/dependabot/dependabot-updates"),
    ]

    assert latest_failed_attempts(runs) == [AttemptRef(1, 2)]


def test_unproven_failures_skip_jobs_already_proven_flaky() -> None:
    runs = [run(1, conclusion="failure"), run(2)]
    jobs = {AttemptRef(1, 1): [job(11, run_id=1), job(12, run_id=1, conclusion="success")]}
    proven = find_flaky_failures(runs, jobs)

    assert [f.job.job_id for f in unproven_failures(runs, jobs, [])] == [11]
    assert unproven_failures(runs, jobs, proven) == []


def test_same_error_across_branches_recurs() -> None:
    runs = [branch_run(1, "main"), branch_run(2, "feature/a"), branch_run(3, "main")]
    jobs = {AttemptRef(r.run_id, 1): [job(r.run_id * 10, run_id=r.run_id)] for r in runs}
    signatures = {10: TIMEOUT, 20: TIMEOUT, 30: OTHER_TIMEOUT}

    (recurring,) = find_recurring_errors(unproven_failures(runs, jobs, []), signatures, min_runs=2)

    assert recurring.runs == 2
    assert recurring.branches == ("feature/a", "main")
    assert recurring.signature == TIMEOUT
    assert recurring.examples[0].endswith("/job/20")
    assert recurring.first_seen < recurring.last_seen


def test_generic_exit_codes_and_missing_logs_never_tie_runs_together() -> None:
    runs = [branch_run(1, "main"), branch_run(2, "main"), branch_run(3, "main")]
    jobs = {AttemptRef(r.run_id, 1): [job(r.run_id * 10, run_id=r.run_id)] for r in runs}

    failures = unproven_failures(runs, jobs, [])

    assert find_recurring_errors(failures, {10: EXIT, 20: EXIT}, min_runs=2) == []


def test_most_runs_first() -> None:
    runs = [branch_run(n, "main") for n in range(1, 6)]
    jobs = {
        AttemptRef(r.run_id, 1): [
            job(r.run_id * 10, run_id=r.run_id, name="a" if r.run_id < 3 else "b")
        ]
        for r in runs
    }
    signatures = {r.run_id * 10: TIMEOUT for r in runs}

    errors = find_recurring_errors(unproven_failures(runs, jobs, []), signatures, min_runs=2)

    assert [(error.key.job, error.runs) for error in errors] == [("b", 3), ("a", 2)]
