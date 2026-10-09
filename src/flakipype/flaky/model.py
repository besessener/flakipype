from dataclasses import dataclass
from datetime import datetime

FAILED_CONCLUSIONS = frozenset({"failure", "timed_out"})
COMPLETED_CONCLUSIONS = FAILED_CONCLUSIONS | {"success"}
# GitHub runs Dependabot and similar services as generated workflows without a file in the repo.
_GENERATED_WORKFLOW_PREFIX = "dynamic/"


@dataclass(frozen=True)
class WorkflowRun:
    repository: str
    run_id: int
    workflow_path: str
    workflow_name: str
    head_sha: str
    head_branch: str
    event: str
    attempt: int
    conclusion: str | None
    created_at: datetime
    url: str

    @property
    def succeeded(self) -> bool:
        return self.conclusion == "success"

    @property
    def failed(self) -> bool:
        return self.conclusion in FAILED_CONCLUSIONS

    @property
    def is_tracked(self) -> bool:
        return not self.workflow_path.startswith(_GENERATED_WORKFLOW_PREFIX)


@dataclass(frozen=True)
class AttemptRef:
    run_id: int
    attempt: int


@dataclass(frozen=True)
class JobResult:
    run_id: int
    attempt: int
    job_id: int
    name: str
    conclusion: str | None
    failed_step: str
    completed_at: datetime | None
    url: str

    @property
    def failed(self) -> bool:
        return self.conclusion in FAILED_CONCLUSIONS

    @property
    def attempt_ref(self) -> AttemptRef:
        return AttemptRef(self.run_id, self.attempt)
