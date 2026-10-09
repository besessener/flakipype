"""The dialog that confirms an action; its text comes from code, never from the model."""

from typing import ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from flakipype.agent.tools import ActionRequest


class ConfirmScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    #dialog {
        width: 76;
        height: auto;
        border: round $warning;
        padding: 0 1;
        background: $surface;
    }
    #dialog-title {
        text-style: bold;
        color: $warning;
    }
    #dialog-details {
        margin: 1 0;
    }
    #dialog-buttons {
        height: auto;
        align-horizontal: center;
    }
    #dialog-buttons Button {
        margin: 0 1;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "decline", "Don't run")]

    def __init__(self, request: ActionRequest) -> None:
        super().__init__()
        self._request = request

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(Text(self._request.title), id="dialog-title")
            # Names of repositories, workflows and refs are shown as they are, never as markup.
            yield Static(Text("\n".join(self._request.details)), id="dialog-details")
            with Horizontal(id="dialog-buttons"):
                yield Button("Run", variant="warning", id="run")
                yield Button("Don't run", variant="primary", id="decline")

    def on_mount(self) -> None:
        self.query_one("#decline", Button).focus()

    @on(Button.Pressed, "#run")
    def confirm(self) -> None:
        self.dismiss(result=True)

    @on(Button.Pressed, "#decline")
    def action_decline(self) -> None:
        self.dismiss(result=False)
