import json

import pytest

from flakipype.agent.investigator import Status
from flakipype.agent.tools import ActionRequest, Confirmer, Mode
from flakipype.agent.workcopy import FileChange
from flakipype.config.settings import FixSettings
from flakipype.github.runs import CommitRun
from flakipype.investigate.chat import ChatService, EntryKind
from flakipype.store.database import ScanCache

from support.fake_anthropic import ScriptedModel, call, message, text
from support.fake_chat import NOW, FixFakes, chat_service
from support.fake_fix import CHANGE, FIX_COMMIT, FakeFixer, fixed, no_fix
from support.fake_investigation import FakeAgent
from support.fake_runs import FakeRuns, state

CI = ".github/workflows/ci.yml"
WARNED = (CHANGE, FileChange(CI, "on: push\njobs: {}\n", "on: [push]\njobs: {}\n"))


def chat_with(
    cache: ScanCache,
    fakes: FixFakes | None = None,
    *,
    answer: bool = True,
    runs: FakeRuns | None = None,
    model: ScriptedModel | None = None,
    agent: FakeAgent | None = None,
) -> tuple[ChatService, list[ActionRequest]]:
    asked: list[ActionRequest] = []

    def confirm(request: ActionRequest) -> bool:
        asked.append(request)
        return answer

    confirmer = Confirmer()
    confirmer.ask = confirm
    chat = chat_service(
        cache, model or ScriptedModel([]), agent=agent, runs=runs, fixes=fakes or FixFakes(),
        confirmer=confirmer,
    )  # fmt: skip
    return chat, asked


def test_a_confirmed_fix_opens_a_draft_pull_request(cache: ScanCache) -> None:
    fakes = FixFakes()
    chat, asked = chat_with(cache, fakes)

    (_, note) = chat.handle("/fix 1")
    (_, audit) = chat.handle("/actions")

    (request,) = asked
    assert request.title == "Push fix and open a draft pull request?"
    assert request.details[0] == "octo-org/app · base main @ 3f2a9c1"
    assert note.kind is EntryKind.NOTE
    assert note.text.startswith("Opened draft pull request #12: https://github.com/octo-org/app/")
    assert "cannot verify automatically" in note.text
    assert fakes.github.drafts[0].head.startswith("flakipype/fix-ci-")
    assert f"`fix` asked by command, confirmed: {note.text}" in audit.text
    assert chat.tokens == 2_000


def test_a_declined_fix_is_kept_until_fresh(cache: ScanCache) -> None:
    fakes = FixFakes()
    chat, asked = chat_with(cache, fakes, answer=False)

    assert chat.handle("/fix 1")[1].text == "Not run."
    chat.handle("/fix #1")
    chat.handle("/fix 1 --fresh")

    assert len(asked) == 3
    assert len(fakes.fixer.requests) == 2
    assert fakes.github.drafts == []


def test_a_finding_without_a_verdict_is_not_fixed(cache: ScanCache) -> None:
    chat, asked = chat_with(cache, agent=FakeAgent(status=Status.NO_VERDICT))

    (_, reply) = chat.handle("/fix 1")

    assert reply == reply.__class__(
        EntryKind.ERROR, "#1 has no verdict (the investigation ended); a fix needs one."
    )
    assert asked == []


def test_tokens_of_a_fix_count_even_without_a_fix(cache: ScanCache) -> None:
    chat, _ = chat_with(cache, FixFakes(fixer=FakeFixer([no_fix("The fixer stopped.")])))

    (_, reply) = chat.handle("/fix 1")

    assert reply.text == "No fix for #1: The fixer stopped."
    assert chat.tokens == 1_005


def test_the_mode_switches_and_auto_runs_without_a_dialog(cache: ScanCache) -> None:
    fakes = FixFakes()
    chat, asked = chat_with(cache, fakes)

    assert chat.handle("/mode")[1].text == "Mode: ask. Every action asks you first."
    (_, switched) = chat.handle("/mode auto")
    (_, note) = chat.handle("/fix 1")

    assert chat.mode is Mode.AUTO
    assert switched.text.startswith("Mode: auto. Actions run without asking")
    assert asked == []
    assert note.text.startswith("Opened draft pull request #12")
    assert "`fix` asked by command, auto:" in chat.handle("/actions")[1].text


def test_auto_mode_does_not_push_a_fix_with_warnings(cache: ScanCache) -> None:
    fakes = FixFakes(fixer=FakeFixer([fixed(WARNED)]))
    chat, asked = chat_with(cache, fakes)
    chat.handle("/mode auto")

    (_, note) = chat.handle("/fix 1")
    chat.handle("/mode ask")
    chat.handle("/fix 1")

    assert note.text == (
        "fix: not run in auto mode because the diff has warnings. "
        "The user can review it after switching to /mode ask."
    )
    assert "`fix` asked by command, not run in auto mode: not pushed" in (
        chat.handle("/actions")[1].text
    )
    (request,) = asked
    assert request.details[-1] == f"⚠ changes .github/: {CI}"
    assert len(fakes.fixer.requests) == 1


def test_the_model_asks_for_changes_through_the_fix_tool(cache: ScanCache) -> None:
    fakes = FixFakes()
    model = ScriptedModel(
        [
            message(call("t1", "fix", {"finding": 1, "instructions": "Keep the assertion."})),
            message(text("Opened it.")),
        ]
    )
    chat, asked = chat_with(cache, fakes, model=model)

    (_, answer) = chat.handle("Fix the CI test, but keep the assertion")

    assert answer.text == "Opened it."
    assert asked[0].confirm_label == "Push"
    assert fakes.fixer.requests[0].instructions == "Keep the assertion."
    assert "`fix` asked by model, confirmed" in chat.handle("/actions")[1].text


def test_verification_notes_come_with_the_run_notes(cache: ScanCache) -> None:
    fakes = FixFakes(settings=FixSettings(verify_runs=1))
    fakes.github.files[CI] = b"on: pull_request\njobs: {}\n"
    runs = FakeRuns(states={91: [state(91, name="CI", conclusion="success")]})
    chat, _ = chat_with(cache, fakes, runs=runs)
    before = chat.unfinished
    chat.handle("/fix 1")
    waiting = chat.unfinished
    fakes.github.runs_by_commit[FIX_COMMIT] = [CommitRun(91, "pull_request")]

    assert chat.poll() == []
    notes = [entry.text for entry in chat.poll()]

    assert (before, waiting, chat.unfinished) == (False, True, False)

    assert notes[0] == "R1: CI passed on attempt 1."
    assert notes[1].startswith("Pull request #12: flakipype verification: CI passed 1 of 1 runs")
    assert fakes.github.comments == [notes[1].removeprefix("Pull request #12: ")]
    saved = json.loads(cache.sessions.load(1) or "{}")
    assert saved["fix"]["pulls"][0]["verification"]["stage"] == "done"


def test_new_and_resume_reset_the_mode_and_restore_the_fixes(cache: ScanCache) -> None:
    fakes = FixFakes()
    chat, _ = chat_with(cache, fakes, answer=False)
    chat.handle("/fix 1")
    chat.handle("/mode auto")

    chat.handle("/new")
    assert chat.mode is Mode.ASK
    assert chat.workspace.fixes.state()["proposals"] == []
    chat.handle("/mode auto")
    chat.handle("/resume 1")
    chat.handle("/fix 1")

    assert chat.mode is Mode.ASK
    assert len(fakes.fixer.requests) == 1


def test_sessions_from_before_fixes_resume_without_them(cache: ScanCache) -> None:
    chat, _ = chat_with(cache, answer=False)
    chat.handle("/fix 1")
    document = json.loads(cache.sessions.load(1) or "{}")
    del document["fix"]
    cache.sessions.update(1, now=NOW.isoformat(), data=json.dumps(document))

    chat.handle("/resume 1")

    assert chat.workspace.fixes.state() == {"opened": 0, "proposals": [], "pulls": []}


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("/fix", "Which finding? E.g. /fix 2 or /fix 2 --fresh."),
        ("/fix 9 --fresh", "#9: no such finding in the current scan."),
        ("/mode fast", "Which mode? /mode ask or /mode auto."),
    ],
)
def test_fix_and_mode_explain_what_is_missing(cache: ScanCache, line: str, error: str) -> None:
    chat, asked = chat_with(cache)

    (_, reply) = chat.handle(line)

    assert (reply.kind, reply.text) == (EntryKind.ERROR, error)
    assert asked == []
