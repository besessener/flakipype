import json
from dataclasses import replace

import pytest

from flakipype.agent.tools import ActionRequest, Confirmer
from flakipype.github.actions import GitHubApiError
from flakipype.investigate.chat import ChatEntry, ChatService, EntryKind
from flakipype.store.database import ScanCache

from support.fake_actions import FakeActions
from support.fake_anthropic import ScriptedModel, call, message, text, thinking
from support.fake_chat import chat_service
from support.fake_investigation import SCAN
from support.fake_runs import DISPATCHABLE, E2E, FakeRuns, state


def runs() -> FakeRuns:
    """The world's run 6 (finding #3, lint) failed; finding #2's workflow can be dispatched."""
    return FakeRuns(
        states={6: [state(6, name="CI")]},
        files={(E2E, "3f2a9c1"): DISPATCHABLE},
        dispatch_ids=[70],
    )


def roles(model: ScriptedModel, request_index: int) -> list[str]:
    return [entry["role"] for entry in model.requests[request_index]["messages"]]


def answered(entries: list[ChatEntry]) -> tuple[EntryKind, str]:
    return entries[-1].kind, entries[-1].text


def test_a_save_during_a_turn_stores_only_finished_turns(cache: ScanCache) -> None:
    started = runs()
    model = ScriptedModel([message(call("t1", "dispatch", {"finding": 2}))])
    confirmer = Confirmer()
    confirmer.ask = lambda _: True
    chat = chat_service(cache, model, runs=started, confirmer=confirmer)
    chat.handle("/rerun 3")
    started.states[6] = [state(6, conclusion="success", attempt=2, name="CI")]

    def poll_while_asking(request: ActionRequest) -> bool:
        del request
        chat.poll()
        # The terminal closes here: the turn never finishes.
        raise SystemExit

    confirmer.ask = poll_while_asking
    with pytest.raises(SystemExit):
        chat.handle("Dispatch E2E to check it")
    stored = json.loads(cache.sessions.load(1) or "{}")
    later = ScriptedModel([message(text("Hello."))])
    resumed = chat_service(cache, later, runs=runs())
    resumed.handle("/resume 1")
    follow_up = resumed.handle("Hi")

    assert stored["entries"][-1]["text"].startswith("R1: CI passed on attempt 2")
    assert stored["history"] == []
    assert roles(later, 0) == ["user"]
    assert answered(follow_up) == (EntryKind.ASSISTANT, "Hello.")


def test_a_github_failure_during_a_question_leaves_the_session_usable(cache: ScanCache) -> None:
    broken = FakeActions(repositories_error=GitHubApiError("gh: HTTP 401: Bad credentials", 401))
    model = ScriptedModel(
        [
            message(call("t1", "scan", {})),
            message(text("GitHub rejected the login.")),
            message(text("Scanned.")),
        ]
    )
    chat: ChatService = chat_service(cache, model, actions=broken)

    (_, answer) = chat.handle("Scan my repositories")
    follow_up = chat.handle("Logged in again, scan")

    assert answer.kind is EntryKind.ASSISTANT
    assert answered(follow_up) == (EntryKind.ASSISTANT, "Scanned.")
    assert roles(model, 2) == ["user", "assistant", "user", "assistant", "user"]
    assert chat.tokens == 3 * 1_200


def test_an_empty_answer_leaves_the_session_usable(cache: ScanCache) -> None:
    model = ScriptedModel([message(), message(text("Hello."))])
    chat = chat_service(cache, model)

    (_, answer) = chat.handle("What does zizmor report?")
    follow_up = chat.handle("Hi")

    assert answered(follow_up) == (EntryKind.ASSISTANT, "Hello.")
    assert answer.kind is EntryKind.ERROR
    assert roles(model, 1) == ["user"]


def test_new_and_resume_count_only_the_sessions_own_tokens(cache: ScanCache) -> None:
    chat = chat_service(cache, ScriptedModel([]))
    chat.handle("/investigate 1")
    assert chat.tokens == 1_000

    chat.handle("/new")
    assert chat.tokens == 0
    chat.handle("/help")
    later = chat_service(cache, ScriptedModel([]))
    later.handle("/resume 1")

    assert later.tokens == 1_000
    assert (later.handle("/resume 2")[0].kind, later.tokens) == (EntryKind.NOTE, 0)


def test_an_empty_selection_and_new_scan_every_repository_again(cache: ScanCache) -> None:
    model = ScriptedModel(
        [
            message(call("t1", "scan", {"days": 90, "repositories": ["app"]})),
            message(text("Scanned app.")),
            message(call("t2", "scan", {"repositories": []})),
            message(text("Scanned all.")),
        ]
    )
    chat = chat_service(cache, model)

    chat.handle("Scan only app over 90 days")
    assert chat.workspace.request.repositories == ("app",)
    chat.handle("Now scan all repositories")
    assert chat.workspace.request.repositories == ()
    chat.workspace.scan(None, ("app",))
    chat.handle("/new")

    assert chat.workspace.request == SCAN


def test_resume_keeps_the_configured_owner_and_host(cache: ScanCache) -> None:
    chat = chat_service(cache, ScriptedModel([]))
    chat.handle("/scan 7")
    document = json.loads(cache.sessions.load(1) or "{}")
    document["scan"] |= {"owner": "other-org", "host": "ghe.example.com"}
    cache.sessions.update(1, now="2026-10-09T08:00:00", data=json.dumps(document), tokens=0)

    (note,) = chat.handle("/resume 1")

    assert note.text == (
        "Resumed session 1. The next action rescans. It was saved for other-org on "
        "ghe.example.com; this chat stays on octo-org on github.com."
    )
    assert chat.workspace.request == replace(SCAN, window_days=7)
    chat.handle("/new")
    assert chat.workspace.request == SCAN


@pytest.mark.parametrize(("changed", "kept"), [(False, True), (True, False)])
def test_resume_after_an_upgrade_drops_the_thinking(
    cache: ScanCache, *, changed: bool, kept: bool
) -> None:
    first = ScriptedModel([message(thinking("Reasoning."), text("Hello."))])
    chat_service(cache, first).handle("Hi")
    if changed:
        document = json.loads(cache.sessions.load(1) or "{}")
        document["fingerprint"] = "an older prompt"
        cache.sessions.update(1, now="2026-10-09T08:00:00", data=json.dumps(document), tokens=0)
    later = ScriptedModel([message(text("Welcome back."))])
    resumed = chat_service(cache, later)

    resumed.handle("/resume 1")
    resumed.handle("Again")

    sent = later.requests[0]["messages"][1]["content"]
    assert [block["type"] for block in sent] == (["thinking", "text"] if kept else ["text"])
