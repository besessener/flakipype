"""Append-only log of every action request: what was asked, the answer, and GitHub's answer."""

import sqlite3
from dataclasses import dataclass
from enum import StrEnum


class AuditStatus(StrEnum):
    """What came of a request; the daily limits count on this, never on the outcome text."""

    # It happened on GitHub.
    DONE = "done"
    # The gate or the person did not allow it.
    DECLINED = "declined"
    # A check refused it before anything happened on GitHub.
    REFUSED = "refused"
    # GitHub refused it or failed.
    FAILED = "failed"


@dataclass(frozen=True)
class AuditEntry:
    time: str
    session: str
    action: str
    # "model", "command" or "run": who asked for it.
    origin: str
    request: str
    # The gate's answer, e.g. "confirmed", "declined", "auto"; or what covered the action.
    answer: str
    # For people; code reads status and spent.
    outcome: str
    status: AuditStatus
    # Reruns, dispatches or pull requests it started; what the daily limits add up.
    spent: int
    run_id: int | None = None


class AuditLog:
    """Uses the cache database; the schema comes from its migrations. Never updates or deletes."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def record(self, entry: AuditEntry) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO action_log (time, session, action, origin, request, answer, outcome, "
                "status, spent, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entry.time, entry.session, entry.action, entry.origin, entry.request,
                 entry.answer, entry.outcome, entry.status.value, entry.spent, entry.run_id),
            )  # fmt: skip

    def entries(self, session: str) -> list[AuditEntry]:
        rows = self._db.execute(
            "SELECT time, session, action, origin, request, answer, outcome, status, spent, run_id "
            "FROM action_log WHERE session = ? ORDER BY id",
            (session,),
        ).fetchall()
        return [_entry(row) for row in rows]

    def since(self, time: str) -> list[AuditEntry]:
        """Every entry at or after `time` (ISO time), oldest first."""
        rows = self._db.execute(
            "SELECT time, session, action, origin, request, answer, outcome, status, spent, run_id "
            "FROM action_log WHERE time >= ? ORDER BY id",
            (time,),
        ).fetchall()
        return [_entry(row) for row in rows]


def _entry(row: tuple[str, str, str, str, str, str, str, str, int, int | None]) -> AuditEntry:
    time, session, action, origin, request, answer, outcome, status, spent, run_id = row
    return AuditEntry(
        time, session, action, origin, request, answer, outcome, AuditStatus(status), spent,
        run_id,
    )  # fmt: skip
