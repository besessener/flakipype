from pathlib import Path

import pytest

from flakipype.store.lock import RunLockedError, run_lock


def test_one_run_at_a_time_and_the_lock_is_released(tmp_path: Path) -> None:
    path = tmp_path / "data" / "run.lock"

    with run_lock(path):
        with pytest.raises(RunLockedError, match="another flakipype run holds"), run_lock(path):
            pass
        held = True

    with run_lock(path):
        released = True

    assert held
    assert released


def test_the_lock_is_released_when_the_run_fails(tmp_path: Path) -> None:
    path = tmp_path / "run.lock"

    with pytest.raises(ValueError, match="boom"), run_lock(path):
        raise ValueError("boom")

    with run_lock(path):
        pass
