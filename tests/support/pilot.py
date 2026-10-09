"""Pilot helpers for the chat window: wait for workers, and for a confirmation dialog."""

from textual.pilot import Pilot
from textual.widgets import Input

from flakipype.tui.confirm import ConfirmScreen


async def settle(pilot: Pilot[None]) -> None:
    await pilot.pause()
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def ask(pilot: Pilot[None], line: str) -> ConfirmScreen:
    """Sends a line that needs confirmation and waits for the dialog."""
    prompt = pilot.app.query_one("#prompt", Input)
    prompt.cursor_blink = False
    prompt.value = line
    prompt.focus()
    await pilot.press("enter")
    # A click before the dialog is laid out misses its buttons and the worker waits forever.
    while not (
        isinstance(pilot.app.screen, ConfirmScreen)
        and pilot.app.screen.query("#run")
        and pilot.app.screen.query_one("#run").region
    ):
        await pilot.pause(0.05)
    return pilot.app.screen
