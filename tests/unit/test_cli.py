import runpy
import sys

import click
import pytest
from typer.testing import CliRunner

from flakipype import __version__
from flakipype.cli import app

runner = CliRunner()


def test_version_option_prints_the_installed_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == f"flakipype {__version__}\n"


def test_without_arguments_shows_help() -> None:
    result = runner.invoke(app, [])

    # Rich forces colours on CI (GITHUB_ACTIONS), which splits words with ANSI codes.
    help_text = click.unstyle(result.output)
    assert "Find, explain and fix flaky GitHub Actions pipelines." in help_text
    assert "--version" in help_text


def test_unknown_command_is_a_usage_error() -> None:
    result = runner.invoke(app, ["no-such-command"])

    assert result.exit_code == 2
    assert "No such command" in result.output


def test_runs_as_python_module(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["flakipype", "--version"])

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("flakipype", run_name="__main__")

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"flakipype {__version__}\n"
