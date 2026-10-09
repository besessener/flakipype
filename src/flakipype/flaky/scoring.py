"""Aggregate flaky failures per job and step and rank them."""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from flakipype.flaky.detection import FlakyFailure, Signal
from flakipype.flaky.model import WorkflowRun
from flakipype.flaky.signature import Category, ErrorSignature

_EXAMPLES = 3


@dataclass(frozen=True)
class FlakyKey:
    repository: str
    workflow_path: str
    workflow_name: str
    job: str
    step: str


@dataclass(frozen=True)
class SignatureCount:
    category: Category
    message: str
    fingerprint: str
    occurrences: int


@dataclass(frozen=True)
class FlakyJob:
    key: FlakyKey
    flaky_failures: int
    affected_runs: int
    total_runs: int
    rerun_passed: int
    same_commit: int
    first_seen: datetime
    last_seen: datetime
    # The workflow passed between the first and the last affected run: the failure came back.
    recurred: bool
    # First passing run of the workflow from the last affected run on, if any.
    passing_since: datetime | None
    examples: tuple[str, ...]
    job_ids: tuple[int, ...]
    signatures: tuple[SignatureCount, ...]

    @property
    def flake_rate(self) -> float:
        return self.affected_runs / self.total_runs if self.total_runs else 0.0


type _Workflow = tuple[str, str]


def completed_runs_per_workflow(runs: Iterable[WorkflowRun]) -> Counter[_Workflow]:
    return Counter(
        (run.repository, run.workflow_path)
        for run in runs
        if run.is_tracked and (run.succeeded or run.failed)
    )


def passes_per_workflow(runs: Iterable[WorkflowRun]) -> dict[_Workflow, list[datetime]]:
    """Creation times of passing runs, oldest first; a run that passed on rerun counts."""
    passes: defaultdict[_Workflow, list[datetime]] = defaultdict(list)
    for run in runs:
        if run.is_tracked and run.succeeded:
            passes[run.repository, run.workflow_path].append(run.created_at)
    return {workflow: sorted(times) for workflow, times in passes.items()}


def rank_flaky_jobs(
    runs: Sequence[WorkflowRun],
    failures: Iterable[FlakyFailure],
    signatures: Mapping[int, ErrorSignature],
) -> list[FlakyJob]:
    """Most affected runs first, then highest rate, then most recent."""
    totals = completed_runs_per_workflow(runs)
    passes = passes_per_workflow(runs)
    groups: defaultdict[FlakyKey, list[FlakyFailure]] = defaultdict(list)
    for failure in failures:
        groups[_key(failure)].append(failure)
    ranked = [
        _summarise(
            key,
            group,
            history=_History(
                total_runs=totals[key.repository, key.workflow_path],
                passes=passes.get((key.repository, key.workflow_path), []),
            ),
            signatures=signatures,
        )
        for key, group in groups.items()
    ]
    return sorted(
        ranked, key=lambda job: (-job.affected_runs, -job.flake_rate, -job.last_seen.timestamp())
    )


def _key(failure: FlakyFailure) -> FlakyKey:
    return FlakyKey(
        repository=failure.run.repository,
        workflow_path=failure.run.workflow_path,
        workflow_name=failure.run.workflow_name,
        job=failure.job.name,
        step=failure.job.failed_step,
    )


@dataclass(frozen=True)
class _History:
    total_runs: int
    passes: list[datetime]


def _summarise(
    key: FlakyKey,
    group: list[FlakyFailure],
    *,
    history: _History,
    signatures: Mapping[int, ErrorSignature],
) -> FlakyJob:
    newest_first = sorted(group, key=_seen_at, reverse=True)
    signals = Counter(failure.signal for failure in group)
    run_times = sorted({failure.run.run_id: failure.run.created_at for failure in group}.values())
    first_run, last_run = run_times[0], run_times[-1]
    return FlakyJob(
        key=key,
        flaky_failures=len(group),
        affected_runs=len(run_times),
        total_runs=max(history.total_runs, len(run_times)),
        rerun_passed=signals[Signal.RERUN_PASSED],
        same_commit=signals[Signal.SAME_COMMIT],
        first_seen=_seen_at(newest_first[-1]),
        last_seen=_seen_at(newest_first[0]),
        recurred=any(first_run <= passed < last_run for passed in history.passes),
        passing_since=next((passed for passed in history.passes if passed >= last_run), None),
        examples=tuple(failure.job.url for failure in newest_first[:_EXAMPLES]),
        job_ids=tuple(failure.job.job_id for failure in newest_first),
        signatures=_count_signatures(newest_first, signatures),
    )


def _seen_at(failure: FlakyFailure) -> datetime:
    return failure.job.completed_at or failure.run.created_at


def _count_signatures(
    group: list[FlakyFailure], signatures: Mapping[int, ErrorSignature]
) -> tuple[SignatureCount, ...]:
    found = [signatures[f.job.job_id] for f in group if f.job.job_id in signatures]
    counts = Counter(signature.fingerprint for signature in found)
    by_fingerprint = {signature.fingerprint: signature for signature in found}
    return tuple(
        SignatureCount(by_fingerprint[fp].category, by_fingerprint[fp].message, fp, occurrences)
        for fp, occurrences in counts.most_common()
    )
