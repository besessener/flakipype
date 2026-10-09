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


class CommitAuthor(BaseModel):
    model_config = _IGNORE_EXTRA

    name: str = ""
    date: datetime | None = None


class CommitDetails(BaseModel):
    model_config = _IGNORE_EXTRA

    message: str
    author: CommitAuthor = CommitAuthor()


class CommitPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    sha: str
    commit: CommitDetails


class ChangedFilePayload(BaseModel):
    model_config = _IGNORE_EXTRA

    filename: str
    status: str
    additions: int = 0
    deletions: int = 0
    patch: str = ""


class ComparisonPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    total_commits: int
    commits: list[CommitPayload]
    files: list[ChangedFilePayload] = []


class JobsPage(BaseModel):
    model_config = _IGNORE_EXTRA

    total_count: int
    jobs: list[JobPayload]


class RunStatePayload(BaseModel):
    """A run as `GET …/actions/runs/{id}` returns it, for watching."""

    model_config = _IGNORE_EXTRA

    id: int
    name: str | None = None
    path: str
    status: str
    conclusion: str | None = None
    run_attempt: int = 1
    head_sha: str
    head_branch: str | None = None
    html_url: str


class JobStatePayload(BaseModel):
    model_config = _IGNORE_EXTRA

    name: str
    status: str
    conclusion: str | None = None


class JobStatesPage(BaseModel):
    model_config = _IGNORE_EXTRA

    jobs: list[JobStatePayload]


class DispatchPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    workflow_run_id: int


class ShaPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    sha: str


class BranchPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    commit: ShaPayload


class GitRefPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    object: ShaPayload


class RepositoryDetailsPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    default_branch: str


class LoginPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    login: str


class PermissionsPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    push: bool = False


class RepositoryAccessPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    default_branch: str
    permissions: PermissionsPayload = PermissionsPayload()


class FileContentPayload(BaseModel):
    """`GET …/contents/{path}` for a file: base64 content, or none above GitHub's size limit."""

    model_config = _IGNORE_EXTRA

    type: str
    encoding: str = ""
    content: str = ""


class TreeEntryPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    path: str
    type: str


class TreePayload(BaseModel):
    model_config = _IGNORE_EXTRA

    truncated: bool = False
    tree: list[TreeEntryPayload]


class PullHeadPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    ref: str


class PullPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    number: int
    html_url: str
    body: str | None = None
    head: PullHeadPayload


class CommitOidPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    oid: str


class CreatedCommitPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    commit: CommitOidPayload


class CommitMutationData(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    created: CreatedCommitPayload = Field(alias="createCommitOnBranch")


class CommitMutationPayload(BaseModel):
    model_config = _IGNORE_EXTRA

    data: CommitMutationData
