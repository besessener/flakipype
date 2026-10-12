import json
from dataclasses import dataclass
from typing import Annotated, Self

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from flakipype.cli import wiring
from flakipype.cli.errors import EXIT_INCOMPLETE, command_errors, error_console
from flakipype.cli.scan_report import render_report
from flakipype.config.settings import MAX_WINDOW_DAYS, Settings
from flakipype.investigate.service import EventKind, InvestigationEvent
from flakipype.scan import progress
from flakipype.scan.export import report_as_json
from flakipype.scan.service import ScanRequest
from flakipype.setup.doctor import RUN_SETUP


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
            max_job_reads=settings.scan.max_job_reads,
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

    def investigation(self, event: InvestigationEvent) -> None:
        detail = f"#{event.finding.number} {event.finding.key.repository} › {event.finding.key.job}"
        if event.kind is EventKind.STARTED:
            self._progress.update(
                self._task, description="Investigating", total=event.total, detail=detail
            )
            return
        self._progress.update(self._task, completed=event.done, total=event.total)

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
        int | None,
        typer.Option(min=1, max=MAX_WINDOW_DAYS, help="Days to look back (default: config)."),
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
    errors = error_console()
    options = ScanOptions(
        owner=owner,
        days=days,
        max_logs=max_logs,
        min_runs=min_runs,
        repositories=tuple(repo or ()),
    )
    with (
        command_errors(errors),
        wiring.open_scan() as (service, settings),
        ProgressView(progress_display(errors)) as view,
    ):
        report = service.scan(options.request(settings), view.update)
    if as_json:
        typer.echo(json.dumps(report_as_json(report), indent=2))
    else:
        output.print(render_report(report, now=report.window.end))
    if not report.complete:
        raise typer.Exit(EXIT_INCOMPLETE)
