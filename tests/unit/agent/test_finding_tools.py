from typing import Any

import pytest

from flakipype.agent.finding_tools import FindingTools
from flakipype.agent.tools import Mode, PolicyGate, RiskLevel, ToolError, deny_all
from flakipype.flaky.signature import Category, ErrorSignature
from flakipype.github.actions import GitHubApiError
from flakipype.github.contents import ChangedFile, Comparison

from support.fake_sources import FakeContents, FakeLogs, evidence, finding


def tools(logs: FakeLogs | None = None, contents: FakeContents | None = None) -> FindingTools:
    return FindingTools(finding(), evidence(), logs or FakeLogs(), contents or FakeContents())


def run(given: FindingTools, name: str, **arguments: Any) -> str:
    (tool,) = [tool for tool in given.tools() if tool.name == name]
    return tool.invoke(arguments, PolicyGate(Mode.ASK, deny_all))


def test_every_tool_only_reads() -> None:
    assert {tool.risk for tool in tools().tools()} == {RiskLevel.READ}


def test_failure_excerpt_is_marked_and_cached() -> None:
    logs = FakeLogs()
    given = tools(logs)

    first = run(given, "failure_excerpt", job_id=11)
    run(given, "failure_excerpt", job_id=11)

    assert first.startswith('<log job="11" job_name="test" step="Run npm test" lines="1-4 of 4"')
    assert "+00:35  ##[error]Test timed out after 5000ms" in first
    assert logs.calls == [11]


def test_unknown_jobs_and_expired_logs_are_tool_errors() -> None:
    given = tools(FakeLogs(logs={11: None}))

    with pytest.raises(ToolError, match="not a job of this workflow"):
        run(given, "failure_excerpt", job_id=999)
    with pytest.raises(ToolError, match="no longer available"):
        run(given, "log_range", job_id=11, from_line=1, to_line=5)


def test_log_range() -> None:
    shown = run(tools(), "log_range", job_id=11, from_line=2, to_line=3)

    assert "    2 ##[error]Test timed out after 5000ms" in shown
    assert "    1 " not in shown


def test_run_history_lists_runs_with_failed_jobs_and_errors() -> None:
    given = FindingTools(
        finding(),
        evidence().__class__(
            runs=evidence().runs,
            jobs=evidence().jobs,
            signatures={11: ErrorSignature(Category.TIMEOUT, "wait timed out", "f" * 12, "e")},
        ),
        FakeLogs(),
        FakeContents(),
    )

    history = run(given, "run_history", limit=2)

    lines = history.splitlines()
    assert lines[1].startswith("2026-10-01 11:00 run 3 attempt 1 push main 3333333333: failure")
    assert "failed attempt 1 job 31 test (Run tests)" in history
    assert "run 1 " not in history
    assert run(given, "run_history").count(" run ") == 3
    assert "— timeout: wait timed out" in run(given, "run_history")


def test_run_history_without_runs() -> None:
    empty = FindingTools(finding(), evidence().__class__(), FakeLogs(), FakeContents())

    assert "no runs" in run(empty, "run_history")


def test_compare_commits_and_file_diff() -> None:
    given = tools()

    commits = run(given, "compare_commits", base="a", head="b")
    diff = run(given, "file_diff", base="a", head="b", path="tests/e2e/scan.spec.ts")

    assert "abcdef1234 2026-10-01 dev: Raise timeout" in commits
    assert "modified  +1 -1 tests/e2e/scan.spec.ts" in commits
    assert "+b" in diff
    with pytest.raises(ToolError, match="did not change"):
        run(given, "file_diff", base="a", head="b", path="other.py")


def test_long_diffs_and_binary_files() -> None:
    long_patch = "\n".join(f"+line {n}" for n in range(400))
    contents = FakeContents(
        comparison=Comparison(
            total_commits=1,
            commits=[],
            files=[
                ChangedFile("big.py", "modified", 400, 0, long_patch),
                ChangedFile("img.png", "added", 0, 0, ""),
            ],
        )
    )
    given = tools(contents=contents)

    assert "[… 100 more lines …]" in run(given, "file_diff", base="a", head="b", path="big.py")
    assert "no textual diff" in run(given, "file_diff", base="a", head="b", path="img.png")
    commits = run(given, "compare_commits", base="a", head="b")
    assert "1 commits (newest 0 shown)" in commits


def test_read_file_and_workflow_file() -> None:
    contents = FakeContents(
        files={
            ("tests/x.py", "abc"): "\n".join(f"line {n}" for n in range(1, 501)),
            (".github/workflows/ci.yml", "main"): "name: CI\n",
        }
    )
    given = tools(contents=contents)

    window = run(given, "read_file", path="tests/x.py", ref="abc", from_line=450)
    workflow = run(given, "workflow_file", ref="main")

    assert 'lines="450-500 of 500"' in window
    assert "  450 line 450" in window
    assert "    1 name: CI" in workflow
    with pytest.raises(ToolError, match="does not exist at abc"):
        run(given, "read_file", path="missing.py", ref="abc")


def test_github_errors_become_tool_errors() -> None:
    class Refusing(FakeContents):
        def file_content(self, repository: str, path: str, ref: str) -> str | None:
            del repository, path, ref
            raise GitHubApiError("gh: Server Error (HTTP 502)", 502)

    with pytest.raises(ToolError, match="GitHub refused"):
        run(tools(contents=Refusing()), "workflow_file", ref="main")
