"""Numbered findings of a scan: what the user can pick and the agent can investigate."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from flakipype.flaky.model import AttemptRef, JobResult, WorkflowRun
from flakipype.flaky.recurring import RecurringError
from flakipype.flaky.scoring import FlakyJob, FlakyKey
from flakipype.flaky.signature import ErrorSignature
from flakipype.flaky.verdict import FlakyRanking


class FindingKind(StrEnum):
    FLAKY = "flaky"
    SEEN_ONCE = "seen_once"
    FIXED = "fixed"
    RECURRING = "recurring"


@dataclass(frozen=True)
class Evidence:
    """What the scan read: runs, the jobs of inspected attempts and log signatures."""

    runs: Sequence[WorkflowRun] = ()
    jobs: Mapping[AttemptRef, Sequence[JobResult]] = field(default_factory=dict)
    signatures: Mapping[int, ErrorSignature] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    number: int
    kind: FindingKind
    key: FlakyKey
    facts: tuple[str, ...]
    job_ids: tuple[int, ...]
    last_seen: datetime
    fingerprint: str = ""

    @property
    def identity(self) -> str:
        """Stable across scans; a verdict for it stays valid until a newer failure shows up."""
        key = self.key
        parts = (self.kind, key.repository, key.workflow_path, key.job, key.step, self.fingerprint)
        return "|".join(parts)


def _when(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def _job_facts(job: FlakyJob, kind: FindingKind) -> tuple[str, ...]:
    facts = [
        f"Status: {kind.value}",
        f"Runs with a proven flaky event: {job.affected_runs} of {job.total_runs} finished runs",
        f"Failed again in the same run but passed on rerun: {job.rerun_passed} times",
        f"Failed while the same commit passed in another run: {job.same_commit} times",
        f"First seen {_when(job.first_seen)}, last seen {_when(job.last_seen)}",
        "Passing since " + (_when(job.passing_since) if job.passing_since else "— (not yet)"),
    ]
    facts.extend(
        f"Error signature ({s.category.value}, {s.occurrences}x): {s.message}"
        for s in job.signatures
    )
    return tuple(facts)


def _recurring_facts(error: RecurringError) -> tuple[str, ...]:
    signature = error.signature
    return (
        "Status: recurring error without proof of flakiness (could be flaky or a real bug)",
        f"Runs that ended with this error: {error.runs}",
        f"Branches: {', '.join(error.branches)}",
        f"First seen {_when(error.first_seen)}, last seen {_when(error.last_seen)}",
        f"Error signature ({signature.category.value}): {signature.message}",
    )


def number_findings(ranking: FlakyRanking, recurring: Iterable[RecurringError]) -> list[Finding]:
    """Flaky first in ranking order, then seen once, fixed and recurring errors."""
    groups = (
        (FindingKind.FLAKY, ranking.flaky),
        (FindingKind.SEEN_ONCE, ranking.seen_once),
        (FindingKind.FIXED, ranking.fixed),
    )
    findings = [
        (kind, job.key, _job_facts(job, kind), job.job_ids, job.last_seen, "")
        for kind, jobs in groups
        for job in jobs
    ]
    findings.extend(
        (FindingKind.RECURRING, e.key, _recurring_facts(e), e.job_ids, e.last_seen,
         e.signature.fingerprint)
        for e in recurring
    )  # fmt: skip
    return [
        Finding(number, kind, key, facts, job_ids, last_seen, fingerprint)
        for number, (kind, key, facts, job_ids, last_seen, fingerprint) in enumerate(
            findings, start=1
        )
    ]
