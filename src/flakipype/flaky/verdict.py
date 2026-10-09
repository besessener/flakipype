"""Is a job really flaky, only seen once, or was it fixed?"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from flakipype.flaky.scoring import FlakyJob


class Verdict(StrEnum):
    FLAKY = "flaky"
    """Failed this way in enough runs, and passed in between: the failure keeps coming back."""
    SEEN_ONCE = "seen_once"
    """Fewer affected runs than required; a single event can be an outage or a fix."""
    FIXED = "fixed"
    """Several failures, all before the workflow started passing for good: a real error fixed."""


def verdict(job: FlakyJob, min_runs: int) -> Verdict:
    if job.affected_runs < min_runs:
        return Verdict.SEEN_ONCE
    # One run cannot recur; with min_runs = 1 the user asked to count it anyway.
    if job.affected_runs > 1 and not job.recurred:
        return Verdict.FIXED
    return Verdict.FLAKY


@dataclass(frozen=True)
class FlakyRanking:
    min_runs: int
    flaky: list[FlakyJob]
    seen_once: list[FlakyJob]
    fixed: list[FlakyJob]


def classify(ranked: Iterable[FlakyJob], min_runs: int) -> FlakyRanking:
    """Keep the ranking order inside each group."""
    groups: dict[Verdict, list[FlakyJob]] = {kind: [] for kind in Verdict}
    for job in ranked:
        groups[verdict(job, min_runs)].append(job)
    return FlakyRanking(
        min_runs=min_runs,
        flaky=groups[Verdict.FLAKY],
        seen_once=groups[Verdict.SEEN_ONCE],
        fixed=groups[Verdict.FIXED],
    )
