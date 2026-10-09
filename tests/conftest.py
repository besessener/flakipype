from collections.abc import Iterator
from pathlib import Path

import pytest

from flakipype.store.database import ScanCache

from support.fake_gh import FakeGh


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
