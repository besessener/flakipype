from typing import Annotated

import typer
from rich.console import Console

from flakipype.agent.tools import Mode
from flakipype.cli import wiring
from flakipype.setup.daemon import DaemonError, render_units

EXIT_FAILED = 1
EXIT_NOT_READY = 2

daemon = typer.Typer(
    name="daemon",
    help="Run `flakipype run` from a systemd user timer.",
    add_completion=False,
    no_args_is_help=True,
)


def _console() -> Console:
    return Console(highlight=False)


@daemon.command()
def install(
    *,
    schedule: Annotated[
        str, typer.Option(help="systemd calendar expression, e.g. daily or Mon..Fri 06:00.")
    ] = "daily",
    mode: Annotated[Mode, typer.Option(help="The mode the timer runs in.")] = Mode.AUTO,
    print_only: Annotated[
        bool, typer.Option("--print", help="Print the unit files and change nothing.")
    ] = False,
) -> None:
    """Check flakipype in the timer's environment, then install and start the timer."""
    console = _console()
    try:
        options = wiring.unit_options(schedule, mode)
        if print_only:
            for name, text in render_units(options).items():
                typer.echo(f"# --- {name}\n{text}")
            return
        service = wiring.build_daemon()
        warnings = service.install(options)
    except wiring.NotReadyError as error:
        console.print(f"[red]Not ready:[/] {error}")
        raise typer.Exit(EXIT_NOT_READY) from error
    except DaemonError as error:
        console.print(f"[red]Not installed:[/] {error}")
        raise typer.Exit(EXIT_FAILED) from error
    console.print(f"Installed and started flakipype.timer ({schedule}) in {service.unit_dir}.")
    for warning in warnings:
        console.print(f"[yellow]Note:[/] {warning}")


@daemon.command()
def uninstall() -> None:
    """Stop the timer and remove the unit files flakipype wrote."""
    console = _console()
    try:
        removed = wiring.build_daemon().uninstall()
    except DaemonError as error:
        console.print(f"[red]Not removed:[/] {error}")
        raise typer.Exit(EXIT_FAILED) from error
    console.print(f"Removed {', '.join(removed)}." if removed else "Nothing to remove.")


@daemon.command()
def status() -> None:
    """The timer's next and last start and the last run's summary."""
    typer.echo(wiring.build_daemon().status())
