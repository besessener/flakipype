"""The parts of GitHub's REST responses flakipype reads, validated at the boundary."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from flakipype.flaky.model import JobResult, WorkflowRun

_IGNORE_EXTRA = ConfigDict(extra="ignore", frozen=True)


class DefaultBranch(BaseModel):
    model_config = _IGNORE_EXTRA

    name: str


class RepositoryPayload(BaseModel):
    """One entry of `gh repo list --json nameWithOwner,defaultBranchRef`."""

    model_config = _IGNORE_EXTRA

    name_with_owner: str = Field(alias="nameWithOwner")
    default_branch: DefaultBranch | None = Field(default=None, alias="defaultBranchRef")


class RunPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    id: int
    name: str | None = None
    path: str
    head_sha: str
    head_branch: str | None = None
    event: str
    conclusion: str | None = None
    run_attempt: int = 1
    created_at: datetime
    html_url: str

    def to_run(self, repository: str) -> WorkflowRun:
        return WorkflowRun(
            repository=repository,
            run_id=self.id,
            workflow_path=self.path,
            workflow_name=self.name or self.path,
            head_sha=self.head_sha,
            head_branch=self.head_branch or "",
            event=self.event,
            attempt=self.run_attempt,
            conclusion=self.conclusion,
            created_at=self.created_at,
            url=self.html_url,
        )


class RunsPage(BaseModel):
    model_config = _IGNORE_EXTRA

    total_count: int
    workflow_runs: list[RunPayload]


class StepPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    name: str
    conclusion: str | None = None


class JobPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    id: int
    run_id: int
    run_attempt: int = 1
    name: str
    conclusion: str | None = None
    completed_at: datetime | None = None
    html_url: str
    steps: list[StepPayload] = []

    def to_job(self) -> JobResult:
        failed_steps = [step.name for step in self.steps if step.conclusion == "failure"]
        return JobResult(
            run_id=self.run_id,
            attempt=self.run_attempt,
            job_id=self.id,
            name=self.name,
            conclusion=self.conclusion,
            failed_step=failed_steps[0] if failed_steps else "",
            completed_at=self.completed_at,
            url=self.html_url,
        )


class JobsPage(BaseModel):
    model_config = _IGNORE_EXTRA

    total_count: int
    jobs: list[JobPayload]
