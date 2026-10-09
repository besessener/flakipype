"""Command line entry point: the chat (TUI) and the headless commands."""

from typing import Annotated

import typer

from flakipype import __version__
from flakipype.cli.chat_command import open_chat_window
from flakipype.cli.investigate_command import investigate
from flakipype.cli.scan_command import scan
from flakipype.cli.setup_commands import doctor, setup

app = typer.Typer(
    name="flakipype",
    help="Find, explain and fix flaky GitHub Actions pipelines. Without a command: the chat.",
    add_completion=False,
)
app.command()(setup)
app.command()(doctor)
app.command()(scan)
app.command()(investigate)


def _print_version(requested: bool) -> None:  # noqa: FBT001 - signature dictated by Typer callbacks
    if not requested:
        return
    typer.echo(f"flakipype {__version__}")
    raise typer.Exit


@app.callback(invoke_without_command=True)
def main(
    context: typer.Context,
    *,
    version: Annotated[  # noqa: ARG001 - handled by the eager Typer callback
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_print_version,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Find, explain and fix flaky GitHub Actions pipelines. Without a command: the chat."""
    if context.invoked_subcommand is None:
        open_chat_window(context)
