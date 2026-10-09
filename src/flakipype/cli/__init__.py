"""Command line entry point: the chat (TUI) and the headless commands."""

from typing import Annotated

import typer

from flakipype import __version__
from flakipype.cli.investigate_command import investigate
from flakipype.cli.scan_command import scan
from flakipype.cli.setup_commands import doctor, setup

app = typer.Typer(
    name="flakipype",
    help="Find, explain and fix flaky GitHub Actions pipelines.",
    no_args_is_help=True,
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


@app.callback()
def main(
    *,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_print_version,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Find, explain and fix flaky GitHub Actions pipelines."""
