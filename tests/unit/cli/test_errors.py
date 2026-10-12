import io

import click
import pytest
import typer
from rich.console import Console

from flakipype.cli import wiring
from flakipype.cli.errors import EXIT_INCOMPLETE, EXIT_NOT_READY, command_errors
from flakipype.github.actions import GitHubApiError


def console() -> tuple[Console, io.StringIO]:
    text = io.StringIO()
    return Console(file=text, highlight=False, width=200), text


@pytest.mark.parametrize(
    ("error", "code", "line"),
    [
        (wiring.NotReadyError("No model configured."), EXIT_NOT_READY, "Not ready: No model"),
        (GitHubApiError("gh: Server Error (HTTP 500)", 500), EXIT_INCOMPLETE, "GitHub: gh: Server"),
    ],
)
def test_errors_become_exit_codes_with_a_line(error: Exception, code: int, line: str) -> None:
    errors, text = console()

    with pytest.raises(typer.Exit) as raised, command_errors(errors):
        raise error

    assert raised.value.exit_code == code
    assert click.unstyle(text.getvalue()).startswith(line)


def test_an_expired_login_says_how_to_log_in_again() -> None:
    errors, text = console()

    with pytest.raises(typer.Exit), command_errors(errors):
        raise GitHubApiError("gh: Bad credentials (HTTP 401)", 401)

    assert "Log in again with `flakipype setup`." in text.getvalue()


def test_error_text_is_not_read_as_markup() -> None:
    errors, text = console()

    with pytest.raises(typer.Exit), command_errors(errors):
        raise GitHubApiError("gh: branch [/x] not found (HTTP 404)", 404)

    assert "branch [/x] not found" in text.getvalue()
