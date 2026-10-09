"""The dialog that confirms an action; its text comes from code, never from the model."""

from typing import ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from flakipype.agent.tools import ActionRequest

_RULE_WIDTH = 70
_DIFF_STYLES = {"+": "green", "-": "red", "@": "cyan"}


def _rule(label: str) -> Text:
    return Text(f"── {label} ".ljust(_RULE_WIDTH, "─"))


def diff_text(diff: str) -> Text:
    """The diff as plain text, coloured by line; its content is never read as markup."""
    text = Text()
    for line in diff.splitlines():
        if text:
            text.append("\n")
        header = line.startswith(("+++", "---"))
        text.append(line, style="bold" if header else _DIFF_STYLES.get(line[:1], ""))
    return text


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
    #dialog-change {
        height: auto;
        max-height: 20;
        margin-bottom: 1;
    }
    .dialog-rule {
        color: $text-muted;
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
        request = self._request
        with Vertical(id="dialog"):
            yield Static(Text(request.title), id="dialog-title")
            # Names of repositories, workflows and refs are shown as they are, never as markup.
            yield Static(Text("\n".join(request.details)), id="dialog-details")
            if request.model_text or request.diff:
                with VerticalScroll(id="dialog-change"):
                    if request.model_text:
                        yield Static(_rule("written by the model"), classes="dialog-rule")
                        yield Static(Text(request.model_text), id="dialog-model-text")
                    if request.diff:
                        yield Static(_rule("diff"), classes="dialog-rule")
                        yield Static(diff_text(request.diff), id="dialog-diff")
            with Horizontal(id="dialog-buttons"):
                yield Button(request.confirm_label, variant="warning", id="run")
                yield Button(request.decline_label, variant="primary", id="decline")

    def on_mount(self) -> None:
        self.query_one("#decline", Button).focus()

    @on(Button.Pressed, "#run")
    def confirm(self) -> None:
        self.dismiss(result=True)

    @on(Button.Pressed, "#decline")
    def action_decline(self) -> None:
        self.dismiss(result=False)
