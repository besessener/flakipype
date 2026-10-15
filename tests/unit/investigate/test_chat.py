from dataclasses import replace

from flakipype.agent.investigator import Status
from flakipype.flaky.model import WorkflowRun
from flakipype.github.actions import GitHubApiError, Repository
from flakipype.investigate.chat import ChatEntry, EntryKind, SidebarItem
from flakipype.investigate.chat_text import HELP
from flakipype.store.database import ScanCache

from support.fake_actions import FakeActions
from support.fake_anthropic import ScriptedModel, call, message, text
from support.fake_chat import chat_service
from support.fake_investigation import APP, FakeAgent, world


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
    references = [finding.reference for finding in chat.workspace.finding_list()]
    assert chat.sidebar() == [
        SidebarItem(1, "flaky", "octo-org/app › CI › test", reference=references[0]),
        SidebarItem(2, "seen once", "octo-org/app › E2E › e2e", reference=references[1]),
        SidebarItem(3, "recurring error", "octo-org/app › CI › lint", reference=references[2]),
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


def test_numbers_that_are_not_ascii_digits_are_not_numbers(cache: ScanCache) -> None:
    chat = chat_service(cache, ScriptedModel([]))

    (_, why) = chat.handle("/why ²")
    (_, dispatch) = chat.handle("/dispatch ²")

    assert why == ChatEntry(EntryKind.ERROR, "Which finding? E.g. /why 1.")
    assert dispatch.kind is EntryKind.ERROR


def test_scan_days_stay_within_the_window_limit(cache: ScanCache) -> None:
    chat = chat_service(cache, ScriptedModel([]))

    (_, too_many) = chat.handle("/scan 1000000")
    (_, none) = chat.handle("/scan 0")
    (_, two_windows) = chat.handle("/scan 7 14 app")

    assert too_many == ChatEntry(
        EntryKind.ERROR,
        "Scan 1 to 400 days and any repositories, e.g. /scan 7 or /scan 7 app.",
    )
    assert none.kind is EntryKind.ERROR
    assert two_windows == too_many
    assert chat.workspace.report is None


def test_scan_names_repositories_and_a_bare_scan_takes_all_again(cache: ScanCache) -> None:
    actions = world()
    actions.repositories_found.append(Repository("octo-org/docs", "main"))
    chat = chat_service(cache, ScriptedModel([]), actions=actions)

    (_, one) = chat.handle("/scan app 14")
    one_request = chat.workspace.request
    (_, by_full_name) = chat.handle("/scan octo-org/docs")
    (_, every) = chat.handle("/scan")

    assert one.text.startswith("Scanned 1 repositories")
    assert (one_request.window_days, one_request.repositories) == (14, ("app",))
    assert by_full_name.text.startswith("Scanned 1 repositories")
    assert "No findings." in by_full_name.text
    assert every.text.startswith("Scanned 2 repositories")
    assert chat.workspace.request.repositories == ()


def test_a_scan_says_which_repository_names_match_nothing(cache: ScanCache) -> None:
    chat = chat_service(cache, ScriptedModel([]))

    (_, note) = chat.handle("/scan ap")

    assert note.text.startswith("Scanned 0 repositories")
    assert "Note: No repository named ap in octo-org" in note.text


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


def test_a_number_that_moved_since_the_resumed_scan_is_refused_once(cache: ScanCache) -> None:
    actions = world()
    agent = FakeAgent()
    chat = chat_service(cache, ScriptedModel([]), agent=agent, actions=actions)
    chat.handle("/scan")
    chat.handle("/new")
    chat.handle("/resume 1")
    # The E2E run that made #2 has left the window: the lint error is #2 now.
    actions.runs_by_repository[APP] = [item for item in world_runs() if item.run_id != 4]

    (_, refused) = chat.handle("/why 2")
    (_, answered) = chat.handle("/why 2")

    assert refused == ChatEntry(
        EntryKind.ERROR,
        "Finding numbers changed since this session's scan (#2). The sidebar now shows the "
        "current numbers; run the command again with those.",
    )
    assert answered.text.startswith("#2 octo-org/app › CI › lint")
    assert agent.calls == [2]


def world_runs() -> list[WorkflowRun]:
    runs = world().runs_by_repository[APP]
    assert isinstance(runs, list)
    return runs


def test_numbers_that_still_match_after_a_resume_just_work(cache: ScanCache) -> None:
    agent = FakeAgent()
    chat = chat_service(cache, ScriptedModel([]), agent=agent)
    chat.handle("/scan")
    chat.handle("/new")
    chat.handle("/resume 1")

    (_, answered) = chat.handle("/why 1")

    assert answered.text.startswith("#1 octo-org/app › CI › test")
    assert agent.calls == [1]


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
