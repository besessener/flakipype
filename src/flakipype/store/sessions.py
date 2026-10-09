"""Chat sessions: a title, timestamps and an opaque JSON document per session."""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionSummary:
    session_id: int
    title: str
    updated: str


class SessionStore:
    """Uses the cache database; the schema comes from its migrations."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def create(self, title: str, *, now: str, data: str) -> int:
        with self._db:
            cursor = self._db.execute(
                "INSERT INTO sessions (title, created, updated, data) VALUES (?, ?, ?, ?)",
                (title, now, now, data),
            )
        return int(cursor.lastrowid or 0)

    def update(self, session_id: int, *, now: str, data: str) -> None:
        with self._db:
            self._db.execute(
                "UPDATE sessions SET updated = ?, data = ? WHERE id = ?", (now, data, session_id)
            )

    def load(self, session_id: int) -> str | None:
        row = self._db.execute("SELECT data FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return str(row[0]) if row else None

    def recent(self, limit: int) -> list[SessionSummary]:
        rows = self._db.execute(
            "SELECT id, title, updated FROM sessions ORDER BY updated DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [SessionSummary(int(row[0]), str(row[1]), str(row[2])) for row in rows]
