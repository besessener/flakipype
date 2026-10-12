"""Exit codes and the error lines every headless command shares, always on stderr."""

from collections.abc import Generator
from contextlib import contextmanager

import typer
from rich.console import Console
from rich.text import Text

from flakipype.cli import wiring
from flakipype.github.actions import GitHubApiError

EXIT_INCOMPLETE = 1
EXIT_NOT_READY = 2
_LOGIN_EXPIRED = "The GitHub login is no longer valid. Log in again with `flakipype setup`."


def error_console() -> Console:
    return Console(stderr=True, highlight=False)


def print_error(console: Console, label: str, error: object) -> None:
    """Error text goes in as plain text: a `[/x]` in a gh message must not read as markup."""
    console.print(Text.assemble((f"{label}:", "red"), f" {error}"))


@contextmanager
def command_errors(console: Console) -> Generator[None]:
    """Not ready exits with 2, a GitHub error with 1; each is named on stderr."""
    try:
        yield
    except wiring.NotReadyError as error:
        print_error(console, "Not ready", error)
        raise typer.Exit(EXIT_NOT_READY) from error
    except GitHubApiError as error:
        print_error(console, "GitHub", error)
        if error.is_authentication_problem:
            console.print(_LOGIN_EXPIRED)
        raise typer.Exit(EXIT_INCOMPLETE) from error
