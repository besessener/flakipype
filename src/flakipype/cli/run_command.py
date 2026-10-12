import json
from typing import Annotated

import typer
from rich.console import Console

from flakipype.agent.tools import Mode
from flakipype.cli import wiring
from flakipype.cli.run_report import render_run, run_as_json
from flakipype.cli.scan_command import ScanOptions
from flakipype.github.actions import GitHubApiError
from flakipype.store.lock import RunLockedError

EXIT_INCOMPLETE = 1
EXIT_NOT_READY = 2
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
    errors = Console(stderr=True, highlight=False)
    options = ScanOptions(
        owner=owner, days=days, max_logs=None, min_runs=None, repositories=tuple(repo or ())
    )
    try:
        with wiring.open_run(mode, options.request) as service:
            if errors.is_terminal:
                service.show_activity(lambda text: _show(errors, text))
            report = service.run()
    except RunLockedError as error:
        errors.print(f"[yellow]Not started:[/] {error}.")
        raise typer.Exit(EXIT_LOCKED) from error
    except wiring.NotReadyError as error:
        errors.print(f"[red]Not ready:[/] {error}")
        raise typer.Exit(EXIT_NOT_READY) from error
    except GitHubApiError as error:
        errors.print(f"[red]GitHub:[/] {error}")
        raise typer.Exit(EXIT_INCOMPLETE) from error
    if as_json:
        typer.echo(json.dumps(run_as_json(report), indent=2))
    else:
        typer.echo(render_run(report))
    if not report.complete:
        raise typer.Exit(EXIT_INCOMPLETE)


def _show(console: Console, text: str) -> None:
    if text:
        console.print(f"[dim]{text}[/]")
