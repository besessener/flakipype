import typer
from rich.console import Console

from flakipype.cli import wiring
from flakipype.cli.setup_commands import is_interactive_terminal
from flakipype.github.actions import GitHubApiError
from flakipype.tui.chat import ChatApp

EXIT_NOT_READY = 2


def open_chat_window(context: typer.Context) -> None:
    """The chat needs a terminal; without one, show the help like any CLI."""
    if not is_interactive_terminal():
        typer.echo(context.get_help())
        return
    errors = Console(stderr=True, highlight=False)
    try:
        with wiring.open_chat() as (chat, settings):
            ChatApp(chat, f"{settings.github.owner} on {settings.github.host}").run()
    except wiring.NotReadyError as error:
        errors.print(f"[red]Not ready:[/] {error}")
        raise typer.Exit(EXIT_NOT_READY) from error
    except GitHubApiError as error:
        errors.print(f"[red]GitHub:[/] {error}")
        raise typer.Exit(1) from error
