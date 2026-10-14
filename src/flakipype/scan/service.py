from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from functools import partial
from typing import Protocol

from flakipype.flaky.detection import FlakyFailure, attempts_to_inspect, find_flaky_failures
from flakipype.flaky.findings import Evidence, Finding, number_findings
from flakipype.flaky.model import AttemptRef, JobResult, WorkflowRun
from flakipype.flaky.recurring import (
    FailedJob,
    RecurringError,
    find_recurring_errors,
    latest_failed_attempts,
    unproven_failures,
)
from flakipype.flaky.scoring import FlakyKey, rank_flaky_jobs
from flakipype.flaky.signature import ErrorSignature, signature_from_log
from flakipype.flaky.verdict import FlakyRanking, classify
from flakipype.github.actions import (
    REPOSITORY_LIMIT,
    ApiRateLimitError,
    GitHubApiError,
    Repository,
    RunListing,
    TimeWindow,
)
from flakipype.scan.progress import Progress, ProgressListener, Stage, ignore_progress
from flakipype.store.database import LogResult, LogState, ScanCache

# Calls in a row that got no answer before a scan stops; each one can wait for gh's timeout.
NO_ANSWER_LIMIT = 5


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
    min_flaky_runs: int = 2
    repositories: tuple[str, ...] = ()
    max_job_reads: int = 500


class ScanStop(StrEnum):
    """Why a scan stopped before it read everything it could."""

    RATE_LIMIT = "GitHub's rate limit"
    TIME_LIMIT = "the time limit"
    NO_ANSWER = "GitHub not answering"


@dataclass(frozen=True)
class ScanReport:
    owner: str
    host: str
    window: TimeWindow
    repositories: int
    runs: int
    ranking: FlakyRanking
    recurring: list[RecurringError]
    problems: list[str]
    logs_not_read: int
    complete: bool
    evidence: Evidence = field(default_factory=Evidence)
    # Attempts whose jobs were not read yet (limit or early stop); later scans continue.
    attempts_not_read: int = 0
    stopped_by: ScanStop | None = None

    @property
    def findings(self) -> list[Finding]:
        return number_findings(self.ranking, self.recurring)


class _ScanStoppedError(Exception):
    """Stops a scan early; the report still contains everything found so far."""

    def __init__(self, reason: ScanStop, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


@dataclass
class _Scan:
    request: ScanRequest
    window: TimeWindow
    on_progress: ProgressListener
    out_of_time: Callable[[], bool]
    runs: list[WorkflowRun] = field(default_factory=list)
    jobs: dict[AttemptRef, list[JobResult]] = field(default_factory=dict)
    signatures: dict[int, ErrorSignature] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    logs_not_read: int = 0
    attempts_not_read: int = 0
    # Set by a stop: the later stages still load the cache but read nothing from GitHub.
    stopped_by: ScanStop | None = None
    no_answers_in_a_row: int = 0

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


def no_time_limit() -> bool:
    return False


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
        self,
        request: ScanRequest,
        on_progress: ProgressListener = ignore_progress,
        *,
        out_of_time: Callable[[], bool] = no_time_limit,
    ) -> ScanReport:
        """Raises GitHubApiError only if the repositories cannot be listed at all."""
        end = self._now()
        window = TimeWindow(end - timedelta(days=request.window_days), end)
        scan = _Scan(request, window, on_progress, out_of_time)
        on_progress(Progress(Stage.REPOSITORIES, 0, 1, request.owner))
        listed = self._actions.repositories(request.owner)
        if len(listed) > REPOSITORY_LIMIT:
            listed = listed[:REPOSITORY_LIMIT]
            scan.problems.append(
                f"{request.owner} has more than {REPOSITORY_LIMIT} repositories; only "
                f"{REPOSITORY_LIMIT} were scanned. Choose repositories with --repo."
            )
        repositories = select_repositories(listed, request.repositories)
        self._stage(scan, lambda: self._read_runs(scan, repositories))
        self._stage(scan, lambda: self._read_jobs(scan))
        to_read = self._cached_logs(scan)
        self._stage(scan, lambda: self._read_logs(scan, to_read))
        proven = find_flaky_failures(scan.runs, scan.jobs)
        unproven = unproven_failures(scan.runs, scan.jobs, proven)
        ranking = classify(
            rank_flaky_jobs(scan.runs, proven, scan.signatures), request.min_flaky_runs
        )
        return ScanReport(
            owner=request.owner,
            host=request.host,
            window=window,
            repositories=len(repositories),
            runs=len(scan.runs),
            ranking=ranking,
            recurring=find_recurring_errors(
                unproven, scan.signatures, request.min_flaky_runs, proven=_proven_errors(ranking)
            ),
            problems=scan.problems,
            logs_not_read=scan.logs_not_read,
            complete=scan.stopped_by is None,
            evidence=Evidence(scan.runs, scan.jobs, scan.signatures),
            attempts_not_read=scan.attempts_not_read,
            stopped_by=scan.stopped_by,
        )

    @staticmethod
    def _stage(scan: _Scan, read: Callable[[], None]) -> None:
        """A stop ends the stage; the scan keeps what it has."""
        try:
            read()
        except _ScanStoppedError as error:
            scan.problems.append(f"Stopped early: {error}. Run the scan again later.")
            scan.stopped_by = error.reason

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
        # Attempts that can be flaky, plus the last attempt of every failed run (recurring errors).
        created = {run.run_id: run.created_at for run in scan.runs}
        flaky = _newest_first(attempts_to_inspect(scan.runs), created)
        refs = list(
            dict.fromkeys([*flaky, *_newest_first(latest_failed_attempts(scan.runs), created)])
        )
        scan.jobs = self._cache.cached_jobs(scan.host, refs)
        missing = [ref for ref in refs if ref not in scan.jobs]
        to_read = [] if scan.stopped_by else missing[: scan.request.max_job_reads]
        scan.attempts_not_read = len(missing)
        repository_of = {run.run_id: run.repository for run in scan.runs}
        for done, ref in enumerate(to_read):
            repository = repository_of[ref.run_id]
            scan.on_progress(
                Progress(Stage.JOBS, done, len(to_read), f"{repository} #{ref.run_id}")
            )
            read = partial(self._actions.attempt_jobs, repository, ref.run_id, ref.attempt)
            action = f"read the jobs of run {ref.run_id}"
            jobs = _guarded(scan, read, repository=repository, action=action)
            scan.attempts_not_read -= 1
            if jobs is not None:
                self._cache.save_jobs(scan.host, ref, jobs)
                scan.jobs[ref] = jobs
        scan.on_progress(Progress(Stage.JOBS, len(to_read), len(to_read)))

    def _cached_logs(self, scan: _Scan) -> list[tuple[int, str]]:
        """Loads the cached log results; the logs still to read, as (job id, repository)."""
        proven = find_flaky_failures(scan.runs, scan.jobs)
        unproven = unproven_failures(scan.runs, scan.jobs, proven)
        # Proven flaky failures first, then the other failed jobs; newest first within each.
        ordered: list[FlakyFailure | FailedJob] = [
            *sorted(proven, key=lambda f: _seen_at(f.run, f.job), reverse=True),
            *sorted(unproven, key=lambda f: _seen_at(f.run, f.job), reverse=True),
        ]
        repository_of = {failure.job.job_id: failure.run.repository for failure in ordered}
        results = self._cache.log_results(scan.host, repository_of)
        scan.signatures = {job_id: r.signature for job_id, r in results.items() if r.signature}
        missing = [job_id for job_id in repository_of if job_id not in results]
        scan.logs_not_read = len(missing)
        return [(job_id, repository_of[job_id]) for job_id in missing]

    def _read_logs(self, scan: _Scan, missing: list[tuple[int, str]]) -> None:
        to_read = [] if scan.stopped_by else missing[: scan.request.max_log_downloads]
        for done, (job_id, repository) in enumerate(to_read):
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


def _newest_first(refs: Iterable[AttemptRef], created: dict[int, datetime]) -> list[AttemptRef]:
    return sorted(refs, key=lambda ref: created[ref.run_id], reverse=True)


def _proven_errors(ranking: FlakyRanking) -> frozenset[tuple[FlakyKey, str]]:
    """The errors of jobs proven flaky, so they are not listed again as recurring errors."""
    jobs = [*ranking.flaky, *ranking.seen_once, *ranking.fixed]
    return frozenset(
        (job.key, signature.fingerprint) for job in jobs for signature in job.signatures
    )


def _seen_at(run: WorkflowRun, job: JobResult) -> datetime:
    return job.completed_at or run.created_at


def _guarded[Result](
    scan: _Scan, call: Callable[[], Result], *, repository: str, action: str
) -> Result | None:
    """Run one GitHub call: a stop ends the scan, any other error skips this item."""
    if scan.out_of_time():
        raise _ScanStoppedError(ScanStop.TIME_LIMIT, "the time limit is reached")
    try:
        result = call()
    except ApiRateLimitError as error:
        raise _ScanStoppedError(ScanStop.RATE_LIMIT, str(error)) from error
    except GitHubApiError as error:
        scan.problems.append(f"{repository}: could not {action}: {error}")
        _count_no_answer(scan, error)
        return None
    scan.no_answers_in_a_row = 0
    return result


def _count_no_answer(scan: _Scan, error: GitHubApiError) -> None:
    scan.no_answers_in_a_row = scan.no_answers_in_a_row + 1 if error.is_no_answer else 0
    if scan.no_answers_in_a_row >= NO_ANSWER_LIMIT:
        detail = f"GitHub did not answer {NO_ANSWER_LIMIT} calls in a row"
        raise _ScanStoppedError(ScanStop.NO_ANSWER, detail) from error
