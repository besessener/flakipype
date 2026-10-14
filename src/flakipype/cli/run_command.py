import json
import signal
from collections.abc import Generator
from contextlib import contextmanager
from types import FrameType
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from flakipype.agent.tools import Mode
from flakipype.cli import wiring
from flakipype.cli.errors import EXIT_INCOMPLETE, command_errors, error_console
from flakipype.cli.run_report import render_run, run_as_json
from flakipype.cli.scan_command import ScanOptions
from flakipype.store.lock import RunLockedError
from flakipype.unattended.service import RunTerminatedError

EXIT_LOCKED = 3


def run(  # noqa: PLR0913 - Typer maps every command line option to one parameter
    *,
    mode: Annotated[
        Mode,
        typer.Option(help="auto: push draft pull requests within the limits; ask: only report."),
    ] = Mode.AUTO,
    days: Annotated[
        int | None, typer.Option(min=1, max=400, help="Days to look back (default: config).")
    ] = None,
    repo: Annotated[
        list[str] | None, typer.Option(help="Only this repository; repeat for more.")
    ] = None,
    owner: Annotated[
        str | None, typer.Option(help="User or organisation (default: config).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the summary as JSON.")] = False,
) -> None:
    """Scan, investigate and fix without a window, e.g. from a timer.

    Opens draft pull requests only, within the per-run and daily limits.
    """
    errors = error_console()
    options = ScanOptions(
        owner=owner, days=days, max_logs=None, min_runs=None, repositories=tuple(repo or ())
    )
    try:
        with command_errors(errors), wiring.open_run(mode, options.request) as service:
            if errors.is_terminal:
                service.show_activity(lambda text: _show(errors, text))
            with _sigterm_ends_the_run():
                report = service.run()
    except RunLockedError as error:
        errors.print(Text.assemble(("Not started:", "yellow"), f" {error}."))
        raise typer.Exit(EXIT_LOCKED) from error
    if as_json:
        typer.echo(json.dumps(run_as_json(report), indent=2))
    else:
        typer.echo(render_run(report))
    if not report.complete:
        raise typer.Exit(EXIT_INCOMPLETE)


@contextmanager
def _sigterm_ends_the_run() -> Generator[None]:
    """Python's default SIGTERM skips every `finally`; the run ends with its summary instead."""
    previous = signal.signal(signal.SIGTERM, _terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _terminate(number: int, frame: FrameType | None) -> None:
    del number, frame
    message = "stopped by SIGTERM before it finished (systemctl stop or the unit's timeout)"
    raise RunTerminatedError(message)


def _show(console: Console, text: str) -> None:
    if text:
        console.print(Text(text, style="dim"))
