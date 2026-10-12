import sys

import pytest

from flakipype.github import gh
from flakipype.github.actions import api_error
from flakipype.github.gh import GhCli


def _python(code: str) -> GhCli:
    return GhCli([sys.executable, "-c", code], host="github.com")


def test_output_that_is_not_utf8_is_replaced_not_raised() -> None:
    cli = _python("import sys; sys.stdout.buffer.write(b'\\xff\\xfeok')")

    result = cli.run([])

    assert result.succeeded
    assert result.stdout.endswith("ok")
    assert "�" in result.stdout


def test_a_gh_call_that_does_not_answer_in_time_is_a_failed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gh, "_DEFAULT_TIMEOUT_SECONDS", 0.2)
    cli = _python("import time; time.sleep(30)")

    result = cli.run([])

    assert not result.succeeded
    assert "did not answer within" in str(api_error(result))


def test_colour_forced_by_the_environment_is_switched_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    cli = _python("import os; print(os.environ['CLICOLOR_FORCE'], os.environ['NO_COLOR'])")

    assert cli.run([]).stdout.split() == ["0", "1"]
