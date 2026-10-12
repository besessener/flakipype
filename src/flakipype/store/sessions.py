"""Sessions of the chat and of unattended runs: a title, timestamps and a JSON document each."""

import sqlite3
from dataclasses import dataclass
from enum import StrEnum


class SessionKind(StrEnum):
    CHAT = "chat"
    RUN = "run"


@dataclass(frozen=True)
class SessionSummary:
    session_id: int
    title: str
    updated: str
    kind: SessionKind = SessionKind.CHAT


class SessionStore:
    """Uses the cache database; the schema comes from its migrations."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def create(
        self, title: str, *, now: str, data: str, kind: SessionKind = SessionKind.CHAT
    ) -> int:
        with self._db:
            cursor = self._db.execute(
                "INSERT INTO sessions (title, created, updated, data, kind) VALUES (?, ?, ?, ?, ?)",
                (title, now, now, data, kind.value),
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

    def kind(self, session_id: int) -> SessionKind | None:
        row = self._db.execute("SELECT kind FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return SessionKind(row[0]) if row else None

    def recent(self, limit: int) -> list[SessionSummary]:
        rows = self._db.execute(
            "SELECT id, title, updated, kind FROM sessions ORDER BY updated DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            SessionSummary(int(row[0]), str(row[1]), str(row[2]), SessionKind(row[3]))
            for row in rows
        ]

    def latest_run(self, *, before: int) -> str | None:
        """The document of the newest run session older than `before`."""
        row = self._db.execute(
            "SELECT data FROM sessions WHERE kind = ? AND id < ? ORDER BY id DESC LIMIT 1",
            (SessionKind.RUN.value, before),
        ).fetchone()
        return str(row[0]) if row else None

    def run_tokens_since(self, since: str) -> int:
        """Tokens of the run sessions created at or after `since` (ISO time)."""
        row = self._db.execute(
            "SELECT COALESCE(SUM(json_extract(data, '$.tokens')), 0) FROM sessions "
            "WHERE kind = ? AND created >= ?",
            (SessionKind.RUN.value, since),
        ).fetchone()
        return int(row[0])
