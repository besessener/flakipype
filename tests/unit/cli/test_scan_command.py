import io
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import click
import pytest
from rich.console import Console
from typer.testing import CliRunner

from flakipype.cli import app, wiring
from flakipype.cli.scan_command import ProgressView, progress_display
from flakipype.config.settings import GitHubSettings, ScanSettings, Settings
from flakipype.github.actions import ApiRateLimitError, GitHubApiError, Repository
from flakipype.scan.progress import Progress, Stage
from flakipype.scan.service import ScanService
from flakipype.store.database import ScanCache

from support.builders import job, run
from support.fake_actions import FakeActions

runner = CliRunner()
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
SETTINGS = Settings(
    github=GitHubSettings(owner="octo-org"),
    scan=ScanSettings(window_days=14, max_log_downloads=7),
)


@pytest.fixture
def actions(monkeypatch: pytest.MonkeyPatch) -> FakeActions:
    fake = FakeActions(
        repositories_found=[Repository("octo-org/app", "main"), Repository("octo-org/docs", "")],
        runs_by_repository={"octo-org/app": [run(1, attempt=2), run(2)]},
        jobs_by_attempt={(1, 1): [job(11, run_id=1)]},
        logs={11: "2026-10-07T09:27:35Z ##[error]Test timed out after 5000ms\n"},
    )
    use_settings(monkeypatch, fake, SETTINGS)
    return fake


def use_settings(monkeypatch: pytest.MonkeyPatch, fake: FakeActions, settings: Settings) -> None:
    @contextmanager
    def open_scan() -> Iterator[tuple[ScanService, Settings]]:
        with ScanCache.in_memory() as cache:
            yield ScanService(actions=fake, cache=cache, now=lambda: NOW), settings

    monkeypatch.setattr(wiring, "open_scan", open_scan)


def test_scan_prints_the_report(actions: FakeActions) -> None:
    result = runner.invoke(app, ["scan"])

    assert result.exit_code == 0, result.output
    text = click.unstyle(result.stdout)
    assert "octo-org on github.com" in text
    assert "1 flaky jobs" in text
    assert actions.windows[0].end - actions.windows[0].start == timedelta(days=14)


def test_scan_json_uses_options_over_config(actions: FakeActions) -> None:
    arguments = ["scan", "--json", "--days", "3", "--repo", "app", "--max-logs", "0"]
    result = runner.invoke(app, [*arguments, "--owner", "other-org"])

    assert result.exit_code == 0, result.output
    exported = json.loads(result.stdout)
    assert exported["owner"] == "other-org"
    assert exported["repositories"] == 1
    assert exported["logs_not_read"] == 1
    assert exported["window"]["start"] == "2026-10-06T12:00:00Z"
    assert "log octo-org/app 11" not in actions.calls


def test_no_owner_anywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    use_settings(monkeypatch, FakeActions(), Settings())

    result = runner.invoke(app, ["scan"])

    assert result.exit_code == 2
    assert "No owner configured" in click.unstyle(result.output)


class NotReady:
    def __enter__(self) -> tuple[ScanService, Settings]:
        message = "No usable gh found."
        raise wiring.NotReadyError(message)

    def __exit__(self, *_: object) -> None:
        return None


def test_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wiring, "open_scan", NotReady)

    result = runner.invoke(app, ["scan"])

    assert result.exit_code == 2
    assert "Not ready: No usable gh found." in click.unstyle(result.output)


def test_repositories_cannot_be_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeActions(repositories_error=GitHubApiError("gh: Not Found (HTTP 404)", 404))
    use_settings(monkeypatch, fake, SETTINGS)

    result = runner.invoke(app, ["scan"])

    assert result.exit_code == 1
    assert "GitHub: gh: Not Found (HTTP 404)" in click.unstyle(result.output)


def test_expired_login_points_to_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    error = GitHubApiError("HTTP 401: Bad credentials (https://api.github.com/graphql)", 401)
    use_settings(monkeypatch, FakeActions(repositories_error=error), SETTINGS)

    result = runner.invoke(app, ["scan"])

    assert result.exit_code == 1
    assert "Log in again with `flakipype setup`" in click.unstyle(result.output)


def test_incomplete_scan_exits_with_one(actions: FakeActions) -> None:
    actions.runs_by_repository["octo-org/docs"] = ApiRateLimitError("API rate limit exceeded", 403)

    result = runner.invoke(app, ["scan", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["complete"] is False


def test_progress_view_tracks_stages() -> None:
    display = progress_display(Console(file=io.StringIO(), force_terminal=True))

    with ProgressView(display) as view:
        view.update(Progress(Stage.RUNS, 1, 2, "octo-org/app"))

    task = display.tasks[0]
    assert (task.description, task.completed, task.total) == ("Reading workflow runs", 1, 2)
    assert task.fields["detail"] == "octo-org/app"


def test_progress_is_hidden_without_a_terminal() -> None:
    assert progress_display(Console(file=io.StringIO())).disable
