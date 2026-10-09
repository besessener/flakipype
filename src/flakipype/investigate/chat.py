"""The chat behind the terminal UI: slash commands, questions to the agent, sessions."""

import json
import re
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from flakipype.actions.watch import WatchedRun
from flakipype.agent.orchestrator import ChatAgent, StepListener, ignore_steps
from flakipype.agent.tools import Confirmer, Mode, PolicyGate, ToolDeclinedError, ToolError
from flakipype.agent.verdict import Verdict
from flakipype.flaky.findings import FindingKind
from flakipype.github.actions import GitHubApiError
from flakipype.investigate.chat_text import HELP, finding_title, kind_label
from flakipype.investigate.workspace import ChatWorkspace
from flakipype.scan.service import ScanRequest
from flakipype.store.sessions import SessionStore

_TITLE_LENGTH = 60
_RECENT_SESSIONS = 10
_ALL = "all"
_FRESH = "--fresh"
_ALL_JOBS = "--all"
_REPEATS = re.compile(r"x(\d+)")
_MODES = {
    Mode.ASK: "Mode: ask. Every action asks you first.",
    Mode.AUTO: (
        "Mode: auto. Actions run without asking, within this session's budgets; a fix with "
        "warnings is not pushed, and fixes are always draft pull requests."
    ),
}


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
    def __init__(  # noqa: PLR0913 - collaborators of the chat, all keyword-only
        self,
        *,
        workspace: ChatWorkspace,
        agent: ChatAgent,
        gate: PolicyGate,
        sessions: SessionStore,
        confirmer: Confirmer,
        now: Callable[[], datetime],
    ) -> None:
        self._workspace = workspace
        self._agent = agent
        self._gate = gate
        self._sessions = sessions
        # The window sets confirmer.ask once it can show a dialog.
        self.confirmer = confirmer
        self._now = now
        self._session = _Session()
        # Run notes are saved from the polling thread while a turn may be saving too.
        self._saving = threading.Lock()

    @property
    def workspace(self) -> ChatWorkspace:
        return self._workspace

    @property
    def entries(self) -> list[ChatEntry]:
        return list(self._session.entries)

    @property
    def tokens(self) -> int:
        return self._session.chat_tokens + self._workspace.tokens

    @property
    def mode(self) -> Mode:
        return self._gate.mode

    def handle(self, line: str, on_step: StepListener = ignore_steps) -> list[ChatEntry]:
        """Answer one line of input; the returned entries are also kept in the session."""
        text = line.strip()
        if not text:
            return []
        if text.startswith("/"):
            return self._command(text)
        answer = self._guarded(lambda: self._ask(text, on_step))
        return self._record([ChatEntry(EntryKind.USER, text), answer])

    def poll(self) -> list[ChatEntry]:
        """Reads started runs and verifications once; a note for each one that finished, kept."""
        finished = [*self._workspace.actions.poll(), *self._workspace.fixes.poll()]
        notes = [ChatEntry(EntryKind.NOTE, note) for note in finished]
        if notes:
            self._session.entries.extend(notes)
            if self._session.session_id is not None:
                self._save()
        return notes

    def watched_runs(self) -> list[WatchedRun]:
        return self._workspace.actions.watched

    @property
    def unfinished(self) -> bool:
        """Whether a started run or a fix's verification still needs polling."""
        runs = any(not run.done for run in self._workspace.actions.watched)
        return runs or any(not pull.verified for pull in self._workspace.fixes.pulls)

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
            "/rerun": self._rerun,
            "/dispatch": self._dispatch,
            "/cancel": self._cancel,
            "/runs": lambda _: self._note(self._workspace.watched_runs()),
            "/actions": lambda _: self._note(self._workspace.actions.audit_text()),
            "/fix": self._fix,
            "/mode": self._mode,
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

    def _rerun(self, arguments: list[str]) -> ChatEntry:
        numbers = _numbers(arguments)
        if not numbers:
            return ChatEntry(EntryKind.ERROR, "Which finding? E.g. /rerun 2 or /rerun 2 --all.")
        tool = "rerun_run" if _ALL_JOBS in arguments else "rerun_failed"
        return self._act(tool, {"finding": numbers[0]})

    def _dispatch(self, arguments: list[str]) -> ChatEntry:
        if not arguments or not arguments[0].lstrip("#").isdigit():
            return ChatEntry(
                EntryKind.ERROR, "Which finding? E.g. /dispatch 2 or /dispatch 2 main x3."
            )
        request: dict[str, object] = {"finding": int(arguments[0].lstrip("#"))}
        for argument in arguments[1:]:
            repeats = _REPEATS.fullmatch(argument)
            if repeats:
                request["repeats"] = int(repeats.group(1))
            else:
                request["ref"] = argument
        return self._act("dispatch", request)

    def _cancel(self, arguments: list[str]) -> ChatEntry:
        numbers = _numbers([argument.lstrip("Rr") for argument in arguments])
        if not numbers:
            return ChatEntry(EntryKind.ERROR, "Which run? E.g. /cancel R1 (see /runs).")
        return self._act("cancel", {"run": numbers[0]})

    def _fix(self, arguments: list[str]) -> ChatEntry:
        numbers = _numbers(arguments)
        if not numbers:
            return ChatEntry(EntryKind.ERROR, "Which finding? E.g. /fix 2 or /fix 2 --fresh.")
        if _FRESH in arguments:
            self._workspace.discard_fix(numbers[0])
        return self._act("fix", {"finding": numbers[0]})

    def _mode(self, arguments: list[str]) -> ChatEntry:
        if not arguments:
            return self._note(_MODES[self._gate.mode])
        if arguments[0] not in set(Mode):
            return ChatEntry(EntryKind.ERROR, "Which mode? /mode ask or /mode auto.")
        self._gate.mode = Mode(arguments[0])
        return self._note(_MODES[self._gate.mode])

    def _act(self, tool: str, arguments: dict[str, object]) -> ChatEntry:
        try:
            with self._workspace.actions.commanded():
                return self._note(self._agent.run_tool(tool, arguments))
        except ToolDeclinedError as error:
            return self._note("Not run." if self._gate.mode is Mode.ASK else str(error))
        except ToolError as error:
            return ChatEntry(EntryKind.ERROR, str(error))

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
        with self._saving:
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
            "actions": self._workspace.actions.state(),
            "fix": self._workspace.fixes.state(),
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
        self._workspace.actions.reset()
        self._workspace.fixes.reset()
        self._gate.mode = Mode.ASK

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
        if "actions" in document:
            self._workspace.actions.restore(document["actions"])
        else:
            self._workspace.actions.reset()
        if "fix" in document:
            self._workspace.fixes.restore(document["fix"])
        else:
            self._workspace.fixes.reset()
        self._gate.mode = Mode.ASK
        return ChatEntry(EntryKind.NOTE, f"Resumed session {numbers[0]}. The next action rescans.")


def _numbers(arguments: list[str]) -> list[int]:
    return [int(argument.lstrip("#")) for argument in arguments if argument.lstrip("#").isdigit()]


def _verdict_label(verdict: Verdict | None) -> str:
    if verdict is None:
        return "no verdict"
    return f"{verdict.classification.value.replace('_', ' ')} ({verdict.confidence.value})"
