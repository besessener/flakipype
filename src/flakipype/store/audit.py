"""Append-only log of every action request: what was asked, the answer, and GitHub's answer."""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class AuditEntry:
    time: str
    session: str
    action: str
    # "model" or "command": who asked for it.
    origin: str
    request: str
    # "confirmed" or "declined".
    answer: str
    outcome: str
    run_id: int | None = None


class AuditLog:
    """Uses the cache database; the schema comes from its migrations. Never updates or deletes."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def record(self, entry: AuditEntry) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO action_log (time, session, action, origin, request, answer, outcome, "
                "run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (entry.time, entry.session, entry.action, entry.origin, entry.request,
                 entry.answer, entry.outcome, entry.run_id),
            )  # fmt: skip

    def entries(self, session: str) -> list[AuditEntry]:
        rows = self._db.execute(
            "SELECT time, session, action, origin, request, answer, outcome, run_id "
            "FROM action_log WHERE session = ? ORDER BY id",
            (session,),
        ).fetchall()
        return [AuditEntry(*row) for row in rows]
