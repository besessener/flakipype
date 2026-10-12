import json

import pytest

from flakipype.agent.tools import ActionRequest, Confirmer
from flakipype.github.actions import GitHubApiError
from flakipype.investigate.chat import ChatService, EntryKind
from flakipype.store.database import ScanCache

from support.fake_actions import FakeActions
from support.fake_anthropic import ScriptedModel, call, message, text
from support.fake_chat import chat_service
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
    resumed.handle("Hi")

    assert stored["entries"][-1]["text"].startswith("R1: CI passed on attempt 2")
    assert stored["history"] == []
    assert roles(later, 0) == ["user"]


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
    chat.handle("Logged in again, scan")

    assert answer.kind is EntryKind.ASSISTANT
    assert roles(model, 2) == ["user", "assistant", "user", "assistant", "user"]
    assert chat.tokens == 3 * 1_200
