import sys
from typing import Annotated

import typer
from rich.console import Console

from flakipype.cli import wiring
from flakipype.cli.report import print_checks
from flakipype.github.binary import GhInstallError
from flakipype.setup.doctor import run_checks
from flakipype.setup.service import InvalidSetupError, SetupDraft, SetupService
from flakipype.tui.setup_wizard import SetupWizard

EXIT_CHECKS_FAILED = 1
EXIT_USAGE = 2


def _console() -> Console:
    return Console(highlight=False)


def is_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def setup(  # noqa: PLR0913 - Typer maps every command line option to one parameter
    *,
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive", help="No wizard: take values from the options."),
    ] = False,
    base_url: Annotated[str | None, typer.Option(help="Anthropic Messages API base URL.")] = None,
    model: Annotated[str | None, typer.Option(help="Model, or deployment name on Foundry.")] = None,
    host: Annotated[str | None, typer.Option(help="GitHub host, e.g. github.com.")] = None,
    owner: Annotated[str | None, typer.Option(help="GitHub user or organisation to scan.")] = None,
    api_key_stdin: Annotated[
        bool,
        typer.Option("--api-key-stdin", help="Read the API key from standard input."),
    ] = False,
) -> None:
    """Connect flakipype to a model endpoint and GitHub."""
    service = wiring.build_setup_service()
    if not non_interactive:
        _run_wizard(service)
        return
    state = service.load()
    draft = SetupDraft(
        base_url=base_url or state.settings.llm.base_url,
        model=model or state.settings.llm.model,
        host=host or state.settings.github.host,
        owner=owner or state.settings.github.owner,
        api_key=sys.stdin.read().strip() if api_key_stdin else "",
    )
    _run_headless(service, draft)


def _run_wizard(service: SetupService) -> None:
    if not is_interactive_terminal():
        _console().print(
            "[red]No terminal attached.[/] Use [bold]--non-interactive[/] with options."
        )
        raise typer.Exit(EXIT_USAGE)
    if not SetupWizard(service).run():
        _console().print("Setup cancelled, nothing saved.")
        raise typer.Exit(EXIT_CHECKS_FAILED)
    _report(service)


def _run_headless(service: SetupService, draft: SetupDraft) -> None:
    console = _console()
    try:
        service.save(draft)
    except InvalidSetupError as error:
        console.print(f"[red]Cannot save:[/] {error}")
        raise typer.Exit(EXIT_USAGE) from error
    console.print(f"Saved {service.paths.config_file}")
    try:
        service.install_gh()
    except GhInstallError as error:
        console.print(f"[red]gh:[/] {error}")
    _report(service)


def _report(service: SetupService) -> None:
    if not print_checks(_console(), run_checks(service)):
        raise typer.Exit(EXIT_CHECKS_FAILED)


def doctor() -> None:
    """Check configuration, model connection, gh and the GitHub login."""
    _report(wiring.build_setup_service())
