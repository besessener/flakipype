"""One `flakipype run` at a time, through SQLite's file lock: the OS releases it if a run dies."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class RunLockedError(Exception):
    """Another process holds the run lock."""


@contextmanager
def run_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=0, isolation_level=None)
    try:
        try:
            connection.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as error:
            message = f"another flakipype run holds {path}"
            raise RunLockedError(message) from error
        try:
            yield
        finally:
            connection.execute("ROLLBACK")
    finally:
        connection.close()
