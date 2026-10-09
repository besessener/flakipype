from dataclasses import dataclass, field

from flakipype.flaky.model import JobResult, WorkflowRun
from flakipype.github.actions import Repository, RunListing, TimeWindow


@dataclass
class FakeActions:
    """In-memory GitHub: answers from dictionaries, raises stored exceptions, counts calls."""

    repositories_found: list[Repository] = field(default_factory=list)
    repositories_error: Exception | None = None
    runs_by_repository: dict[str, list[WorkflowRun] | Exception] = field(default_factory=dict)
    truncated: set[str] = field(default_factory=set)
    jobs_by_attempt: dict[tuple[int, int], list[JobResult] | Exception] = field(
        default_factory=dict
    )
    logs: dict[int, str | Exception | None] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    windows: list[TimeWindow] = field(default_factory=list)

    def repositories(self, owner: str) -> list[Repository]:
        self.calls.append(f"repositories {owner}")
        if self.repositories_error is not None:
            raise self.repositories_error
        return self.repositories_found

    def runs(self, repository: str, window: TimeWindow) -> RunListing:
        self.calls.append(f"runs {repository}")
        self.windows.append(window)
        runs = self.runs_by_repository.get(repository, [])
        if isinstance(runs, Exception):
            raise runs
        return RunListing(runs, truncated=repository in self.truncated)

    def attempt_jobs(self, repository: str, run_id: int, attempt: int) -> list[JobResult]:
        self.calls.append(f"jobs {repository} {run_id}/{attempt}")
        jobs = self.jobs_by_attempt.get((run_id, attempt), [])
        if isinstance(jobs, Exception):
            raise jobs
        return jobs

    def job_log(self, repository: str, job_id: int) -> str | None:
        self.calls.append(f"log {repository} {job_id}")
        log = self.logs.get(job_id)
        if isinstance(log, Exception):
            raise log
        return log
