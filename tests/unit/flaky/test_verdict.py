from datetime import timedelta

from flakipype.flaky.detection import find_flaky_failures
from flakipype.flaky.model import AttemptRef, WorkflowRun
from flakipype.flaky.scoring import FlakyJob, rank_flaky_jobs
from flakipype.flaky.verdict import Verdict, classify, verdict

from support.builders import START, job, run


def ranked(runs: list[WorkflowRun], failed_attempts: dict[int, int]) -> FlakyJob:
    jobs = {AttemptRef(run_id, 1): [job(run_id * 10, run_id=run_id)] for run_id in failed_attempts}
    (flaky,) = rank_flaky_jobs(runs, find_flaky_failures(runs, jobs), {})
    return flaky


def test_reruns_spread_over_time_are_flaky() -> None:
    flaky = ranked([run(1, attempt=2), run(2), run(5, attempt=2)], {1: 1, 5: 1})

    assert flaky.recurred
    assert verdict(flaky, min_runs=2) is Verdict.FLAKY


def test_a_single_occurrence_is_only_seen_once() -> None:
    flaky = ranked([run(1, attempt=2), run(2)], {1: 1})

    assert verdict(flaky, min_runs=2) is Verdict.SEEN_ONCE
    assert verdict(flaky, min_runs=1) is Verdict.FLAKY


def test_failures_that_stop_after_a_fix_are_fixed() -> None:
    # Two pushes of one commit failed; after a settings change a dispatch on it passed for good.
    sha = "f" * 40
    runs = [
        run(1, conclusion="failure", sha=sha),
        run(2, conclusion="failure", sha=sha),
        run(3, sha=sha),
        run(4),
    ]

    flaky = ranked(runs, {1: 1, 2: 1})

    assert not flaky.recurred
    assert flaky.passing_since == START + timedelta(hours=3)
    assert verdict(flaky, min_runs=2) is Verdict.FIXED


def test_still_failing_has_no_passing_since() -> None:
    sha = "f" * 40
    runs = [
        run(1, sha=sha),
        run(2, conclusion="failure", sha=sha),
        run(3, conclusion="failure", sha=sha),
    ]

    flaky = ranked(runs, {2: 1, 3: 1})

    assert flaky.passing_since is None
    assert flaky.first_seen < flaky.last_seen


def test_classify_keeps_the_ranking_order_in_each_group() -> None:
    flaky = ranked([run(1, attempt=2), run(2), run(5, attempt=2)], {1: 1, 5: 1})
    once = ranked([run(1, attempt=2)], {1: 1})

    ranking = classify([flaky, once, flaky], min_runs=2)

    assert (ranking.min_runs, ranking.flaky, ranking.seen_once, ranking.fixed) == (
        2,
        [flaky, flaky],
        [once],
        [],
    )
