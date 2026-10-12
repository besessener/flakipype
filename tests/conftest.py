import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from flakipype.store.database import ScanCache

from support.fake_gh import FakeGh


def _set_time_zone(zone: str | None) -> None:
    if zone is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = zone
    time.tzset()


@pytest.fixture(autouse=True)
def utc_time_zone() -> Iterator[None]:
    """Local times in output are UTC in every test, whatever the machine's zone."""
    previous = os.environ.get("TZ")
    _set_time_zone("UTC")
    yield
    _set_time_zone(previous)


@pytest.fixture
def berlin_time_zone() -> None:
    """Autouse fixtures start first, so this replaces the UTC default; its teardown restores."""
    _set_time_zone("Europe/Berlin")


@pytest.fixture
def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeGh:
    fake = FakeGh(scenario_file=tmp_path / "gh-scenario.json", log_file=tmp_path / "gh-log.jsonl")
    fake.scenario_file.write_text('{"calls": []}', encoding="utf-8")
    monkeypatch.setenv("FAKE_GH_SCENARIO", str(fake.scenario_file))
    monkeypatch.setenv("FAKE_GH_LOG", str(fake.log_file))
    return fake


@pytest.fixture
def cache() -> Iterator[ScanCache]:
    """An in-memory scan cache, closed after the test (Python 3.13+ warns about open ones)."""
    with ScanCache.in_memory() as memory:
        yield memory
