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
    last_seen: datetime
    examples: tuple[str, ...]
    job_ids: tuple[int, ...]
    signatures: tuple[SignatureCount, ...]

    @property
    def flake_rate(self) -> float:
        return self.affected_runs / self.total_runs if self.total_runs else 0.0


def completed_runs_per_workflow(runs: Iterable[WorkflowRun]) -> Counter[tuple[str, str]]:
    return Counter(
        (run.repository, run.workflow_path)
        for run in runs
        if run.is_tracked and (run.succeeded or run.failed)
    )


def rank_flaky_jobs(
    runs: Sequence[WorkflowRun],
    failures: Iterable[FlakyFailure],
    signatures: Mapping[int, ErrorSignature],
) -> list[FlakyJob]:
    """Most affected runs first, then highest rate, then most recent."""
    totals = completed_runs_per_workflow(runs)
    groups: defaultdict[FlakyKey, list[FlakyFailure]] = defaultdict(list)
    for failure in failures:
        groups[_key(failure)].append(failure)
    ranked = [
        _summarise(
            key,
            group,
            total_runs=totals[key.repository, key.workflow_path],
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


def _summarise(
    key: FlakyKey,
    group: list[FlakyFailure],
    *,
    total_runs: int,
    signatures: Mapping[int, ErrorSignature],
) -> FlakyJob:
    newest_first = sorted(group, key=_seen_at, reverse=True)
    signals = Counter(failure.signal for failure in group)
    affected_runs = len({failure.run.run_id for failure in group})
    return FlakyJob(
        key=key,
        flaky_failures=len(group),
        affected_runs=affected_runs,
        total_runs=max(total_runs, affected_runs),
        rerun_passed=signals[Signal.RERUN_PASSED],
        same_commit=signals[Signal.SAME_COMMIT],
        last_seen=_seen_at(newest_first[0]),
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
