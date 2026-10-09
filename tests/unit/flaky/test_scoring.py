from datetime import timedelta

from flakipype.flaky.detection import find_flaky_failures
from flakipype.flaky.model import AttemptRef
from flakipype.flaky.scoring import FlakyKey, SignatureCount, rank_flaky_jobs
from flakipype.flaky.signature import Category, ErrorSignature

from support.builders import START, job, run

TIMEOUT = ErrorSignature(Category.TIMEOUT, "wait timed out", "aaaaaaaaaaaa", "excerpt")
NETWORK = ErrorSignature(Category.NETWORK, "ECONNRESET", "bbbbbbbbbbbb", "excerpt")


def test_ranking_counts_rates_signals_and_signatures() -> None:
    runs = [
        run(1, attempt=2),
        run(2, attempt=2),
        run(3, conclusion="failure", sha="c" * 40),
        run(4, sha="c" * 40),
        run(5),
        run(6, conclusion="cancelled"),
        run(7, attempt=2, workflow=".github/workflows/e2e.yml", name="E2E"),
    ]
    jobs = {
        AttemptRef(1, 1): [job(11, run_id=1)],
        AttemptRef(2, 1): [job(21, run_id=2), job(22, run_id=2, name="test", step="Run tests")],
        AttemptRef(3, 1): [job(31, run_id=3)],
        AttemptRef(7, 1): [job(71, run_id=7, name="e2e", step="Playwright")],
    }
    signatures = {11: TIMEOUT, 21: TIMEOUT, 31: NETWORK}

    ranked = rank_flaky_jobs(runs, find_flaky_failures(runs, jobs), signatures)

    top, second = ranked
    assert top.key == FlakyKey(
        "octo-org/app", ".github/workflows/ci.yml", "CI", "test", "Run tests"
    )
    assert (top.flaky_failures, top.affected_runs, top.total_runs) == (4, 3, 5)
    assert top.flake_rate == 0.6
    assert (top.rerun_passed, top.same_commit) == (3, 1)
    assert top.last_seen == START + timedelta(hours=3, minutes=1)
    assert top.examples[0].endswith("/runs/3/job/31")
    assert len(top.examples) == 3
    assert top.job_ids == (31, 21, 22, 11)
    assert top.signatures == (
        SignatureCount(Category.TIMEOUT, "wait timed out", "aaaaaaaaaaaa", 2),
        SignatureCount(Category.NETWORK, "ECONNRESET", "bbbbbbbbbbbb", 1),
    )
    assert second.key.workflow_name == "E2E"
    assert (second.affected_runs, second.total_runs, second.flake_rate) == (1, 1, 1.0)
    assert second.signatures == ()


def test_equal_runs_rank_by_rate_then_recency() -> None:
    runs = [
        run(1, attempt=2, workflow="a.yml"),
        run(2, workflow="a.yml"),
        run(3, attempt=2, workflow="b.yml"),
        run(4, attempt=2, workflow="c.yml"),
    ]
    jobs = {AttemptRef(r, 1): [job(r * 10, run_id=r)] for r in (1, 3, 4)}

    ranked = rank_flaky_jobs(runs, find_flaky_failures(runs, jobs), {})

    assert [flaky.key.workflow_path for flaky in ranked] == ["c.yml", "b.yml", "a.yml"]


def test_rate_never_exceeds_one_when_runs_were_not_counted() -> None:
    runs = [run(1, attempt=2)]
    failures = find_flaky_failures(runs, {AttemptRef(1, 1): [job(11, run_id=1)]})

    ranked = rank_flaky_jobs([], failures, {})

    assert ranked[0].total_runs == 1
    assert ranked[0].flake_rate == 1.0


def test_job_without_completion_time_uses_the_run_creation() -> None:
    runs = [run(1, attempt=2)]
    failure_job = job(11, run_id=1)
    undated = type(failure_job)(**{**failure_job.__dict__, "completed_at": None})

    ranked = rank_flaky_jobs(runs, find_flaky_failures(runs, {AttemptRef(1, 1): [undated]}), {})

    assert ranked[0].last_seen == runs[0].created_at
