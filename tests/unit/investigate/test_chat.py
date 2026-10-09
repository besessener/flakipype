from dataclasses import replace

from flakipype.agent.investigator import Status
from flakipype.github.actions import GitHubApiError
from flakipype.investigate.chat import ChatEntry, EntryKind, SidebarItem
from flakipype.investigate.chat_text import HELP
from flakipype.store.database import ScanCache

from support.fake_actions import FakeActions
from support.fake_anthropic import ScriptedModel, call, message, text
from support.fake_chat import chat_service
from support.fake_investigation import FakeAgent


def kinds(entries: list[ChatEntry]) -> list[EntryKind]:
    return [entry.kind for entry in entries]


def test_help_blank_lines_and_unknown_commands(cache: ScanCache) -> None:
    chat = chat_service(cache, ScriptedModel([]))

    assert chat.handle("   ") == []
    assert chat.handle("/help") == [
        ChatEntry(EntryKind.USER, "/help"),
        ChatEntry(EntryKind.NOTE, HELP),
    ]
    (_, unknown) = chat.handle("/push")
    assert unknown == ChatEntry(EntryKind.ERROR, "Unknown command /push. Type /help.")


def test_scan_fills_the_sidebar(cache: ScanCache) -> None:
    chat = chat_service(cache, ScriptedModel([]))
    assert chat.sidebar() == []

    (_, note) = chat.handle("/scan 14")

    assert note.text.startswith("Scanned 1 repositories")
    assert chat.workspace.request.window_days == 14
    assert chat.sidebar() == [
        SidebarItem(1, "flaky", "octo-org/app › CI › test"),
        SidebarItem(2, "seen once", "octo-org/app › E2E › e2e"),
        SidebarItem(3, "recurring error", "octo-org/app › CI › lint"),
    ]
    assert chat.handle("/findings")[1].text == chat.handle("/flaky")[1].text


def test_investigate_all_why_and_budget(cache: ScanCache) -> None:
    agent = FakeAgent()
    chat = chat_service(cache, ScriptedModel([]), agent=agent)

    (_, investigated) = chat.handle("/investigate all --fresh")
    (_, why) = chat.handle("/why #3")
    (_, budget) = chat.handle("/budget")

    assert agent.calls == [1, 3]
    assert "Classification: flaky_test" in investigated.text
    assert why.text.startswith("#3 octo-org/app › CI › lint")
    assert budget.text == "Tokens used in this session: 2,000"
    verdicts = [item.verdict for item in chat.sidebar()]
    assert verdicts == ["flaky test (high)", "", "flaky test (high)"]


def test_failed_investigations_show_in_the_sidebar(cache: ScanCache) -> None:
    chat = chat_service(cache, ScriptedModel([]), agent=FakeAgent(status=Status.NO_VERDICT))

    chat.handle("/investigate 2")

    assert chat.sidebar()[1].verdict == "no verdict"


def test_commands_without_numbers_ask_for_them(cache: ScanCache) -> None:
    chat = chat_service(cache, ScriptedModel([]))

    (_, investigate) = chat.handle("/investigate")
    (_, why) = chat.handle("/why")

    assert investigate.kind is EntryKind.ERROR
    assert "/investigate 1 3" in investigate.text
    assert why == ChatEntry(EntryKind.ERROR, "Which finding? E.g. /why 1.")


def test_questions_go_to_the_agent(cache: ScanCache) -> None:
    model = ScriptedModel(
        [message(call("t1", "list_findings", {})), message(text("#1 is flaky.")), 500]
    )
    chat = chat_service(cache, model)
    steps: list[str] = []

    answered = chat.handle("Which jobs are flaky?", steps.append)
    failed = chat.handle("And why?")

    assert answered == [
        ChatEntry(EntryKind.USER, "Which jobs are flaky?"),
        ChatEntry(EntryKind.ASSISTANT, "#1 is flaky."),
    ]
    assert steps == ["list_findings"]
    assert failed[1].kind is EntryKind.ERROR
    assert chat.tokens == 2_400
    assert len(chat.sidebar()) == 3


def test_github_errors_are_shown_not_raised(cache: ScanCache) -> None:
    broken = FakeActions(repositories_error=GitHubApiError("gh: Not Found (HTTP 404)", 404))
    chat = chat_service(cache, ScriptedModel([]), actions=broken)

    (_, error) = chat.handle("/scan")

    assert error == ChatEntry(EntryKind.ERROR, "GitHub: gh: Not Found (HTTP 404)")


def test_sessions_are_saved_listed_and_resumed(cache: ScanCache) -> None:
    model = ScriptedModel([message(text("Hello.")), message(text("Welcome back."))])
    chat = chat_service(cache, model)
    assert chat.handle("/sessions")[1].text == "No saved sessions yet."
    chat.handle("/scan 7")
    chat.handle("Hi")
    conversation = chat.entries

    assert chat.handle("/new") == [ChatEntry(EntryKind.NOTE, "New session.")]
    assert chat.entries == []
    (_, listed) = chat.handle("/sessions")
    resumed = chat.handle("/resume 1")

    assert "- `1` /sessions (2026-10-09 08:" in listed.text
    assert resumed == [ChatEntry(EntryKind.NOTE, "Resumed session 1. The next action rescans.")]
    assert chat.entries == conversation
    assert chat.tokens == 1_200
    assert chat.workspace.request.window_days == 7
    assert chat.workspace.report is None
    assert [item.number for item in chat.sidebar()] == [1, 2, 3]
    chat.handle("Again?")
    assert [m["role"] for m in model.requests[1]["messages"]] == ["user", "assistant", "user"]


def test_resuming_an_unknown_session(cache: ScanCache) -> None:
    chat = chat_service(cache, ScriptedModel([]))

    assert chat.handle("/resume 9")[0].kind is EntryKind.ERROR
    assert chat.handle("/resume")[0].text == "No such session. See /sessions."


def test_a_resumed_session_keeps_its_repositories(cache: ScanCache) -> None:
    chat = chat_service(cache, ScriptedModel([]))
    chat.workspace.request = replace(chat.workspace.request, repositories=("app",))
    chat.handle("/help")
    chat.handle("/new")

    chat.handle("/resume 1")

    assert chat.workspace.request.repositories == ("app",)
