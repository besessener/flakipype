import json

import pytest

from flakipype.agent.tools import ActionRequest, Confirmer
from flakipype.investigate.chat import ChatEntry, ChatService, EntryKind
from flakipype.store.database import ScanCache

from support.fake_anthropic import ScriptedModel, call, message, text
from support.fake_chat import NOW, chat_service
from support.fake_runs import DISPATCHABLE, E2E, FakeRuns, state


def runs() -> FakeRuns:
    """The world's run 6 (finding #3, lint) failed; finding #2's workflow can be dispatched."""
    return FakeRuns(
        states={6: [state(6, name="CI")]},
        files={(E2E, "3f2a9c1"): DISPATCHABLE},
        dispatch_ids=[70, 71],
    )


def chat_with(
    cache: ScanCache,
    started: FakeRuns,
    *,
    answer: bool = True,
    model: ScriptedModel | None = None,
) -> tuple[ChatService, list[ActionRequest]]:
    asked: list[ActionRequest] = []

    def confirm(request: ActionRequest) -> bool:
        asked.append(request)
        return answer

    confirmer = Confirmer()
    confirmer.ask = confirm
    chat = chat_service(cache, model or ScriptedModel([]), runs=started, confirmer=confirmer)
    return chat, asked


def test_a_confirmed_rerun_command_starts_and_lists_the_run(cache: ScanCache) -> None:
    started = runs()
    chat, asked = chat_with(cache, started)

    (_, note) = chat.handle("/rerun 3")
    (_, listed) = chat.handle("/runs")
    (_, audit) = chat.handle("/actions")

    assert [request.title for request in asked] == ["Rerun failed jobs?"]
    assert note.text.startswith("Started R1: app · CI #6/2.")
    assert "rerun_failed_jobs octo-org/app 6" in started.calls
    assert listed.text.startswith("R1 app · CI #6/2: queued · run 6")
    assert audit.text == (
        "Actions in this session:\n"
        f"- {NOW:%H:%M} `rerun_failed` asked by command, confirmed: {note.text}"
    )
    assert [run.number for run in chat.watched_runs()] == [1]


def test_a_declined_command_runs_nothing(cache: ScanCache) -> None:
    started = FakeRuns(states={6: [state(6, conclusion="success")]})
    chat, _ = chat_with(cache, started, answer=False)

    assert chat.handle("/rerun 3 --all")[1] == ChatEntry(EntryKind.NOTE, "Not run.")
    assert chat.watched_runs() == []


def test_a_repeated_dispatch_is_watched_and_summed_up(cache: ScanCache) -> None:
    started = runs()
    chat, asked = chat_with(cache, started)

    (_, note) = chat.handle("/dispatch #2 main x2")
    assert asked[0].details[1] == "on main at 3f2a9c1 · 2 runs, without inputs"
    assert note.text.startswith("Started R1, R2: E2E on main.")
    started.states[70] = [state(70, conclusion="success")]
    started.states[71] = [state(71, status="in_progress", conclusion=None)]

    assert chat.poll() == [ChatEntry(EntryKind.NOTE, "R1: E2E dispatch 1/2 passed.")]
    started.states[71] = [state(71, conclusion="failure")]
    assert [entry.text for entry in chat.poll()] == [
        "R2: E2E dispatch 2/2 failed.",
        "E2E on 3f2a9c1: 1 of 2 passed.",
    ]
    assert chat.poll() == []
    saved = json.loads(cache.sessions.load(1) or "{}")
    assert saved["entries"][-1]["text"] == "E2E on 3f2a9c1: 1 of 2 passed."
    assert [run["conclusion"] for run in saved["actions"]["runs"]] == ["success", "failure"]


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("/rerun", "Which finding? E.g. /rerun 2 or /rerun 2 --all."),
        ("/dispatch", "Which finding? E.g. /dispatch 2 or /dispatch 2 main x3."),
        ("/dispatch main", "Which finding? E.g. /dispatch 2 or /dispatch 2 main x3."),
        ("/cancel", "Which run? E.g. /cancel R1 (see /runs)."),
        ("/cancel R1", "R1 is not a run started in this session; see watched_runs."),
        ("/rerun 9", "#9: no such finding in the current scan."),
        ("/rerun 1", "Finding #1 has no run that is still failing"),
    ],
)
def test_commands_explain_what_is_missing(cache: ScanCache, line: str, error: str) -> None:
    chat, asked = chat_with(cache, runs())

    (_, reply) = chat.handle(line)

    assert reply.kind is EntryKind.ERROR
    assert reply.text.startswith(error)
    assert asked == []


def test_a_cancel_command(cache: ScanCache) -> None:
    started = runs()
    chat, _ = chat_with(cache, started)
    chat.handle("/dispatch 2")

    (_, note) = chat.handle("/cancel r1")

    assert note.text.startswith("Cancel requested for R1.")
    assert "cancel octo-org/app 70" in started.calls


def test_the_model_asks_through_the_same_dialog(cache: ScanCache) -> None:
    model = ScriptedModel(
        [message(call("t1", "dispatch", {"finding": 2})), message(text("Started R1."))]
    )
    chat, asked = chat_with(cache, runs(), model=model)

    (_, answer) = chat.handle("Run E2E again")

    assert answer.text == "Started R1."
    assert asked[0].title == "Dispatch workflow?"
    assert "asked by model, confirmed" in chat.handle("/actions")[1].text


def test_new_resets_and_resume_restores_the_runs_and_budget(cache: ScanCache) -> None:
    chat, _ = chat_with(cache, runs())
    chat.handle("/rerun 3")
    session = chat.workspace.actions.session

    chat.handle("/new")
    assert (chat.watched_runs(), chat.workspace.actions.used) == ([], 0)
    assert chat.workspace.actions.session != session
    chat.handle("/resume 1")

    assert [run.label for run in chat.watched_runs()] == ["#6/2"]
    assert (chat.workspace.actions.used, chat.workspace.actions.session) == (1, session)


def test_sessions_from_before_actions_resume_with_a_fresh_budget(cache: ScanCache) -> None:
    chat, _ = chat_with(cache, runs())
    chat.handle("/rerun 3")
    document = json.loads(cache.sessions.load(1) or "{}")
    del document["actions"]
    cache.sessions.update(1, now=NOW.isoformat(), data=json.dumps(document))

    chat.handle("/resume 1")

    assert (chat.watched_runs(), chat.workspace.actions.used) == ([], 0)


def test_notes_before_the_first_save_wait_for_it(cache: ScanCache) -> None:
    started = runs()
    first, _ = chat_with(cache, started)
    first.handle("/rerun 3")
    started.states[6] = [state(6, conclusion="success", attempt=2, name="CI")]
    fresh, _ = chat_with(cache, started)
    fresh.workspace.actions.restore(first.workspace.actions.state())

    (note,) = fresh.poll()

    assert note.text.startswith("R1: CI passed on attempt 2")
    assert fresh.entries == [note]
    assert cache.sessions.load(2) is None
