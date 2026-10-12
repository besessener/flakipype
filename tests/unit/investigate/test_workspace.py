from dataclasses import replace

import pytest

from flakipype.actions.service import ActionService
from flakipype.agent.investigator import Status
from flakipype.agent.tools import ToolError
from flakipype.config.settings import ActionSettings
from flakipype.store.database import ScanCache

from support.fake_chat import NOW, chat_workspace
from support.fake_investigation import SCAN, FakeAgent
from support.fake_runs import FakeRuns


def test_findings_scan_once_and_report_progress(cache: ScanCache) -> None:
    workspace = chat_workspace(cache, FakeAgent())
    activity: list[str] = []
    workspace.on_activity = activity.append

    first = workspace.findings()
    again = workspace.findings()

    assert first == again
    assert first.startswith("#1 [flaky] octo-org/app › CI › test\n  - ")
    assert "#3 [recurring error] octo-org/app › CI › lint" in first
    assert [finding.number for finding in workspace.finding_list()] == [1, 2, 3]
    assert activity[0] == "Listing repositories 0/1 · octo-org"
    assert "Reading workflow runs 1/1" in activity
    assert activity[-1] == ""


def test_scan_takes_new_options_and_forgets_old_verdicts(cache: ScanCache) -> None:
    workspace = chat_workspace(cache, FakeAgent())
    workspace.investigate((1,), fresh=False)

    summary = workspace.scan(7, ("app",))

    assert workspace.request.window_days == 7
    assert workspace.request.repositories == ("app",)
    assert workspace.results == {}
    assert summary.startswith("Scanned ")

    workspace.scan(None, ())

    assert workspace.request.window_days == 7
    assert workspace.request.repositories == ()


def test_investigate_keeps_verdicts_tokens_and_names_unknown_numbers(cache: ScanCache) -> None:
    agent = FakeAgent()
    workspace = chat_workspace(cache, agent)
    activity: list[str] = []
    workspace.on_activity = activity.append

    text = workspace.investigate((1, 9), fresh=False)

    assert "#1 octo-org/app › CI › test" in text
    assert "Classification: flaky_test, confidence high" in text
    assert text.endswith("#9: no such finding.")
    assert workspace.tokens == 1_000
    assert set(workspace.results) == {1}
    assert "Investigating #1 test" in activity
    assert "Investigated 1/1" in activity


def test_verdict_reuses_results_or_investigates(cache: ScanCache) -> None:
    agent = FakeAgent()
    workspace = chat_workspace(cache, agent)

    first = workspace.verdict(3)
    second = workspace.verdict(3)

    assert first == second
    assert agent.calls == [3]


def test_failed_investigations_say_why(cache: ScanCache) -> None:
    workspace = chat_workspace(cache, FakeAgent(status=Status.BUDGET))

    text = workspace.investigate((2,), fresh=True)

    assert "No verdict (budget)" in text


def test_start_over_and_resume_go_back_to_the_configured_scan(cache: ScanCache) -> None:
    workspace = chat_workspace(cache, FakeAgent())
    workspace.scan(7, ("app",))
    workspace.investigate((1,), fresh=False)

    workspace.start_over()

    assert (workspace.request, workspace.report, workspace.results) == (SCAN, None, {})
    assert workspace.tokens == 0
    workspace.resume(window_days=90, repositories=("docs",), tokens=500)
    assert workspace.request == replace(SCAN, window_days=90, repositories=("docs",))
    assert workspace.tokens == 500


def test_a_fix_outside_the_configured_owner_spends_no_tokens(cache: ScanCache) -> None:
    agent = FakeAgent()
    workspace = chat_workspace(cache, agent)
    workspace.actions = ActionService(
        runs=FakeRuns(), files=FakeRuns(), audit=cache.audit, settings=ActionSettings(),
        owner="other-org", now=lambda: NOW,
    )  # fmt: skip

    with pytest.raises(ToolError, match="does not belong to the configured owner other-org"):
        workspace.fix(1, "")

    assert workspace.tokens == 0
    assert workspace.results == {}
