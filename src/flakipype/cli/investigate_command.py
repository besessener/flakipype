import json
from typing import Annotated

import typer
from rich.console import Console

from flakipype.cli import wiring
from flakipype.cli.investigation_report import investigation_as_json, render_investigation
from flakipype.cli.scan_command import ProgressView, ScanOptions, progress_display
from flakipype.flaky.findings import FindingKind
from flakipype.github.actions import GitHubApiError
from flakipype.investigate.service import InvestigationRequest, Selection

EXIT_INCOMPLETE = 1
EXIT_NOT_READY = 2


def investigate(  # noqa: PLR0913 - Typer maps every command line option to one parameter
    *,
    finding: Annotated[
        list[int] | None,
        typer.Option(min=1, help="Finding number from `flakipype scan`; repeat for more."),
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
    errors = Console(stderr=True, highlight=False)
    options = ScanOptions(
        owner=owner, days=days, max_logs=None, min_runs=None, repositories=tuple(repo or ())
    )
    selection = Selection(numbers=tuple(finding or ()))
    if all_findings:
        selection = Selection(kinds=tuple(FindingKind))
    try:
        with (
            wiring.open_investigation() as (service, settings),
            ProgressView(progress_display(errors)) as view,
        ):
            request = InvestigationRequest(options.request(settings), selection, fresh=fresh)
            report = service.run(request, view.update, view.investigation)
    except wiring.NotReadyError as error:
        errors.print(f"[red]Not ready:[/] {error}")
        raise typer.Exit(EXIT_NOT_READY) from error
    except GitHubApiError as error:
        errors.print(f"[red]GitHub:[/] {error}")
        raise typer.Exit(EXIT_INCOMPLETE) from error
    if as_json:
        typer.echo(json.dumps(investigation_as_json(report), indent=2))
    else:
        Console(highlight=False).print(render_investigation(report))
    if not report.complete or not report.scan.complete:
        raise typer.Exit(EXIT_INCOMPLETE)
