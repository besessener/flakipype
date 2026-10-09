"""The chat behind the terminal UI: slash commands, questions to the agent, sessions."""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from flakipype.agent.orchestrator import ChatAgent, StepListener, ignore_steps
from flakipype.agent.verdict import Verdict
from flakipype.flaky.findings import FindingKind
from flakipype.github.actions import GitHubApiError
from flakipype.investigate.chat_text import finding_title, kind_label
from flakipype.investigate.workspace import ChatWorkspace
from flakipype.scan.service import ScanRequest
from flakipype.store.sessions import SessionStore

_TITLE_LENGTH = 60
_RECENT_SESSIONS = 10
_ALL = "all"
_FRESH = "--fresh"

HELP = """\
**Commands**

- `/scan [days]` – scan the workflow runs and number the findings
- `/findings` – list the findings of the current scan
- `/investigate N [N …] | all [--fresh]` – let the agent investigate findings
- `/why N` – show the verdict for finding N with its evidence
- `/budget` – tokens used in this session
- `/sessions` – recent sessions · `/resume N` – continue one · `/new` – start over
- `/help` – this list · `/quit` – leave (also Ctrl+Q)

Or just ask, e.g. *why does the E2E test of Archivist fail?*"""


class EntryKind(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    NOTE = "note"
    ERROR = "error"


@dataclass(frozen=True)
class ChatEntry:
    kind: EntryKind
    text: str


@dataclass(frozen=True)
class SidebarItem:
    number: int
    kind: str
    title: str
    verdict: str = ""


@dataclass
class _Session:
    session_id: int | None = None
    entries: list[ChatEntry] = field(default_factory=list)
    snapshot: list[SidebarItem] = field(default_factory=list)
    chat_tokens: int = 0


class ChatService:
    def __init__(
        self,
        *,
        workspace: ChatWorkspace,
        agent: ChatAgent,
        sessions: SessionStore,
        now: Callable[[], datetime],
    ) -> None:
        self._workspace = workspace
        self._agent = agent
        self._sessions = sessions
        self._now = now
        self._session = _Session()

    @property
    def workspace(self) -> ChatWorkspace:
        return self._workspace

    @property
    def entries(self) -> list[ChatEntry]:
        return list(self._session.entries)

    @property
    def tokens(self) -> int:
        return self._session.chat_tokens + self._workspace.tokens

    def handle(self, line: str, on_step: StepListener = ignore_steps) -> list[ChatEntry]:
        """Answer one line of input; the returned entries are also kept in the session."""
        text = line.strip()
        if not text:
            return []
        if text.startswith("/"):
            return self._command(text)
        answer = self._guarded(lambda: self._ask(text, on_step))
        return self._record([ChatEntry(EntryKind.USER, text), answer])

    def sidebar(self) -> list[SidebarItem]:
        findings = self._workspace.finding_list()
        if not findings:
            return list(self._session.snapshot)
        results = self._workspace.results
        return [
            SidebarItem(
                finding.number,
                kind_label(finding.kind),
                finding_title(finding),
                _verdict_label(results[finding.number].verdict)
                if finding.number in results
                else "",
            )
            for finding in findings
        ]

    def _ask(self, text: str, on_step: StepListener) -> ChatEntry:
        reply = self._agent.ask(text, on_step)
        self._session.chat_tokens += reply.tokens
        return ChatEntry(EntryKind.ASSISTANT if reply.completed else EntryKind.ERROR, reply.text)

    def _command(self, text: str) -> list[ChatEntry]:
        name, *arguments = text.split()
        handlers: dict[str, Callable[[list[str]], ChatEntry]] = {
            "/help": lambda _: ChatEntry(EntryKind.NOTE, HELP),
            "/scan": self._scan,
            "/findings": lambda _: self._note(self._workspace.findings()),
            "/flaky": lambda _: self._note(self._workspace.findings()),
            "/investigate": self._investigate,
            "/why": self._why,
            "/budget": lambda _: self._note(f"Tokens used in this session: {self.tokens:,}"),
            "/sessions": lambda _: self._note(self._session_list()),
        }
        if name == "/new":
            self._start_over()
            return [ChatEntry(EntryKind.NOTE, "New session.")]
        if name == "/resume":
            return [self._resume(arguments)]
        handler = handlers.get(name)
        if handler is None:
            reply = ChatEntry(EntryKind.ERROR, f"Unknown command {name}. Type /help.")
        else:
            reply = self._guarded(lambda: handler(arguments))
        return self._record([ChatEntry(EntryKind.USER, text), reply])

    def _note(self, text: str) -> ChatEntry:
        return ChatEntry(EntryKind.NOTE, text)

    def _scan(self, arguments: list[str]) -> ChatEntry:
        days = _numbers(arguments)
        return self._note(self._workspace.scan(days[0] if days else None, ()))

    def _investigate(self, arguments: list[str]) -> ChatEntry:
        if _ALL in arguments:
            self._workspace.findings()
            wanted = {FindingKind.FLAKY, FindingKind.RECURRING}
            numbers = [f.number for f in self._workspace.finding_list() if f.kind in wanted]
        else:
            numbers = _numbers(arguments)
        if not numbers:
            return ChatEntry(
                EntryKind.ERROR, "Which findings? E.g. /investigate 1 3 or /investigate all."
            )
        return self._note(self._workspace.investigate(tuple(numbers), fresh=_FRESH in arguments))

    def _why(self, arguments: list[str]) -> ChatEntry:
        numbers = _numbers(arguments)
        if not numbers:
            return ChatEntry(EntryKind.ERROR, "Which finding? E.g. /why 1.")
        return self._note(self._workspace.verdict(numbers[0]))

    def _guarded(self, action: Callable[[], ChatEntry]) -> ChatEntry:
        try:
            return action()
        except GitHubApiError as error:
            return ChatEntry(EntryKind.ERROR, f"GitHub: {error}")

    def _record(self, new: list[ChatEntry]) -> list[ChatEntry]:
        self._session.entries.extend(new)
        self._save()
        return new

    def _save(self) -> None:
        data = json.dumps(self._document())
        now = self._now().isoformat()
        if self._session.session_id is None:
            first = next(e.text for e in self._session.entries if e.kind is EntryKind.USER)
            self._session.session_id = self._sessions.create(
                first[:_TITLE_LENGTH], now=now, data=data
            )
        else:
            self._sessions.update(self._session.session_id, now=now, data=data)

    def _document(self) -> dict[str, Any]:
        return {
            "entries": [asdict(entry) for entry in self._session.entries],
            "history": self._agent.history,
            "scan": asdict(self._workspace.request),
            "findings": [asdict(item) for item in self.sidebar()],
            "chat_tokens": self._session.chat_tokens,
        }

    def _session_list(self) -> str:
        sessions = self._sessions.recent(_RECENT_SESSIONS)
        if not sessions:
            return "No saved sessions yet."
        lines = [
            f"- `{s.session_id}` {s.title} ({s.updated[:16].replace('T', ' ')})" for s in sessions
        ]
        return "Recent sessions (resume with /resume N):\n" + "\n".join(lines)

    def _start_over(self) -> None:
        self._session = _Session()
        self._agent.restore([])

    def _resume(self, arguments: list[str]) -> ChatEntry:
        numbers = _numbers(arguments)
        stored = self._sessions.load(numbers[0]) if numbers else None
        if stored is None:
            return ChatEntry(EntryKind.ERROR, "No such session. See /sessions.")
        document: dict[str, Any] = json.loads(stored)
        self._session = _Session(
            session_id=numbers[0],
            entries=[ChatEntry(EntryKind(e["kind"]), e["text"]) for e in document["entries"]],
            snapshot=[SidebarItem(**item) for item in document["findings"]],
            chat_tokens=int(document["chat_tokens"]),
        )
        self._agent.restore(document["history"])
        scan = document["scan"]
        self._workspace.request = ScanRequest(
            **{**scan, "repositories": tuple(scan["repositories"])}
        )
        self._workspace.report = None
        self._workspace.results = {}
        return ChatEntry(EntryKind.NOTE, f"Resumed session {numbers[0]}. The next action rescans.")


def _numbers(arguments: list[str]) -> list[int]:
    return [int(argument.lstrip("#")) for argument in arguments if argument.lstrip("#").isdigit()]


def _verdict_label(verdict: Verdict | None) -> str:
    if verdict is None:
        return "no verdict"
    return f"{verdict.classification.value.replace('_', ' ')} ({verdict.confidence.value})"
