"""Which failures are flaky: the same code both failed and passed."""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from flakipype.flaky.model import AttemptRef, JobResult, WorkflowRun


class Signal(StrEnum):
    RERUN_PASSED = "rerun_passed"
    """An attempt failed and a later attempt of the same run passed."""
    SAME_COMMIT = "same_commit"
    """The run failed while another run of the same workflow passed on the same commit."""


@dataclass(frozen=True)
class FlakyFailure:
    run: WorkflowRun
    job: JobResult
    signal: Signal


def attempts_to_inspect(runs: Iterable[WorkflowRun]) -> dict[AttemptRef, Signal]:
    """The attempts whose failed jobs are flaky; only these need their jobs fetched."""
    tracked = [run for run in runs if run.is_tracked]
    inspect = _same_commit_attempts(tracked)
    for run in tracked:
        if run.succeeded and run.attempt > 1:
            for attempt in range(1, run.attempt):
                inspect[AttemptRef(run.run_id, attempt)] = Signal.RERUN_PASSED
    return inspect


def _same_commit_attempts(runs: Sequence[WorkflowRun]) -> dict[AttemptRef, Signal]:
    by_commit: defaultdict[tuple[str, str, str], list[WorkflowRun]] = defaultdict(list)
    for run in runs:
        by_commit[run.repository, run.workflow_path, run.head_sha].append(run)
    inspect: dict[AttemptRef, Signal] = {}
    for group in by_commit.values():
        if not any(run.succeeded for run in group):
            continue
        for run in group:
            if run.failed:
                inspect[AttemptRef(run.run_id, run.attempt)] = Signal.SAME_COMMIT
    return inspect


def find_flaky_failures(
    runs: Iterable[WorkflowRun],
    jobs: Mapping[AttemptRef, Sequence[JobResult]],
) -> list[FlakyFailure]:
    runs_by_id = {run.run_id: run for run in runs}
    return [
        FlakyFailure(runs_by_id[ref.run_id], job, signal)
        for ref, signal in attempts_to_inspect(runs_by_id.values()).items()
        for job in jobs.get(ref, ())
        if job.failed and job.attempt_ref == ref
    ]
