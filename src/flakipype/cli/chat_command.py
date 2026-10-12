import typer

from flakipype.cli import wiring
from flakipype.cli.errors import command_errors, error_console
from flakipype.cli.setup_commands import is_interactive_terminal
from flakipype.tui.chat import ChatApp


def open_chat_window(context: typer.Context) -> None:
    """The chat needs a terminal; without one, show the help like any CLI."""
    if not is_interactive_terminal():
        typer.echo(context.get_help())
        return
    with command_errors(error_console()), wiring.open_chat() as (chat, settings):
        app = ChatApp(chat, f"{settings.github.owner} on {settings.github.host}")
        app.run()
    # A crash in a chat worker closes the app with return code 1; it must not end as success.
    if app.return_code:
        raise typer.Exit(app.return_code)
