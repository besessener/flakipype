from datetime import UTC, datetime, timedelta

from flakipype.flaky.model import JobResult, WorkflowRun

START = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def run(
    run_id: int,
    *,
    conclusion: str | None = "success",
    attempt: int = 1,
    sha: str = "a" * 40,
    workflow: str = ".github/workflows/ci.yml",
    repository: str = "octo-org/app",
    name: str = "CI",
) -> WorkflowRun:
    return WorkflowRun(
        repository=repository,
        run_id=run_id,
        workflow_path=workflow,
        workflow_name=name,
        head_sha=sha,
        head_branch="main",
        event="push",
        attempt=attempt,
        conclusion=conclusion,
        created_at=START + timedelta(hours=run_id),
        url=f"https://github.com/{repository}/actions/runs/{run_id}",
    )


def job(
    job_id: int,
    *,
    run_id: int,
    attempt: int = 1,
    conclusion: str | None = "failure",
    name: str = "test",
    step: str = "Run tests",
    completed_at: datetime | None = None,
) -> JobResult:
    return JobResult(
        run_id=run_id,
        attempt=attempt,
        job_id=job_id,
        name=name,
        conclusion=conclusion,
        failed_step=step if conclusion in {"failure", "timed_out"} else "",
        completed_at=completed_at or START + timedelta(hours=run_id, minutes=attempt),
        url=f"https://github.com/octo-org/app/actions/runs/{run_id}/job/{job_id}",
    )
