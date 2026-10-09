"""Read repositories, workflow runs, jobs and logs through `gh api`."""

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

from pydantic import TypeAdapter, ValidationError

from flakipype.flaky.model import JobResult, WorkflowRun
from flakipype.github.gh import GhCli, GhResult
from flakipype.github.payloads import JobsPage, RepositoryPayload, RunsPage

# GitHub returns at most this many results for one filtered run listing.
RUN_LISTING_CAP = 1000
PAGE_SIZE = 100
_REPOSITORY_LIMIT = "1000"
_SMALLEST_WINDOW = timedelta(minutes=1)
_HTTP_STATUS = re.compile(r"\bHTTP (\d{3})\b")
_RATE_LIMIT = re.compile(r"rate limit", re.IGNORECASE)
_HTTP_UNAUTHORIZED = 401
_HTTP_NOT_FOUND = 404
_HTTP_GONE = 410
_REPOSITORIES = TypeAdapter(list[RepositoryPayload])


class GitHubApiError(Exception):
    def __init__(self, detail: str, status: int | None = None) -> None:
        super().__init__(detail)
        self.status = status

    @property
    def is_authentication_problem(self) -> bool:
        return self.status == _HTTP_UNAUTHORIZED


class ApiRateLimitError(GitHubApiError):
    """GitHub's API rate limit for this token is used up."""


@dataclass(frozen=True)
class Repository:
    full_name: str
    default_branch: str


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime

    @property
    def query(self) -> str:
        return f"{_iso(self.start)}..{_iso(self.end)}"

    def halves(self) -> tuple["TimeWindow", "TimeWindow"]:
        middle = self.start + (self.end - self.start) / 2
        return TimeWindow(self.start, middle), TimeWindow(middle + timedelta(seconds=1), self.end)


@dataclass(frozen=True)
class RunListing:
    runs: list[WorkflowRun]
    # True when even a one-minute window held more runs than GitHub returns; some were missed.
    truncated: bool


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def api_error(result: GhResult) -> GitHubApiError:
    """The typed error for a failed gh call: rate limit, authentication or other."""
    detail = result.stderr.strip() or f"gh exited with code {result.exit_code}"
    match = _HTTP_STATUS.search(detail)
    status = int(match.group(1)) if match else None
    if _RATE_LIMIT.search(detail):
        return ApiRateLimitError(detail, status)
    return GitHubApiError(detail, status)


class ActionsClient:
    def __init__(self, gh: GhCli) -> None:
        self._gh = gh

    def repositories(self, owner: str) -> list[Repository]:
        """Repositories the owner owns, without archived ones and forks."""
        fields = "nameWithOwner,defaultBranchRef"
        listing = ["repo", "list", owner, "--no-archived", "--source", "--limit", _REPOSITORY_LIMIT]
        output = self._run([*listing, "--json", fields])
        payloads = parse_answer(_REPOSITORIES.validate_json, output)
        return [
            Repository(
                item.name_with_owner, item.default_branch.name if item.default_branch else ""
            )
            for item in payloads
        ]

    def runs(self, repository: str, window: TimeWindow) -> RunListing:
        first = self._runs_page(repository, window, page=1)
        if first.total_count > RUN_LISTING_CAP:
            if window.end - window.start <= _SMALLEST_WINDOW:
                return RunListing(self._all_pages(repository, window, first), truncated=True)
            earlier, later = window.halves()
            older, newer = self.runs(repository, earlier), self.runs(repository, later)
            return RunListing(older.runs + newer.runs, older.truncated or newer.truncated)
        return RunListing(self._all_pages(repository, window, first), truncated=False)

    def _all_pages(self, repository: str, window: TimeWindow, first: RunsPage) -> list[WorkflowRun]:
        payloads = list(first.workflow_runs)
        pages = math.ceil(min(first.total_count, RUN_LISTING_CAP) / PAGE_SIZE)
        for page in range(2, pages + 1):
            payloads.extend(self._runs_page(repository, window, page).workflow_runs)
        unique = {payload.id: payload for payload in payloads}
        return [payload.to_run(repository) for payload in unique.values()]

    def _runs_page(self, repository: str, window: TimeWindow, page: int) -> RunsPage:
        query = urlencode(
            {"per_page": PAGE_SIZE, "page": page, "created": window.query},
            safe=":.",
        )
        output = self._run(
            ["api", f"repos/{repository}/actions/runs?{query}&exclude_pull_requests=true"]
        )
        return parse_answer(RunsPage.model_validate_json, output)

    def attempt_jobs(self, repository: str, run_id: int, attempt: int) -> list[JobResult]:
        jobs: list[JobResult] = []
        page = 1
        while True:
            query = urlencode({"per_page": PAGE_SIZE, "page": page})
            path = f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs?{query}"
            output = self._run(["api", path])
            payload = parse_answer(JobsPage.model_validate_json, output)
            jobs.extend(job.to_job() for job in payload.jobs)
            if len(jobs) >= payload.total_count or not payload.jobs:
                return jobs
            page += 1

    def job_log(self, repository: str, job_id: int) -> str | None:
        """The raw log, or None when GitHub no longer has it (expired or deleted)."""
        path = f"repos/{repository}/actions/jobs/{job_id}/logs"
        # Logs are untrusted; flakipype strips escape sequences itself before showing anything.
        result = self._gh.run(["api", path, "--allow-escape-sequences"])
        if result.succeeded:
            return result.stdout
        error = api_error(result)
        if error.status in {_HTTP_NOT_FOUND, _HTTP_GONE}:
            return None
        raise error

    def _run(self, arguments: list[str]) -> str:
        result = self._gh.run(arguments)
        if not result.succeeded:
            raise api_error(result)
        return result.stdout


def parse_answer[Parsed](parse: Callable[[str], Parsed], text: str) -> Parsed:
    try:
        return parse(text)
    except (ValidationError, json.JSONDecodeError) as error:
        message = f"Unexpected answer from GitHub: {error}"
        raise GitHubApiError(message) from error
