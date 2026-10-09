"""Start, cancel and watch workflow runs through `gh api`."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import quote, urlencode

from flakipype.github.actions import api_error, parse_answer
from flakipype.github.gh import GhCli
from flakipype.github.payloads import (
    BranchPayload,
    DispatchPayload,
    GitRefPayload,
    JobStatesPage,
    LoginPayload,
    RepositoryDetailsPayload,
    RunsPage,
    RunStatePayload,
)

_HTTP_NOT_FOUND = 404
_JOBS_SHOWN = 100
_DISPATCHED_RUNS_LISTED = 20


@dataclass(frozen=True)
class RunState:
    run_id: int
    workflow_name: str
    status: str
    conclusion: str | None
    attempt: int
    head_sha: str
    head_branch: str
    url: str

    @property
    def completed(self) -> bool:
        return self.status == "completed"


@dataclass(frozen=True)
class JobState:
    name: str
    status: str
    conclusion: str | None


@dataclass(frozen=True)
class CommitRun:
    run_id: int
    event: str


def workflow_file(workflow_path: str) -> str:
    """GitHub accepts a workflow's file name wherever it wants a workflow id."""
    return quote(PurePosixPath(workflow_path).name, safe="")


class RunControl:
    def __init__(self, gh: GhCli) -> None:
        self._gh = gh

    def rerun_failed_jobs(self, repository: str, run_id: int) -> None:
        self._post(f"repos/{repository}/actions/runs/{run_id}/rerun-failed-jobs")

    def rerun(self, repository: str, run_id: int) -> None:
        self._post(f"repos/{repository}/actions/runs/{run_id}/rerun")

    def cancel(self, repository: str, run_id: int) -> None:
        self._post(f"repos/{repository}/actions/runs/{run_id}/cancel")

    def dispatch(self, repository: str, workflow_path: str, ref: str) -> int | None:
        """The new run's id; None where GitHub does not return it (older Enterprise Server)."""
        path = f"repos/{repository}/actions/workflows/{workflow_file(workflow_path)}/dispatches"
        output = self._post(path, "-f", f"ref={ref}")
        if not output.strip():
            return None
        return parse_answer(DispatchPayload.model_validate_json, output).workflow_run_id

    def dispatched_runs(
        self, repository: str, workflow_path: str, *, ref: str, since: datetime
    ) -> list[int]:
        """Ids of runs the logged-in user dispatched on `ref` since `since`, oldest first."""
        query = urlencode(
            {
                "event": "workflow_dispatch",
                "branch": ref,
                "actor": self.login(),
                "created": f">={since.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                "per_page": _DISPATCHED_RUNS_LISTED,
            },
            safe=":>=",
        )
        path = f"repos/{repository}/actions/workflows/{workflow_file(workflow_path)}/runs?{query}"
        page = parse_answer(RunsPage.model_validate_json, self._get(path))
        return sorted(run.id for run in page.workflow_runs)

    def commit_runs(self, repository: str, workflow_path: str, commit: str) -> list[CommitRun]:
        """Runs of the workflow on one commit, oldest first."""
        query = urlencode({"head_sha": commit, "per_page": _DISPATCHED_RUNS_LISTED})
        path = f"repos/{repository}/actions/workflows/{workflow_file(workflow_path)}/runs?{query}"
        page = parse_answer(RunsPage.model_validate_json, self._get(path))
        runs = sorted(page.workflow_runs, key=lambda run: run.created_at)
        return [CommitRun(run.id, run.event) for run in runs]

    def login(self) -> str:
        return parse_answer(LoginPayload.model_validate_json, self._get("user")).login

    def run_state(self, repository: str, run_id: int) -> RunState:
        output = self._get(f"repos/{repository}/actions/runs/{run_id}")
        run = parse_answer(RunStatePayload.model_validate_json, output)
        return RunState(
            run_id=run.id,
            workflow_name=run.name or run.path,
            status=run.status,
            conclusion=run.conclusion,
            attempt=run.run_attempt,
            head_sha=run.head_sha,
            head_branch=run.head_branch or "",
            url=run.html_url,
        )

    def job_states(self, repository: str, run_id: int, attempt: int) -> list[JobState]:
        path = (
            f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs"
            f"?per_page={_JOBS_SHOWN}"
        )
        page = parse_answer(JobStatesPage.model_validate_json, self._get(path))
        return [JobState(job.name, job.status, job.conclusion) for job in page.jobs]

    def default_branch(self, repository: str) -> str:
        output = self._get(f"repos/{repository}")
        return parse_answer(RepositoryDetailsPayload.model_validate_json, output).default_branch

    def ref_commit(self, repository: str, ref: str) -> str | None:
        """The commit a branch or tag points to; None if it is neither."""
        name = quote(ref, safe="")
        branch = self._get_or_none(f"repos/{repository}/branches/{name}")
        if branch is not None:
            return parse_answer(BranchPayload.model_validate_json, branch).commit.sha
        tag = self._get_or_none(f"repos/{repository}/git/ref/tags/{name}")
        if tag is not None:
            return parse_answer(GitRefPayload.model_validate_json, tag).object.sha
        return None

    def _post(self, path: str, *fields: str) -> str:
        result = self._gh.run(["api", "-X", "POST", path, *fields])
        if not result.succeeded:
            raise api_error(result)
        return result.stdout

    def _get(self, path: str) -> str:
        result = self._gh.run(["api", path])
        if not result.succeeded:
            raise api_error(result)
        return result.stdout

    def _get_or_none(self, path: str) -> str | None:
        result = self._gh.run(["api", path])
        if result.succeeded:
            return result.stdout
        error = api_error(result)
        if error.status == _HTTP_NOT_FOUND:
            return None
        raise error
