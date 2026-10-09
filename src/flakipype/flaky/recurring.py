"""The same error in several runs without proof of flakiness: could be flaky, could be real bugs."""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from flakipype.flaky.detection import FlakyFailure
from flakipype.flaky.model import AttemptRef, JobResult, WorkflowRun
from flakipype.flaky.scoring import FlakyKey
from flakipype.flaky.signature import Category, ErrorSignature

_EXAMPLES = 3


@dataclass(frozen=True)
class FailedJob:
    run: WorkflowRun
    job: JobResult

    @property
    def seen_at(self) -> datetime:
        return self.job.completed_at or self.run.created_at


@dataclass(frozen=True)
class RecurringError:
    key: FlakyKey
    signature: ErrorSignature
    runs: int
    branches: tuple[str, ...]
    first_seen: datetime
    last_seen: datetime
    examples: tuple[str, ...]
    job_ids: tuple[int, ...] = ()


def latest_failed_attempts(runs: Iterable[WorkflowRun]) -> list[AttemptRef]:
    """Final attempts of failed runs: their jobs show which error ended the run."""
    return [AttemptRef(run.run_id, run.attempt) for run in runs if run.is_tracked and run.failed]


def unproven_failures(
    runs: Iterable[WorkflowRun],
    jobs: Mapping[AttemptRef, Sequence[JobResult]],
    proven: Iterable[FlakyFailure],
) -> list[FailedJob]:
    """Failed jobs that ended a run and are not already proven flaky."""
    known = {failure.job.job_id for failure in proven}
    runs_by_id = {run.run_id: run for run in runs}
    return [
        FailedJob(runs_by_id[ref.run_id], job)
        for ref in latest_failed_attempts(runs_by_id.values())
        for job in jobs.get(ref, ())
        if job.failed and job.attempt_ref == ref and job.job_id not in known
    ]


def find_recurring_errors(
    failures: Iterable[FailedJob],
    signatures: Mapping[int, ErrorSignature],
    min_runs: int,
) -> list[RecurringError]:
    """Same job, step and error in at least `min_runs` runs, on any branch; most runs first."""
    groups: defaultdict[tuple[FlakyKey, str], list[FailedJob]] = defaultdict(list)
    for failure in failures:
        signature = signatures.get(failure.job.job_id)
        # A generic exit code says nothing about the cause, so it cannot tie runs together.
        if signature is None or signature.category is Category.EXIT_CODE:
            continue
        groups[_key(failure), signature.fingerprint].append(failure)
    recurring = [
        _summarise(key, group, signatures[group[0].job.job_id])
        for (key, _), group in groups.items()
        if len({failure.run.run_id for failure in group}) >= min_runs
    ]
    return sorted(recurring, key=lambda error: (-error.runs, -error.last_seen.timestamp()))


def _key(failure: FailedJob) -> FlakyKey:
    return FlakyKey(
        repository=failure.run.repository,
        workflow_path=failure.run.workflow_path,
        workflow_name=failure.run.workflow_name,
        job=failure.job.name,
        step=failure.job.failed_step,
    )


def _summarise(
    key: FlakyKey, group: Sequence[FailedJob], signature: ErrorSignature
) -> RecurringError:
    newest_first = sorted(group, key=lambda failure: failure.seen_at, reverse=True)
    return RecurringError(
        key=key,
        signature=signature,
        runs=len({failure.run.run_id for failure in group}),
        branches=tuple(sorted({failure.run.head_branch for failure in group})),
        first_seen=newest_first[-1].seen_at,
        last_seen=newest_first[0].seen_at,
        examples=tuple(failure.job.url for failure in newest_first[:_EXAMPLES]),
        job_ids=tuple(failure.job.job_id for failure in newest_first),
    )
