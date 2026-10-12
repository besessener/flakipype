import sqlite3
import threading
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from flakipype.flaky.model import AttemptRef
from flakipype.flaky.signature import Category, ErrorSignature
from flakipype.store import database
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
    undated = replace(undated, completed_at=None)

    cache.save_jobs(HOST, AttemptRef(1, 1), [undated])

    assert cache.cached_jobs(HOST, [AttemptRef(1, 1)])[AttemptRef(1, 1)] == [undated]


def test_verdicts_are_only_valid_for_the_same_newest_failure(cache: ScanCache) -> None:
    cache.save_verdict(HOST, "flaky|a", last_seen="2026-10-01", result='{"v": 1}')
    cache.save_verdict(HOST, "flaky|a", last_seen="2026-10-02", result='{"v": 2}')

    assert cache.cached_verdict(HOST, "flaky|a", "2026-10-02") == '{"v": 2}'
    assert cache.cached_verdict(HOST, "flaky|a", "2026-10-01") is None
    assert cache.cached_verdict("ghes.example", "flaky|a", "2026-10-02") is None


def test_unpushed_fixes_are_remembered_until_a_newer_failure(cache: ScanCache) -> None:
    cache.save_unpushed_fix(HOST, "flaky|a", last_seen="2026-10-01", outcome="rejected")

    assert cache.unpushed_fix(HOST, "flaky|a", "2026-10-01") == "rejected"
    assert cache.unpushed_fix(HOST, "flaky|a", "2026-10-02") is None
    assert cache.unpushed_fix("ghes.example", "flaky|a", "2026-10-01") is None


def test_a_cache_file_uses_the_wal_journal(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    ScanCache.open(path).close()

    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_schema_version_is_recorded_and_migrations_run_once(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    ScanCache.open(path).close()
    ScanCache.open(path).close()

    assert schema_version(path) == len(MIGRATIONS)


def test_processes_opening_a_new_cache_together_all_succeed(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    openers = 8
    start = threading.Barrier(openers)
    errors: list[Exception] = []

    def open_cache() -> None:
        start.wait()
        try:
            ScanCache.open(path).close()
        except sqlite3.Error as error:
            errors.append(error)

    threads = [threading.Thread(target=open_cache) for _ in range(openers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert schema_version(path) == len(MIGRATIONS)


def test_opening_waits_for_another_writer_before_switching_to_wal(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    with closing(sqlite3.connect(path, isolation_level=None, check_same_thread=False)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        threading.Timer(0.1, writer.execute, ["COMMIT"]).start()

        ScanCache.open(path).close()

    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)


def test_opening_gives_up_when_another_writer_keeps_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "cache.sqlite3"
    monkeypatch.setattr(database, "_BUSY_SECONDS", 0)
    with closing(sqlite3.connect(path, isolation_level=None)) as writer:
        writer.execute("BEGIN IMMEDIATE")

        with pytest.raises(sqlite3.OperationalError, match="locked"):
            ScanCache.open(path)


def test_a_failing_migration_leaves_the_cache_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "cache.sqlite3"
    broken = "ALTER TABLE sessions ADD COLUMN extra TEXT; INSERT INTO missing VALUES (1);"
    monkeypatch.setattr(database, "MIGRATIONS", (*MIGRATIONS, broken))

    with pytest.raises(sqlite3.OperationalError, match="missing"):
        ScanCache.open(path)

    assert schema_version(path) == 0
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT name FROM sqlite_master").fetchall() == []
    monkeypatch.undo()
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
