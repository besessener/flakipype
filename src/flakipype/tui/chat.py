"""The chat window: conversation, activity line, input, and the findings sidebar."""

from typing import ClassVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Markdown, Static

from flakipype.investigate.chat import ChatEntry, ChatService, EntryKind, SidebarItem

WELCOME = (
    "Welcome to **flakipype**. Start with `/scan`, ask a question, or type `/help`.\n\n"
    "Everything here only reads: nothing in your repositories changes."
)
_QUIT = frozenset({"/quit", "/exit"})


def entry_widget(entry: ChatEntry) -> Widget:
    classes = f"entry {entry.kind.value}"
    if entry.kind is EntryKind.USER:
        return Static(Text(f"› {entry.text}"), classes=classes)
    if entry.kind is EntryKind.ASSISTANT:
        return Markdown(entry.text, classes=classes)
    # Notes quote scan output such as "<duration>", which Markdown would drop as HTML.
    return Markdown(entry.text.replace("<", "\\<"), classes=classes)


def sidebar_label(item: SidebarItem) -> Text:
    text = Text(f"#{item.number} ", style="bold")
    text.append(item.kind, style="yellow" if item.kind == "flaky" else "dim")
    text.append(f"\n{item.title}")
    if item.verdict:
        text.append(f"\n{item.verdict}", style="cyan")
    return text


class FindingItem(ListItem):
    def __init__(self, item: SidebarItem) -> None:
        super().__init__(Label(sidebar_label(item)))
        self.item = item


class ChatApp(App[None]):
    CSS_PATH = "chat.tcss"
    TITLE = "flakipype"
    BINDINGS: ClassVar[list[BindingType]] = [Binding("ctrl+q", "quit", "Quit")]

    def __init__(self, service: ChatService, subtitle: str) -> None:
        super().__init__()
        self._service = service
        self.sub_title = subtitle

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="chat"):
                yield VerticalScroll(id="conversation")
                yield Static("", id="activity")
                yield Input(placeholder="Ask a question or type /help", id="prompt")
            with Vertical(id="sidebar"):
                yield Static("Findings", id="sidebar-title")
                yield ListView(id="findings")
        yield Footer()

    def on_mount(self) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        # Markdown lays itself out after mounting, so scrolling once would stop short.
        conversation.anchor()
        conversation.mount(entry_widget(ChatEntry(EntryKind.NOTE, WELCOME)))
        conversation.mount_all([entry_widget(entry) for entry in self._service.entries])
        self._refresh_sidebar()
        self.query_one("#prompt", Input).focus()

    @on(Input.Submitted, "#prompt")
    def submit(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        event.input.value = ""
        if line in _QUIT:
            self.exit()
            return
        if not line:
            return
        event.input.disabled = True
        self._show_activity("Thinking…")
        self._handle(line)

    @on(ListView.Selected, "#findings")
    def pick_finding(self, event: ListView.Selected) -> None:
        if not isinstance(event.item, FindingItem):
            return
        prompt = self.query_one("#prompt", Input)
        # Investigating costs tokens, so it is proposed, never started by a click.
        command = "/why" if event.item.item.verdict else "/investigate"
        prompt.value = f"{command} {event.item.item.number}"
        prompt.focus()

    @work(thread=True, exclusive=True)
    def _handle(self, line: str) -> None:
        self._service.workspace.on_activity = self._activity_from_worker
        entries = self._service.handle(
            line, lambda step: self._activity_from_worker(f"Using {step}…")
        )
        self.call_from_thread(self._show_entries, entries)

    def _activity_from_worker(self, text: str) -> None:
        self.call_from_thread(self._show_activity, text or "Thinking…")

    def _show_activity(self, text: str) -> None:
        self.query_one("#activity", Static).update(text)

    def _show_entries(self, entries: list[ChatEntry]) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        if entries and entries[0].kind is not EntryKind.USER:
            # /new and /resume replace the conversation.
            conversation.remove_children()
            conversation.mount_all([entry_widget(entry) for entry in self._service.entries])
        conversation.mount_all([entry_widget(entry) for entry in entries])
        conversation.anchor()
        self._show_activity(f"{self._service.tokens:,} tokens used")
        self._refresh_sidebar()
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = False
        prompt.focus()

    def _refresh_sidebar(self) -> None:
        findings = self.query_one("#findings", ListView)
        findings.clear()
        items = self._service.sidebar()
        if not items:
            findings.append(ListItem(Label(Text("No scan yet. Type /scan.", style="dim"))))
            return
        findings.extend(FindingItem(item) for item in items)
