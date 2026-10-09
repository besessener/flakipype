from collections.abc import Callable

from textual.pilot import Pilot
from textual.widgets import Markdown, Static

from flakipype.agent.tools import Confirmer
from flakipype.github.runs import JobState
from flakipype.store.database import ScanCache
from flakipype.tui.chat import ChatApp, runs_text

from support.fake_anthropic import ScriptedModel
from support.fake_chat import chat_service
from support.fake_runs import DISPATCHABLE, E2E, FakeRuns, state
from support.pilot import ask, settle

SIZE = (120, 40)


def failed_lint_run() -> FakeRuns:
    return FakeRuns(
        states={6: [state(6, name="CI")]}, jobs={(6, 1): [JobState("lint", "completed", "failure")]}
    )


def app_for(cache: ScanCache, started: FakeRuns) -> ChatApp:
    return ChatApp(chat_service(cache, ScriptedModel([]), runs=started), "octo-org on github.com")


def last_entry(app: ChatApp) -> str:
    return app.query("#conversation > Markdown").last(Markdown).source


def runs_panel(app: ChatApp) -> str:
    panel = app.query_one("#runs", Static)
    return str(panel.render()) if panel.display else ""


async def test_a_confirmed_rerun_shows_up_in_the_runs_panel(cache: ScanCache) -> None:
    started = failed_lint_run()
    app = app_for(cache, started)

    async with app.run_test(size=SIZE) as pilot:
        assert runs_panel(app) == ""
        dialog = await ask(pilot, "/rerun 3")
        assert "run 6 (attempt 1 → 2)" in str(dialog.query_one("#dialog-details").render())
        await pilot.click("#run")
        await settle(pilot)

        assert "rerun_failed_jobs octo-org/app 6" in started.calls
        assert runs_panel(app) == "R1 app · CI #6/2\n  queued"
        started.states[6] = [state(6, conclusion="success", attempt=2, name="CI")]
        app.action_poll_runs()
        await settle(pilot)

        assert runs_panel(app) == "R1 app · CI #6/2\n  ✓ passed"
        assert "R1: CI passed on attempt 2" in last_entry(app)
        app.action_poll_runs()
        assert len(app.workers) == 0


async def test_escape_declines(cache: ScanCache) -> None:
    started = failed_lint_run()
    app = app_for(cache, started)

    async with app.run_test(size=SIZE) as pilot:
        await ask(pilot, "/rerun 3")
        await pilot.press("escape")
        await settle(pilot)

        assert "Not run." in last_entry(app)
        assert not [call for call in started.calls if call.startswith("rerun")]


async def test_a_poll_in_progress_is_not_started_twice(cache: ScanCache) -> None:
    app = app_for(cache, failed_lint_run())

    async with app.run_test(size=SIZE) as pilot:
        await ask(pilot, "/rerun 3")
        await pilot.click("#run")
        await settle(pilot)
        app.action_poll_runs()
        app.action_poll_runs()

        assert len(app.workers) == 1
        await settle(pilot)


def test_runs_are_listed_one_below_the_other(cache: ScanCache) -> None:
    started = FakeRuns(files={(E2E, "3f2a9c1"): DISPATCHABLE})
    confirmer = Confirmer()
    confirmer.ask = lambda _: True
    chat = chat_service(cache, ScriptedModel([]), runs=started, confirmer=confirmer)
    chat.handle("/dispatch 2 x2")

    assert str(runs_text(chat.watched_runs())) == (
        "R1 app · E2E dispatch 1/2\n  queued\nR2 app · E2E dispatch 2/2\n  queued"
    )


def test_confirmation_snapshot(cache: ScanCache, snap_compare: Callable[..., bool]) -> None:
    app = app_for(cache, failed_lint_run())

    async def run(pilot: Pilot[None]) -> None:
        await ask(pilot, "/rerun 3")

    assert snap_compare(app, terminal_size=SIZE, run_before=run)


def test_runs_panel_snapshot(cache: ScanCache, snap_compare: Callable[..., bool]) -> None:
    app = app_for(cache, failed_lint_run())

    async def run(pilot: Pilot[None]) -> None:
        await ask(pilot, "/rerun 3")
        await pilot.click("#run")
        await settle(pilot)

    assert snap_compare(app, terminal_size=SIZE, run_before=run)
