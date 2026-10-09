from collections.abc import Callable

from textual.pilot import Pilot
from textual.widgets import Input, ListView, Markdown, Static

from flakipype.investigate.chat import ChatService
from flakipype.store.database import ScanCache
from flakipype.tui.chat import ChatApp, FindingItem

from support.fake_anthropic import ScriptedModel, call, message, text
from support.fake_chat import chat_service
from support.pilot import settle

SIZE = (120, 40)


async def send(pilot: Pilot[None], line: str) -> None:
    prompt = pilot.app.query_one("#prompt", Input)
    prompt.value = line
    prompt.focus()
    await pilot.press("enter")
    await settle(pilot)


def conversation(app: ChatApp) -> list[str]:
    texts = []
    for widget in app.query_one("#conversation").children:
        if isinstance(widget, Markdown):
            texts.append(widget.source)
        else:
            texts.append(str(widget.render()))
    return texts


def sidebar(app: ChatApp) -> list[FindingItem]:
    return list(app.query_one("#findings", ListView).query(FindingItem))


def activity(app: ChatApp) -> str:
    return str(app.query_one("#activity", Static).render())


def app_for(cache: ScanCache, model: ScriptedModel | None = None) -> tuple[ChatApp, ChatService]:
    chat = chat_service(cache, model or ScriptedModel([]))
    return ChatApp(chat, "octo-org on github.com"), chat


async def test_scan_fills_the_sidebar_and_a_click_proposes_a_command(cache: ScanCache) -> None:
    app, _ = app_for(cache)

    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert sidebar(app) == []
        await send(pilot, "/scan")

        assert "› /scan" in conversation(app)
        assert conversation(app)[-1].startswith("Scanned 1 repositories")
        assert [item.item.number for item in sidebar(app)] == [1, 2, 3]
        assert activity(app) == "0 tokens used · ask mode"
        app.query_one("#findings", ListView).focus()
        await pilot.press("down", "down", "enter")
        await pilot.pause()

        assert app.query_one("#prompt", Input).value == "/investigate 2"


async def test_questions_show_tool_activity_and_answers(cache: ScanCache) -> None:
    model = ScriptedModel(
        [
            message(call("t1", "investigate", {"findings": [1]})),
            message(text("**#1** is a flaky test.")),
        ]
    )
    app, _ = app_for(cache, model)

    async with app.run_test(size=SIZE) as pilot:
        await send(pilot, "Why is #1 flaky?")
        app.query_one("#findings", ListView).focus()
        await pilot.press("down", "enter")
        await pilot.pause()

        assert conversation(app)[-1] == "**#1** is a flaky test."
        assert activity(app) == "3,400 tokens used · ask mode"
        assert sidebar(app)[0].item.verdict == "flaky test (high)"
        assert app.query_one("#prompt", Input).value == "/why 1"


async def test_new_and_resume_replace_the_conversation(cache: ScanCache) -> None:
    app, _ = app_for(cache)

    async with app.run_test(size=SIZE) as pilot:
        await send(pilot, "/help")
        await send(pilot, "/new")
        assert conversation(app) == ["New session."]
        await send(pilot, "/resume 1")

        assert conversation(app)[0] == "› /help"
        assert conversation(app)[-1] == "Resumed session 1. The next action rescans."


async def test_the_status_line_shows_the_mode(cache: ScanCache) -> None:
    app, _ = app_for(cache)

    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert activity(app) == "0 tokens used · ask mode"
        await send(pilot, "/mode auto")
        assert activity(app) == "0 tokens used · auto mode"
        await send(pilot, "/new")

        assert activity(app) == "0 tokens used · ask mode"


async def test_blank_lines_are_ignored_and_quit_leaves(cache: ScanCache) -> None:
    app, chat = app_for(cache)

    async with app.run_test(size=SIZE) as pilot:
        await send(pilot, "  ")
        assert chat.entries == []
        app.query_one("#findings", ListView).focus()
        await pilot.press("down", "enter")
        await pilot.pause()
        assert app.query_one("#prompt", Input).value == ""
        await send(pilot, "/quit")

    assert app.return_code == 0


def test_chat_snapshot(cache: ScanCache, snap_compare: Callable[..., bool]) -> None:
    app, _ = app_for(cache)

    async def run(pilot: Pilot[None]) -> None:
        # A blinking cursor would make the picture depend on timing.
        pilot.app.query_one("#prompt", Input).cursor_blink = False
        await send(pilot, "/scan")

    assert snap_compare(app, terminal_size=SIZE, run_before=run)
