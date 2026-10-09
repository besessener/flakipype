import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from flakipype.github.actions import (
    ActionsClient,
    ApiRateLimitError,
    GitHubApiError,
    Repository,
    TimeWindow,
)

from support.fake_gh import FakeGh, gh_fixture

REPO = "besessener/Archivist"
WINDOW = TimeWindow(datetime(2026, 9, 9, tzinfo=UTC), datetime(2026, 10, 9, tzinfo=UTC))


def runs_call(window: TimeWindow, page: int = 1) -> list[str]:
    query = f"per_page=100&page={page}&created={window.query}&exclude_pull_requests=true"
    return ["api", f"repos/{REPO}/actions/runs?{query}"]


def runs_page(total: int, run_ids: list[int]) -> str:
    template = json.loads(gh_fixture("runs-page.json"))["workflow_runs"][0]
    return json.dumps(
        {"total_count": total, "workflow_runs": [{**template, "id": rid} for rid in run_ids]}
    )


def jobs_call(page: int) -> list[str]:
    return ["api", f"repos/{REPO}/actions/runs/7/attempts/1/jobs?per_page=100&page={page}"]


def test_repositories_from_gh_repo_list(fake_gh: FakeGh) -> None:
    entries: list[dict[str, Any]] = json.loads(gh_fixture("repo-list.json"))
    entries.append({"nameWithOwner": "besessener/empty", "defaultBranchRef": None})
    arguments = ["repo", "list", "besessener", "--no-archived", "--source", "--limit", "1000"]
    fake_gh.record(
        [*arguments, "--json", "nameWithOwner,defaultBranchRef"], stdout=json.dumps(entries)
    )

    repositories = ActionsClient(fake_gh.cli()).repositories("besessener")

    assert repositories[:2] == [
        Repository("besessener/flakipype", "main"),
        Repository("besessener/Archivist", "main"),
    ]
    assert repositories[-1] == Repository("besessener/empty", "")


def test_recorded_run_is_parsed(fake_gh: FakeGh) -> None:
    fake_gh.record(runs_call(WINDOW), stdout=gh_fixture("runs-page.json"))

    listing = ActionsClient(fake_gh.cli()).runs(REPO, WINDOW)

    (run,) = listing.runs
    assert not listing.truncated
    assert (run.run_id, run.workflow_name, run.workflow_path) == (
        37599586878,
        "CI",
        ".github/workflows/ci.yml",
    )
    assert (run.attempt, run.conclusion, run.repository) == (2, "success", REPO)
    assert run.created_at.tzinfo is not None


def test_runs_are_read_page_by_page(fake_gh: FakeGh) -> None:
    fake_gh.record(runs_call(WINDOW), stdout=runs_page(150, list(range(100))))
    fake_gh.record(runs_call(WINDOW, page=2), stdout=runs_page(150, list(range(100, 150))))

    listing = ActionsClient(fake_gh.cli()).runs(REPO, WINDOW)

    assert len(listing.runs) == 150


def test_window_is_split_when_github_would_cap_the_listing(fake_gh: FakeGh) -> None:
    earlier, later = WINDOW.halves()
    fake_gh.record(runs_call(WINDOW), stdout=runs_page(1500, [1]))
    fake_gh.record(runs_call(earlier), stdout=runs_page(2, [1, 2]))
    fake_gh.record(runs_call(later), stdout=runs_page(2, [2, 3]))

    listing = ActionsClient(fake_gh.cli()).runs(REPO, WINDOW)

    assert sorted(run.run_id for run in listing.runs) == [1, 2, 2, 3]
    assert not listing.truncated
    assert later.start == earlier.end + timedelta(seconds=1)


def test_a_full_minute_cannot_be_split_further(fake_gh: FakeGh) -> None:
    minute = TimeWindow(WINDOW.start, WINDOW.start + timedelta(minutes=1))
    fake_gh.record(runs_call(minute), stdout=runs_page(1200, [1, 1]))
    for page in range(2, 11):
        fake_gh.record(runs_call(minute, page), stdout=runs_page(1200, [page]))

    listing = ActionsClient(fake_gh.cli()).runs(REPO, minute)

    assert listing.truncated
    assert len(listing.runs) == 10


def test_recorded_jobs_are_parsed(fake_gh: FakeGh) -> None:
    fake_gh.record(jobs_call(1), stdout=gh_fixture("attempt-jobs.json"))

    jobs = ActionsClient(fake_gh.cli()).attempt_jobs(REPO, 7, 1)

    failed = [job for job in jobs if job.failed]
    assert [(job.name, job.failed_step) for job in failed] == [
        ("test", "E2E (Electron under Xvfb)")
    ]
    assert [job.failed_step for job in jobs if not job.failed] == ["", "", ""]
    assert failed[0].attempt == 1
    assert failed[0].url.endswith("/job/112720402394")


def test_jobs_are_read_page_by_page(fake_gh: FakeGh) -> None:
    template = json.loads(gh_fixture("attempt-jobs.json"))["jobs"][0]
    first = {"total_count": 3, "jobs": [{**template, "id": 1}, {**template, "id": 2}]}
    fake_gh.record(jobs_call(1), stdout=json.dumps(first))
    fake_gh.record(jobs_call(2), stdout=json.dumps({"total_count": 3, "jobs": []}))

    jobs = ActionsClient(fake_gh.cli()).attempt_jobs(REPO, 7, 1)

    assert [job.job_id for job in jobs] == [1, 2]


def test_job_log(fake_gh: FakeGh) -> None:
    log_call = ["api", f"repos/{REPO}/actions/jobs/5/logs", "--allow-escape-sequences"]
    fake_gh.record(log_call, stdout="2026-10-07T09:27:35Z ##[error]boom\n")

    assert ActionsClient(fake_gh.cli()).job_log(REPO, 5) == "2026-10-07T09:27:35Z ##[error]boom\n"


@pytest.mark.parametrize("status", [404, 410])
def test_expired_log_is_none(fake_gh: FakeGh, status: int) -> None:
    log_call = ["api", f"repos/{REPO}/actions/jobs/5/logs", "--allow-escape-sequences"]
    fake_gh.record(log_call, stderr=f"gh: Gone (HTTP {status})\n", exit_code=1)

    assert ActionsClient(fake_gh.cli()).job_log(REPO, 5) is None


def test_other_log_errors_raise(fake_gh: FakeGh) -> None:
    log_call = ["api", f"repos/{REPO}/actions/jobs/5/logs", "--allow-escape-sequences"]
    fake_gh.record(log_call, stderr="gh: Server Error (HTTP 500)\n", exit_code=1)

    with pytest.raises(GitHubApiError) as error:
        ActionsClient(fake_gh.cli()).job_log(REPO, 5)

    assert error.value.status == 500


def test_rate_limit_is_its_own_error(fake_gh: FakeGh) -> None:
    message = "gh: API rate limit exceeded for user ID 1. (HTTP 403)\n"
    fake_gh.record(runs_call(WINDOW), stderr=message, exit_code=1)

    with pytest.raises(ApiRateLimitError) as error:
        ActionsClient(fake_gh.cli()).runs(REPO, WINDOW)

    assert error.value.status == 403


def test_status_written_without_parentheses(fake_gh: FakeGh) -> None:
    arguments = ["repo", "list", "octo-org", "--no-archived", "--source", "--limit", "1000"]
    message = "HTTP 401: Bad credentials (https://api.github.com/graphql)\n"
    fake_gh.record(
        [*arguments, "--json", "nameWithOwner,defaultBranchRef"], stderr=message, exit_code=1
    )

    with pytest.raises(GitHubApiError) as error:
        ActionsClient(fake_gh.cli()).repositories("octo-org")

    assert error.value.status == 401
    assert error.value.is_authentication_problem


def test_errors_without_http_status_and_message(fake_gh: FakeGh) -> None:
    fake_gh.record(runs_call(WINDOW), exit_code=1)

    with pytest.raises(GitHubApiError, match="exited with code 1") as error:
        ActionsClient(fake_gh.cli()).runs(REPO, WINDOW)

    assert error.value.status is None


def test_unexpected_answer_is_an_api_error(fake_gh: FakeGh) -> None:
    fake_gh.record(runs_call(WINDOW), stdout='{"total_count": "many"}')

    with pytest.raises(GitHubApiError, match="Unexpected answer"):
        ActionsClient(fake_gh.cli()).runs(REPO, WINDOW)
