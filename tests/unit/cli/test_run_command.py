import io
import json
import os
import signal
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import timedelta

import click
import pytest
from rich.console import Console
from typer.testing import CliRunner

from flakipype.agent.tools import Mode
from flakipype.cli import app, errors, wiring
from flakipype.cli.run_report import render_run
from flakipype.config.settings import GitHubSettings, Settings
from flakipype.github.actions import ApiRateLimitError, GitHubApiError
from flakipype.scan.service import ScanRequest
from flakipype.store.database import ScanCache
from flakipype.store.lock import RunLockedError
from flakipype.unattended.limits import Usage
from flakipype.unattended.service import RunService

from support.fake_actions import FakeActions
from support.fake_investigation import world
from support.fake_run import ClassifyingAgent, RunWorld, limits

runner = CliRunner()
SETTINGS = Settings(github=GitHubSettings(owner="octo-org"))


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch, cache: ScanCache) -> list[tuple[Mode, ScanRequest]]:
    """Each `open_run` call: the mode and the scan request built from the options."""
    calls: list[tuple[Mode, ScanRequest]] = []

    @contextmanager
    def open_run(
        mode: Mode, request_for: Callable[[Settings], ScanRequest]
    ) -> Generator[RunService]:
        calls.append((mode, request_for(SETTINGS)))
        yield RunWorld(cache, mode=mode).service()

    monkeypatch.setattr(wiring, "open_run", open_run)
    return calls


def test_run_prints_a_summary(opened: list[tuple[Mode, ScanRequest]]) -> None:
    result = runner.invoke(app, ["run", "--days", "7", "--repo", "app"])

    assert result.exit_code == 0, result.output
    lines = click.unstyle(result.stdout).splitlines()
    assert lines[0] == "flakipype run · octo-org · auto · 2026-10-09 08:00–08:00 UTC"
    assert lines[1] == "Scan: 1 repositories, 6 runs, 1 flaky, 1 seen once, 1 recurring error"
    assert lines[2] == "Investigated: 2 (1 flaky_test, 1 real_bug)"
    assert lines[3].startswith("Fixes: #1 octo-org/app › CI › test: Opened draft pull request #12")
    assert lines[4] == (
        "       #3 octo-org/app › CI › lint: not fixed: real bug, which flakipype does not fix"
    )
    assert lines[5].startswith("Verification: octo-org/app#12: flakipype verification: cannot")
    assert lines[6] == (
        "Budget: pull requests today 1 of 3 · actions today 0 of 20 · tokens 3,000 of "
        "1,000,000 (today 3,000 of 3,000,000)"
    )
    ((mode, request),) = opened
    assert (mode, request.window_days, request.repositories) == (Mode.AUTO, 7, ("app",))


@pytest.mark.usefixtures("berlin_time_zone", "opened")
def test_the_summary_shows_local_time() -> None:
    result = runner.invoke(app, ["run"])

    first = click.unstyle(result.stdout).splitlines()[0]
    assert first == "flakipype run · octo-org · auto · 2026-10-09 10:00–10:00 CEST"


def test_run_in_ask_mode_as_json(opened: list[tuple[Mode, ScanRequest]]) -> None:
    result = runner.invoke(app, ["run", "--mode", "ask", "--json"])

    exported = json.loads(result.stdout)
    assert result.exit_code == 0
    assert (exported["schema_version"], exported["mode"], exported["complete"]) == (1, "ask", True)
    fix, real_bug = exported["fixes"]
    assert (fix["finding"], fix["kind"]) == (1, "kept")
    assert (real_bug["finding"], real_bug["kind"]) == (3, "skipped")
    assert "+await rows.waitFor()" in fix["diff"]
    assert exported["investigations"][0] == {
        "finding": 1, "status": "completed", "classification": "flaky_test",
        "review": "accepted: ok", "from_cache": False,
    }  # fmt: skip
    assert exported["budget"]["run_limits"] == {
        "pull_requests": 3, "actions": 10, "tokens": 1_000_000, "minutes": 120,
    }  # fmt: skip
    assert exported["scan"]["owner"] == "octo-org"
    assert opened[0][0] is Mode.ASK


def test_the_summary_lists_every_fix_and_problem_on_its_own_line(cache: ScanCache) -> None:
    world = RunWorld(cache, agent=ClassifyingAgent(flaky=frozenset({1, 3})))
    world.github.errors["open_draft"] = GitHubApiError("Server Error (HTTP 500)", 500)

    report = world.service().run()
    text = render_run(report)

    assert "Problems: Branch flakipype/fix-ci-" in text
    assert "\n          Branch flakipype/fix-ci-" in text
    assert "Fixes: #1 octo-org/app › CI › test: Branch flakipype/fix-ci-" in text
    assert "\n       #3 octo-org/app › CI › lint: Branch" in text


def test_the_summary_of_runs_that_stopped(cache: ScanCache) -> None:
    world = RunWorld(cache, limits=limits(minutes=10))
    world.github.files[".github/workflows/ci.yml"] = b"on: pull_request\njobs: {}\n"
    report = world.service().run()
    cached = RunWorld(cache, limits=limits(pull_requests=0)).service().run()
    world.source.repositories_error = GitHubApiError("Bad credentials (HTTP 401)", 401)
    failed = world.service().run()

    assert "octo-org/app#12: 0 of 3 runs, continues in the next run" in render_run(report)
    assert "Stopped by: the time limit of 10 minutes; verifications continue" in render_run(report)
    assert "Investigated: 0, 2 verdicts from the cache" in render_run(cached)
    assert render_run(failed).splitlines()[:3] == [
        f"flakipype run · — · auto · {failed.started:%Y-%m-%d %H:%M}–{failed.finished:%H:%M} UTC",
        "Scan: not finished",
        "Investigated: 0",
    ]
    assert report.started + timedelta(minutes=10) == report.finished


def test_a_stopped_scan_is_named_and_the_day_counts_earlier_runs(cache: ScanCache) -> None:
    world = RunWorld(cache, limits=replace(limits(), day_used=Usage(1, 4, 500)))
    world.source.runs_by_repository["octo-org/app"] = ApiRateLimitError("rate limit", 403)

    report = world.service().run()

    text = render_run(report)
    assert text.splitlines()[1] == "Scan: 1 repositories, 0 runs, no findings; stopped early"
    assert "pull requests today 1 of 3 · actions today 4 of 20" in text
    assert "(today 500 of 3,000,000)" in text
    assert not report.complete


@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (RunLockedError("another flakipype run holds /x/run.lock"), 3, "Not started: another"),
        (wiring.NotReadyError("No API key stored."), 2, "Not ready: No API key stored."),
        (GitHubApiError("Bad credentials (HTTP 401)", 401), 1, "GitHub: Bad credentials"),
    ],
)
def test_run_exit_codes(
    monkeypatch: pytest.MonkeyPatch, error: Exception, code: int, message: str
) -> None:
    def open_run(*_: object) -> Iterator[RunService]:
        raise error

    monkeypatch.setattr(wiring, "open_run", open_run)

    result = runner.invoke(app, ["run"])

    assert result.exit_code == code
    assert message in click.unstyle(result.stderr)


def test_an_incomplete_run_exits_with_one(
    monkeypatch: pytest.MonkeyPatch, cache: ScanCache
) -> None:
    world = RunWorld(cache)
    world.source.repositories_error = GitHubApiError("Bad credentials (HTTP 401)", 401)

    @contextmanager
    def open_run(*_: object) -> Generator[RunService]:
        yield world.service()

    monkeypatch.setattr(wiring, "open_run", open_run)

    result = runner.invoke(app, ["run"])

    assert result.exit_code == 1
    assert "Problems: GitHub: Bad credentials (HTTP 401)" in result.stdout


@dataclass
class TerminatedGitHub(FakeActions):
    """systemd stops the run while it reads the first log."""

    def job_log(self, repository: str, job_id: int) -> str | None:
        os.kill(os.getpid(), signal.SIGTERM)
        return super().job_log(repository, job_id)


def test_sigterm_ends_the_run_with_its_summary(
    monkeypatch: pytest.MonkeyPatch, cache: ScanCache
) -> None:
    world_run = RunWorld(cache, source=TerminatedGitHub(**vars(world())))

    @contextmanager
    def open_run(*_: object) -> Generator[RunService]:
        yield world_run.service()

    monkeypatch.setattr(wiring, "open_run", open_run)
    before = signal.getsignal(signal.SIGTERM)

    result = runner.invoke(app, ["run"])

    assert result.exit_code == 1
    assert "Problems: stopped by SIGTERM before it finished" in result.stdout
    assert signal.getsignal(signal.SIGTERM) == before


def test_progress_goes_to_a_terminal_on_stderr(
    monkeypatch: pytest.MonkeyPatch, opened: list[tuple[Mode, ScanRequest]]
) -> None:
    terminal = io.StringIO()

    def console(*, stderr: bool, highlight: bool) -> Console:
        assert stderr
        return Console(file=terminal, force_terminal=True, highlight=highlight, width=100)

    monkeypatch.setattr(errors, "Console", console)

    result = runner.invoke(app, ["run"])

    assert result.exit_code == 0
    assert "Investigating #1 test" in click.unstyle(terminal.getvalue())
    assert opened


def test_progress_shows_job_names_as_text_not_markup(
    monkeypatch: pytest.MonkeyPatch, cache: ScanCache
) -> None:
    source = world()
    source.jobs_by_attempt = {
        attempt: [replace(job, name="unit [/]") for job in jobs]
        for attempt, jobs in source.jobs_by_attempt.items()
        if isinstance(jobs, list)
    }

    @contextmanager
    def open_run(
        mode: Mode, request_for: Callable[[Settings], ScanRequest]
    ) -> Generator[RunService]:
        del request_for
        yield RunWorld(cache, mode=mode, source=source).service()

    terminal = io.StringIO()
    monkeypatch.setattr(wiring, "open_run", open_run)
    monkeypatch.setattr(
        errors, "Console", lambda **_: Console(file=terminal, force_terminal=True, width=100)
    )

    result = runner.invoke(app, ["run"])

    assert result.exit_code == 0, result.output
    assert "Investigating #1 unit [/]" in click.unstyle(terminal.getvalue())
