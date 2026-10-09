from collections.abc import Callable

import pytest
from textual.app import App
from textual.dom import DOMNode
from textual.pilot import Pilot
from textual.widgets import Button, Markdown, Static

from flakipype.agent.tools import ActionRequest
from flakipype.store.database import ScanCache
from flakipype.tui.chat import ChatApp
from flakipype.tui.confirm import ConfirmScreen, diff_text

from support.fake_anthropic import ScriptedModel
from support.fake_chat import FixFakes, chat_service
from support.pilot import ask, settle

SIZE = (120, 40)


def app_for(cache: ScanCache, fakes: FixFakes) -> ChatApp:
    chat = chat_service(cache, ScriptedModel([]), fixes=fakes)
    return ChatApp(chat, "octo-org on github.com")


def shown(dialog: DOMNode, selector: str) -> str:
    return str(dialog.query_one(selector, Static).render())


def last_entry(app: ChatApp) -> str:
    return app.query("#conversation > Markdown").last(Markdown).source


async def test_the_fix_dialog_shows_the_model_text_and_the_diff(cache: ScanCache) -> None:
    fakes = FixFakes()
    app = app_for(cache, fakes)

    async with app.run_test(size=SIZE) as pilot:
        dialog = await ask(pilot, "/fix 1")

        assert shown(dialog, "#dialog-title") == "Push fix and open a draft pull request?"
        assert "Warnings: none" in shown(dialog, "#dialog-details")
        assert shown(dialog, "#dialog-model-text").startswith("Wait for the document rows\n\n")
        assert "+await rows.waitFor()" in shown(dialog, "#dialog-diff")
        assert str(dialog.query_one("#run", Button).label) == "Push"
        assert str(dialog.query_one("#decline", Button).label) == "Don't push"
        assert dialog.focused is dialog.query_one("#decline", Button)
        await pilot.click("#run")
        await settle(pilot)

        assert last_entry(app).startswith("Opened draft pull request #12")
        assert len(fakes.github.drafts) == 1


async def test_dont_push_keeps_the_fix(cache: ScanCache) -> None:
    fakes = FixFakes()
    app = app_for(cache, fakes)

    async with app.run_test(size=SIZE) as pilot:
        await ask(pilot, "/fix 1")
        await pilot.click("#decline")
        await settle(pilot)

        assert last_entry(app) == "Not run."
        assert fakes.github.drafts == []


class DialogApp(App[None]):
    def __init__(self, request: ActionRequest) -> None:
        super().__init__()
        self._request = request

    def on_mount(self) -> None:
        self.push_screen(ConfirmScreen(self._request))


@pytest.mark.parametrize(
    ("request_", "present", "absent"),
    [
        (ActionRequest("Push?", (), model_text="[b]Why[/b]"), "#dialog-model-text", "#dialog-diff"),
        (ActionRequest("Push?", (), diff="+x"), "#dialog-diff", "#dialog-model-text"),
        (ActionRequest("Rerun?", ()), "#dialog-details", "#dialog-change"),
    ],
)
async def test_the_change_pane_shows_only_what_there_is(
    request_: ActionRequest, present: str, absent: str
) -> None:
    app = DialogApp(request_)

    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        dialog = app.screen

        assert dialog.query(present)
        assert not dialog.query(absent)
        if request_.model_text:
            assert shown(dialog, present) == "[b]Why[/b]"


def test_markup_in_a_diff_stays_text() -> None:
    text = diff_text("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-[red]old\n+[bold]new\n context")

    assert text.plain == "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-[red]old\n+[bold]new\n context"
    assert [str(span.style) for span in text.spans] == ["bold", "bold", "cyan", "red", "green"]


def test_fix_dialog_snapshot(cache: ScanCache, snap_compare: Callable[..., bool]) -> None:
    app = app_for(cache, FixFakes())

    async def run(pilot: Pilot[None]) -> None:
        await ask(pilot, "/fix 1")

    assert snap_compare(app, terminal_size=SIZE, run_before=run)
