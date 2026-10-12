"""SQLite cache for what is expensive to fetch: jobs of finished attempts and log signatures."""

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Self

from flakipype.flaky.model import AttemptRef, JobResult
from flakipype.flaky.signature import SIGNATURE_VERSION, Category, ErrorSignature
from flakipype.store.audit import AuditLog
from flakipype.store.sessions import SessionStore

# Append only: each entry migrates from the previous schema version to the next.
MIGRATIONS = (
    """
    CREATE TABLE inspected_attempts (
        host TEXT NOT NULL, run_id INTEGER NOT NULL, attempt INTEGER NOT NULL,
        PRIMARY KEY (host, run_id, attempt)
    );
    CREATE TABLE jobs (
        host TEXT NOT NULL, job_id INTEGER NOT NULL, run_id INTEGER NOT NULL,
        attempt INTEGER NOT NULL, name TEXT NOT NULL, conclusion TEXT,
        failed_step TEXT NOT NULL, completed_at TEXT, url TEXT NOT NULL,
        PRIMARY KEY (host, job_id)
    );
    CREATE INDEX jobs_by_attempt ON jobs (host, run_id, attempt);
    CREATE TABLE job_logs (
        host TEXT NOT NULL, job_id INTEGER NOT NULL, state TEXT NOT NULL,
        category TEXT, message TEXT, fingerprint TEXT, excerpt TEXT,
        PRIMARY KEY (host, job_id)
    );
    """,
    "ALTER TABLE job_logs ADD COLUMN signature_version INTEGER NOT NULL DEFAULT 1;",
    """
    CREATE TABLE verdicts (
        host TEXT NOT NULL, identity TEXT NOT NULL, last_seen TEXT NOT NULL,
        result TEXT NOT NULL, PRIMARY KEY (host, identity)
    );
    """,
    """
    CREATE TABLE sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
        created TEXT NOT NULL, updated TEXT NOT NULL, data TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE action_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, session TEXT NOT NULL,
        action TEXT NOT NULL, origin TEXT NOT NULL, request TEXT NOT NULL,
        answer TEXT NOT NULL, outcome TEXT NOT NULL, run_id INTEGER
    );
    CREATE INDEX action_log_by_session ON action_log (session);
    """,
    """
    ALTER TABLE sessions ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat';
    CREATE INDEX action_log_by_time ON action_log (time);
    CREATE TABLE fix_attempts (
        host TEXT NOT NULL, identity TEXT NOT NULL, last_seen TEXT NOT NULL,
        outcome TEXT NOT NULL, PRIMARY KEY (host, identity)
    );
    """,
    """
    CREATE TABLE no_verdicts (
        host TEXT NOT NULL, identity TEXT NOT NULL, last_seen TEXT NOT NULL,
        detail TEXT NOT NULL, PRIMARY KEY (host, identity)
    );
    """,
)
# The chat and a run may write at the same time; a writer waits this long for the other.
_BUSY_SECONDS = 30


class LogState(StrEnum):
    SIGNATURE = "signature"
    NO_ERROR_LINES = "no_error_lines"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class LogResult:
    state: LogState
    signature: ErrorSignature | None = None


def _schema_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _migrate(connection: sqlite3.Connection) -> None:
    """All missing steps in one transaction, so a crash or a second process never sees half."""
    if _schema_version(connection) >= len(MIGRATIONS):
        return
    # In legacy mode executescript commits first, which would end the transaction after a step.
    connection.autocommit = True
    try:
        connection.execute("BEGIN IMMEDIATE")
        # Read again under the write lock: another process may have migrated meanwhile.
        for script in MIGRATIONS[_schema_version(connection) :]:
            connection.executescript(script)
        connection.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")
        connection.execute("COMMIT")
    finally:
        # Legacy rollback() ends a failed migration and does nothing after the commit.
        connection.autocommit = sqlite3.LEGACY_TRANSACTION_CONTROL
        connection.rollback()


def _parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class ScanCache:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection
        _migrate(self._db)

    @classmethod
    def open(cls, path: Path) -> "ScanCache":
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=_BUSY_SECONDS, check_same_thread=False)
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            return cls(connection)
        except BaseException:
            connection.close()
            raise

    @classmethod
    def in_memory(cls) -> "ScanCache":
        return cls(sqlite3.connect(":memory:", check_same_thread=False))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    @property
    def sessions(self) -> SessionStore:
        return SessionStore(self._db)

    @property
    def audit(self) -> AuditLog:
        return AuditLog(self._db)

    def cached_jobs(
        self, host: str, refs: Iterable[AttemptRef]
    ) -> dict[AttemptRef, list[JobResult]]:
        cached: dict[AttemptRef, list[JobResult]] = {}
        for ref in refs:
            inspected = self._db.execute(
                "SELECT 1 FROM inspected_attempts WHERE host = ? AND run_id = ? AND attempt = ?",
                (host, ref.run_id, ref.attempt),
            ).fetchone()
            if inspected:
                cached[ref] = self._jobs_of(host, ref)
        return cached

    def _jobs_of(self, host: str, ref: AttemptRef) -> list[JobResult]:
        rows = self._db.execute(
            "SELECT job_id, name, conclusion, failed_step, completed_at, url FROM jobs "
            "WHERE host = ? AND run_id = ? AND attempt = ? ORDER BY job_id",
            (host, ref.run_id, ref.attempt),
        ).fetchall()
        return [
            JobResult(ref.run_id, ref.attempt, job_id, name, conclusion, step, _parse_time(at), url)
            for job_id, name, conclusion, step, at, url in rows
        ]

    def save_jobs(self, host: str, ref: AttemptRef, jobs: Iterable[JobResult]) -> None:
        rows = [
            (host, job.job_id, job.run_id, job.attempt, job.name, job.conclusion,
             job.failed_step, job.completed_at.isoformat() if job.completed_at else None, job.url)
            for job in jobs
        ]  # fmt: skip
        with self._db:
            self._db.executemany("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?,?,?)", rows)
            self._db.execute(
                "INSERT OR REPLACE INTO inspected_attempts VALUES (?, ?, ?)",
                (host, ref.run_id, ref.attempt),
            )

    def log_results(self, host: str, job_ids: Iterable[int]) -> dict[int, LogResult]:
        results: dict[int, LogResult] = {}
        for job_id in job_ids:
            row = self._db.execute(
                "SELECT state, category, message, fingerprint, excerpt FROM job_logs "
                "WHERE host = ? AND job_id = ? AND signature_version = ?",
                (host, job_id, SIGNATURE_VERSION),
            ).fetchone()
            if row:
                results[job_id] = _log_result(row)
        return results

    def save_log_result(self, host: str, job_id: int, result: LogResult) -> None:
        signature = result.signature
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO job_logs (host, job_id, state, category, message, "
                "fingerprint, excerpt, signature_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    host,
                    job_id,
                    result.state.value,
                    signature.category.value if signature else None,
                    signature.message if signature else None,
                    signature.fingerprint if signature else None,
                    signature.excerpt if signature else None,
                    SIGNATURE_VERSION,
                ),
            )

    def cached_verdict(self, host: str, identity: str, last_seen: str) -> str | None:
        """The stored result, if it was made after the finding's newest failure."""
        row = self._db.execute(
            "SELECT result FROM verdicts WHERE host = ? AND identity = ? AND last_seen = ?",
            (host, identity, last_seen),
        ).fetchone()
        return str(row[0]) if row else None

    def save_verdict(self, host: str, identity: str, *, last_seen: str, result: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO verdicts VALUES (?, ?, ?, ?)",
                (host, identity, last_seen, result),
            )

    def unpushed_fix(self, host: str, identity: str, last_seen: str) -> str | None:
        """Why a run did not push a fix for the finding, if it had no newer failure since."""
        row = self._db.execute(
            "SELECT outcome FROM fix_attempts WHERE host = ? AND identity = ? AND last_seen = ?",
            (host, identity, last_seen),
        ).fetchone()
        return str(row[0]) if row else None

    def save_unpushed_fix(self, host: str, identity: str, *, last_seen: str, outcome: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO fix_attempts VALUES (?, ?, ?, ?)",
                (host, identity, last_seen, outcome),
            )

    def no_verdict(self, host: str, identity: str, last_seen: str) -> str | None:
        """Why a run's investigation had no verdict, if the finding has not failed since."""
        row = self._db.execute(
            "SELECT detail FROM no_verdicts WHERE host = ? AND identity = ? AND last_seen = ?",
            (host, identity, last_seen),
        ).fetchone()
        return str(row[0]) if row else None

    def save_no_verdict(self, host: str, identity: str, *, last_seen: str, detail: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO no_verdicts VALUES (?, ?, ?, ?)",
                (host, identity, last_seen, detail),
            )


type _LogRow = tuple[str, str | None, str | None, str | None, str | None]


def _log_result(row: _LogRow) -> LogResult:
    state, category, message, fingerprint, excerpt = row
    if category is None or message is None or fingerprint is None or excerpt is None:
        return LogResult(LogState(state))
    return LogResult(
        LogState(state), ErrorSignature(Category(category), message, fingerprint, excerpt)
    )
