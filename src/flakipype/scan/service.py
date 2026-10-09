from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from typing import Protocol

from flakipype.flaky.detection import FlakyFailure, attempts_to_inspect, find_flaky_failures
from flakipype.flaky.model import AttemptRef, JobResult, WorkflowRun
from flakipype.flaky.scoring import FlakyJob, rank_flaky_jobs
from flakipype.flaky.signature import ErrorSignature, signature_from_log
from flakipype.github.actions import (
    ApiRateLimitError,
    GitHubApiError,
    Repository,
    RunListing,
    TimeWindow,
)
from flakipype.scan.progress import Progress, ProgressListener, Stage, ignore_progress
from flakipype.store.database import LogResult, LogState, ScanCache


class ActionsSource(Protocol):
    def repositories(self, owner: str) -> list[Repository]: ...

    def runs(self, repository: str, window: TimeWindow) -> RunListing: ...

    def attempt_jobs(self, repository: str, run_id: int, attempt: int) -> list[JobResult]: ...

    def job_log(self, repository: str, job_id: int) -> str | None: ...


@dataclass(frozen=True)
class ScanRequest:
    owner: str
    host: str
    window_days: int
    max_log_downloads: int
    repositories: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScanReport:
    owner: str
    host: str
    window: TimeWindow
    repositories: int
    runs: int
    flaky: list[FlakyJob]
    problems: list[str]
    logs_not_read: int
    complete: bool


class _RateLimitReachedError(Exception):
    """Stops a scan early; the report still contains everything found so far."""


@dataclass
class _Scan:
    request: ScanRequest
    window: TimeWindow
    on_progress: ProgressListener
    runs: list[WorkflowRun] = field(default_factory=list)
    jobs: dict[AttemptRef, list[JobResult]] = field(default_factory=dict)
    signatures: dict[int, ErrorSignature] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    logs_not_read: int = 0

    @property
    def host(self) -> str:
        return self.request.host


def select_repositories(
    repositories: Sequence[Repository], names: Sequence[str]
) -> list[Repository]:
    """All repositories, or those matching a name given as `repo` or `owner/repo`."""
    if not names:
        return list(repositories)
    wanted = {name.lower() for name in names}
    return [
        repository
        for repository in repositories
        if {repository.full_name.lower(), repository.full_name.split("/")[-1].lower()} & wanted
    ]


def _log_result(log: str | None) -> LogResult:
    if log is None:
        return LogResult(LogState.UNAVAILABLE)
    signature = signature_from_log(log)
    if signature is None:
        return LogResult(LogState.NO_ERROR_LINES)
    return LogResult(LogState.SIGNATURE, signature)


class ScanService:
    def __init__(
        self, *, actions: ActionsSource, cache: ScanCache, now: Callable[[], datetime]
    ) -> None:
        self._actions = actions
        self._cache = cache
        self._now = now

    def scan(
        self, request: ScanRequest, on_progress: ProgressListener = ignore_progress
    ) -> ScanReport:
        """Raises GitHubApiError only if the repositories cannot be listed at all."""
        end = self._now()
        window = TimeWindow(end - timedelta(days=request.window_days), end)
        scan = _Scan(request, window, on_progress)
        on_progress(Progress(Stage.REPOSITORIES, 0, 1, request.owner))
        repositories = select_repositories(
            self._actions.repositories(request.owner), request.repositories
        )
        complete = True
        try:
            self._read_runs(scan, repositories)
            self._read_jobs(scan)
            self._read_logs(scan)
        except _RateLimitReachedError as error:
            complete = False
            scan.problems.append(f"Stopped early: {error}. Run the scan again later.")
        failures = find_flaky_failures(scan.runs, scan.jobs)
        return ScanReport(
            owner=request.owner,
            host=request.host,
            window=window,
            repositories=len(repositories),
            runs=len(scan.runs),
            flaky=rank_flaky_jobs(scan.runs, failures, scan.signatures),
            problems=scan.problems,
            logs_not_read=scan.logs_not_read,
            complete=complete,
        )

    def _read_runs(self, scan: _Scan, repositories: Sequence[Repository]) -> None:
        total = len(repositories)
        for done, repository in enumerate(repositories):
            name = repository.full_name
            scan.on_progress(Progress(Stage.RUNS, done, total, name))
            read = partial(self._actions.runs, name, scan.window)
            listing = _guarded(scan, read, repository=name, action="list runs")
            if listing is None:
                continue
            if listing.truncated:
                scan.problems.append(f"{name}: too many runs per minute; GitHub listed only some.")
            scan.runs.extend(listing.runs)
        scan.on_progress(Progress(Stage.RUNS, total, total))

    def _read_jobs(self, scan: _Scan) -> None:
        refs = list(attempts_to_inspect(scan.runs))
        scan.jobs = self._cache.cached_jobs(scan.host, refs)
        missing = [ref for ref in refs if ref not in scan.jobs]
        repository_of = {run.run_id: run.repository for run in scan.runs}
        for done, ref in enumerate(missing):
            repository = repository_of[ref.run_id]
            scan.on_progress(
                Progress(Stage.JOBS, done, len(missing), f"{repository} #{ref.run_id}")
            )
            read = partial(self._actions.attempt_jobs, repository, ref.run_id, ref.attempt)
            action = f"read the jobs of run {ref.run_id}"
            jobs = _guarded(scan, read, repository=repository, action=action)
            if jobs is not None:
                self._cache.save_jobs(scan.host, ref, jobs)
                scan.jobs[ref] = jobs
        scan.on_progress(Progress(Stage.JOBS, len(missing), len(missing)))

    def _read_logs(self, scan: _Scan) -> None:
        failures = sorted(find_flaky_failures(scan.runs, scan.jobs), key=_seen_at, reverse=True)
        repository_of = {failure.job.job_id: failure.run.repository for failure in failures}
        results = self._cache.log_results(scan.host, repository_of)
        scan.signatures = {job_id: r.signature for job_id, r in results.items() if r.signature}
        missing = [job_id for job_id in repository_of if job_id not in results]
        to_read = missing[: scan.request.max_log_downloads]
        scan.logs_not_read = len(missing)
        for done, job_id in enumerate(to_read):
            repository = repository_of[job_id]
            scan.on_progress(Progress(Stage.LOGS, done, len(to_read), f"{repository} job {job_id}"))
            read = partial(self._read_log, repository, job_id)
            action = f"read the log of job {job_id}"
            result = _guarded(scan, read, repository=repository, action=action)
            scan.logs_not_read -= 1
            if result is not None:
                self._cache.save_log_result(scan.host, job_id, result)
                if result.signature:
                    scan.signatures[job_id] = result.signature
        scan.on_progress(Progress(Stage.LOGS, len(to_read), len(to_read)))

    def _read_log(self, repository: str, job_id: int) -> LogResult:
        return _log_result(self._actions.job_log(repository, job_id))


def _seen_at(failure: FlakyFailure) -> datetime:
    return failure.job.completed_at or failure.run.created_at


def _guarded[Result](
    scan: _Scan, call: Callable[[], Result], *, repository: str, action: str
) -> Result | None:
    """Run one GitHub call: a rate limit stops the scan, any other error skips this item."""
    try:
        return call()
    except ApiRateLimitError as error:
        raise _RateLimitReachedError(str(error)) from error
    except GitHubApiError as error:
        scan.problems.append(f"{repository}: could not {action}: {error}")
        return None
