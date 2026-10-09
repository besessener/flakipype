import sqlite3
from contextlib import closing
from pathlib import Path

from flakipype.flaky.model import AttemptRef
from flakipype.flaky.signature import Category, ErrorSignature
from flakipype.store.database import MIGRATIONS, LogResult, LogState, ScanCache

from support.builders import job

HOST = "github.com"
SIGNATURE = ErrorSignature(Category.TIMEOUT, "wait timed out", "aaaaaaaaaaaa", "Timeout: 20000ms")


def schema_version(path: Path) -> int:
    with closing(sqlite3.connect(path)) as connection:
        version: int = connection.execute("PRAGMA user_version").fetchone()[0]
        return version


def test_jobs_of_an_attempt_survive_reopening(tmp_path: Path) -> None:
    path = tmp_path / "data" / "cache.sqlite3"
    jobs = [job(11, run_id=1), job(12, run_id=1, conclusion="success")]
    with ScanCache.open(path) as first:
        first.save_jobs(HOST, AttemptRef(1, 1), jobs)

    with ScanCache.open(path) as reopened:
        cached = reopened.cached_jobs(HOST, [AttemptRef(1, 1), AttemptRef(1, 2)])

    assert cached == {AttemptRef(1, 1): jobs}


def test_an_attempt_without_jobs_is_still_cached(cache: ScanCache) -> None:
    cache.save_jobs(HOST, AttemptRef(1, 1), [])

    assert cache.cached_jobs(HOST, [AttemptRef(1, 1)]) == {AttemptRef(1, 1): []}


def test_hosts_do_not_share_entries(cache: ScanCache) -> None:
    cache.save_jobs(HOST, AttemptRef(1, 1), [job(11, run_id=1)])
    cache.save_log_result(HOST, 11, LogResult(LogState.SIGNATURE, SIGNATURE))

    assert cache.cached_jobs("github.example.com", [AttemptRef(1, 1)]) == {}
    assert cache.log_results("github.example.com", [11]) == {}


def test_log_results_round_trip(cache: ScanCache) -> None:
    cache.save_log_result(HOST, 11, LogResult(LogState.SIGNATURE, SIGNATURE))
    cache.save_log_result(HOST, 12, LogResult(LogState.UNAVAILABLE))
    cache.save_log_result(HOST, 13, LogResult(LogState.NO_ERROR_LINES))

    assert cache.log_results(HOST, [11, 12, 13, 14]) == {
        11: LogResult(LogState.SIGNATURE, SIGNATURE),
        12: LogResult(LogState.UNAVAILABLE),
        13: LogResult(LogState.NO_ERROR_LINES),
    }


def test_job_without_completion_time(cache: ScanCache) -> None:
    undated = job(11, run_id=1)
    undated = type(undated)(**{**undated.__dict__, "completed_at": None})

    cache.save_jobs(HOST, AttemptRef(1, 1), [undated])

    assert cache.cached_jobs(HOST, [AttemptRef(1, 1)])[AttemptRef(1, 1)] == [undated]


def test_verdicts_are_only_valid_for_the_same_newest_failure(cache: ScanCache) -> None:
    cache.save_verdict(HOST, "flaky|a", last_seen="2026-10-01", result='{"v": 1}')
    cache.save_verdict(HOST, "flaky|a", last_seen="2026-10-02", result='{"v": 2}')

    assert cache.cached_verdict(HOST, "flaky|a", "2026-10-02") == '{"v": 2}'
    assert cache.cached_verdict(HOST, "flaky|a", "2026-10-01") is None
    assert cache.cached_verdict("ghes.example", "flaky|a", "2026-10-02") is None


def test_schema_version_is_recorded_and_migrations_run_once(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    ScanCache.open(path).close()
    ScanCache.open(path).close()

    assert schema_version(path) == len(MIGRATIONS)


def test_signatures_from_an_older_algorithm_are_read_again() -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        cache = ScanCache(connection)
        cache.save_log_result(HOST, 11, LogResult(LogState.SIGNATURE, SIGNATURE))
        with connection:
            connection.execute("UPDATE job_logs SET signature_version = signature_version - 1")

        assert cache.log_results(HOST, [11]) == {}


def test_a_version_one_cache_is_migrated_and_its_signatures_recomputed(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(MIGRATIONS[0])
        connection.execute("PRAGMA user_version = 1")
        connection.execute(
            "INSERT INTO job_logs VALUES (?, 11, 'signature', 'exit code', 'm', 'f', 'e')", (HOST,)
        )

    with ScanCache.open(path) as migrated:
        assert migrated.log_results(HOST, [11]) == {}

    assert schema_version(path) == len(MIGRATIONS)
