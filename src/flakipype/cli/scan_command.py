import json
from dataclasses import dataclass
from typing import Annotated, Self

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from flakipype.cli import wiring
from flakipype.cli.scan_report import render_report
from flakipype.config.settings import Settings
from flakipype.github.actions import GitHubApiError
from flakipype.scan import progress
from flakipype.scan.export import report_as_json
from flakipype.scan.service import ScanRequest
from flakipype.setup.doctor import RUN_SETUP

EXIT_INCOMPLETE = 1
EXIT_NOT_READY = 2


@dataclass(frozen=True)
class ScanOptions:
    """Command line options; unset ones fall back to the configuration."""

    owner: str | None
    days: int | None
    max_logs: int | None
    min_runs: int | None
    repositories: tuple[str, ...]

    def request(self, settings: Settings) -> ScanRequest:
        owner = self.owner or settings.github.owner
        if not owner:
            message = f"No owner configured. {RUN_SETUP}"
            raise wiring.NotReadyError(message)
        return ScanRequest(
            owner=owner,
            host=settings.github.host,
            window_days=self.days or settings.scan.window_days,
            max_log_downloads=(
                settings.scan.max_log_downloads if self.max_logs is None else self.max_logs
            ),
            min_flaky_runs=self.min_runs or settings.scan.min_flaky_runs,
            repositories=self.repositories,
        )


def progress_display(console: Console) -> Progress:
    """Live progress on stderr, so stdout stays clean for --json; hidden without a terminal."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("[dim]{task.fields[detail]}"),
        console=console,
        transient=True,
        disable=not console.is_terminal,
    )


class ProgressView:
    """Shows the scan's progress events in one Rich progress task."""

    def __init__(self, display: Progress) -> None:
        self._progress = display
        self._task = self._progress.add_task("Starting", total=None, detail="")

    def __enter__(self) -> Self:
        self._progress.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._progress.stop()

    def update(self, event: progress.Progress) -> None:
        self._progress.update(
            self._task,
            description=event.stage.value,
            completed=event.done,
            total=event.total,
            detail=event.detail,
        )


def scan(  # noqa: PLR0913 - Typer maps every command line option to one parameter
    *,
    days: Annotated[
        int | None, typer.Option(min=1, max=400, help="Days to look back (default: config).")
    ] = None,
    repo: Annotated[
        list[str] | None, typer.Option(help="Only this repository; repeat for more.")
    ] = None,
    owner: Annotated[
        str | None, typer.Option(help="User or organisation (default: config).")
    ] = None,
    max_logs: Annotated[
        int | None, typer.Option(min=0, max=1000, help="Most logs to download (default: config).")
    ] = None,
    min_runs: Annotated[
        int | None,
        typer.Option(min=1, max=100, help="Runs needed to call a job flaky (default: config)."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the result as JSON.")] = False,
) -> None:
    """Find flaky workflows, jobs and steps in the owner's GitHub Actions runs."""
    output = Console(highlight=False)
    errors = Console(stderr=True, highlight=False)
    options = ScanOptions(
        owner=owner,
        days=days,
        max_logs=max_logs,
        min_runs=min_runs,
        repositories=tuple(repo or ()),
    )
    try:
        with (
            wiring.open_scan() as (service, settings),
            ProgressView(progress_display(errors)) as view,
        ):
            report = service.scan(options.request(settings), view.update)
    except wiring.NotReadyError as error:
        errors.print(f"[red]Not ready:[/] {error}")
        raise typer.Exit(EXIT_NOT_READY) from error
    except GitHubApiError as error:
        errors.print(f"[red]GitHub:[/] {error}")
        if error.is_authentication_problem:
            errors.print(
                "The GitHub login is no longer valid. Log in again with `flakipype setup`."
            )
        raise typer.Exit(EXIT_INCOMPLETE) from error
    if as_json:
        typer.echo(json.dumps(report_as_json(report), indent=2))
    else:
        output.print(render_report(report, now=report.window.end))
    if not report.complete:
        raise typer.Exit(EXIT_INCOMPLETE)
