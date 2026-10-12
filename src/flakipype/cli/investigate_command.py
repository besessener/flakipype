import json
from typing import Annotated

import typer
from rich.console import Console

from flakipype.cli import wiring
from flakipype.cli.errors import EXIT_INCOMPLETE, command_errors, error_console
from flakipype.cli.investigation_report import investigation_as_json, render_investigation
from flakipype.cli.scan_command import ProgressView, ScanOptions, progress_display
from flakipype.flaky.findings import FindingKind
from flakipype.investigate.service import InvestigationRequest, Selection


def investigate(  # noqa: PLR0913 - Typer maps every command line option to one parameter
    *,
    finding: Annotated[
        list[str] | None,
        typer.Option(help="Finding number, or its reference from `scan --json`; repeat for more."),
    ] = None,
    all_findings: Annotated[
        bool, typer.Option("--all", help="Every finding, also seen once and fixed.")
    ] = False,
    fresh: Annotated[
        bool, typer.Option("--fresh", help="Investigate again even if a verdict is stored.")
    ] = False,
    days: Annotated[
        int | None, typer.Option(min=1, max=400, help="Days to look back (default: config).")
    ] = None,
    repo: Annotated[
        list[str] | None, typer.Option(help="Only this repository; repeat for more.")
    ] = None,
    owner: Annotated[
        str | None, typer.Option(help="User or organisation (default: config).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the result as JSON.")] = False,
) -> None:
    """Let the agent investigate findings and explain them with evidence.

    Without --finding or --all: the flaky jobs and the recurring errors.
    """
    errors = error_console()
    options = ScanOptions(
        owner=owner, days=days, max_logs=None, min_runs=None, repositories=tuple(repo or ())
    )
    selection = _selection(finding or [])
    if all_findings:
        selection = Selection(kinds=tuple(FindingKind))
    with (
        command_errors(errors),
        wiring.open_investigation() as (service, settings),
        ProgressView(progress_display(errors)) as view,
    ):
        request = InvestigationRequest(options.request(settings), selection, fresh=fresh)
        report = service.run(request, view.update, view.investigation)
    if as_json:
        typer.echo(json.dumps(investigation_as_json(report), indent=2))
    else:
        Console(highlight=False).print(render_investigation(report))
    if not report.complete or not report.scan.complete:
        raise typer.Exit(EXIT_INCOMPLETE)


def _selection(findings: list[str]) -> Selection:
    """Numbers belong to one scan, which this command repeats; references stay valid."""
    numbers = [int(item) for item in findings if item.isascii() and item.isdigit()]
    references = [item.lower() for item in findings if not (item.isascii() and item.isdigit())]
    return Selection(numbers=tuple(numbers), references=tuple(references))
