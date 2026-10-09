"""In-memory run control and workflow files: answers from dictionaries, records every call."""

from dataclasses import dataclass, field
from datetime import datetime

from flakipype.flaky.findings import Evidence, Finding, FindingKind
from flakipype.flaky.scoring import FlakyKey
from flakipype.github.runs import JobState, RunState

from support.builders import START, job, run

APP = "octo-org/app"
E2E = ".github/workflows/e2e.yml"
DISPATCHABLE = "on:\n  workflow_dispatch:\n  push:\njobs: {}\n"


def state(
    run_id: int,
    *,
    status: str = "completed",
    conclusion: str | None = "failure",
    attempt: int = 1,
    name: str = "E2E",
) -> RunState:
    return RunState(
        run_id=run_id, workflow_name=name, status=status, conclusion=conclusion,
        attempt=attempt, head_sha="3f2a9c1" + "0" * 33, head_branch="main",
        url=f"https://github.com/{APP}/actions/runs/{run_id}",
    )  # fmt: skip


@dataclass
class FakeRuns:
    # Successive answers per run id; the last one repeats.
    states: dict[int, list[RunState | Exception]] = field(default_factory=dict)
    jobs: dict[tuple[int, int], list[JobState]] = field(default_factory=dict)
    refs: dict[str, str] = field(default_factory=lambda: {"main": "3f2a9c1" + "0" * 33})
    files: dict[tuple[str, str], str] = field(default_factory=dict)
    dispatch_ids: list[int | None] = field(default_factory=list)
    found: list[int] = field(default_factory=list)
    errors: dict[str, Exception] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def _call(self, call: str) -> None:
        self.calls.append(call)
        error = self.errors.get(call.split(maxsplit=1)[0])
        if error is not None:
            raise error

    def rerun_failed_jobs(self, repository: str, run_id: int) -> None:
        self._call(f"rerun_failed_jobs {repository} {run_id}")

    def rerun(self, repository: str, run_id: int) -> None:
        self._call(f"rerun {repository} {run_id}")

    def cancel(self, repository: str, run_id: int) -> None:
        self._call(f"cancel {repository} {run_id}")

    def dispatch(self, repository: str, workflow_path: str, ref: str) -> int | None:
        self._call(f"dispatch {repository} {workflow_path} {ref}")
        return self.dispatch_ids.pop(0) if self.dispatch_ids else None

    def dispatched_runs(
        self, repository: str, workflow_path: str, *, ref: str, since: datetime
    ) -> list[int]:
        self._call(f"dispatched_runs {repository} {workflow_path} {ref} {since:%H:%M}")
        return list(self.found)

    def run_state(self, repository: str, run_id: int) -> RunState:
        self._call(f"run_state {repository} {run_id}")
        answers = self.states[run_id]
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def job_states(self, repository: str, run_id: int, attempt: int) -> list[JobState]:
        self._call(f"job_states {repository} {run_id}/{attempt}")
        return self.jobs.get((run_id, attempt), [])

    def default_branch(self, repository: str) -> str:
        self._call(f"default_branch {repository}")
        return "main"

    def ref_commit(self, repository: str, ref: str) -> str | None:
        self._call(f"ref_commit {repository} {ref}")
        return self.refs.get(ref)

    def file_content(self, repository: str, path: str, ref: str) -> str | None:
        self._call(f"file_content {repository} {path} {ref[:7]}")
        return self.files.get((path, ref[:7]))


def e2e_finding(number: int = 2, *, repository: str = APP) -> Finding:
    """E2E failed in runs 4 (newest, attempt 1) and 3 (passed on attempt 2)."""
    key = FlakyKey(repository, E2E, "E2E", "e2e", "Run tests")
    return Finding(number, FindingKind.FLAKY, key, ("Status: flaky",), (31, 41), START)


def e2e_evidence(*, newest: str = "failure") -> Evidence:
    runs = [
        run(3, attempt=2, workflow=E2E, name="E2E"),
        run(4, conclusion=newest, workflow=E2E, name="E2E"),
        run(5, workflow=E2E, name="E2E"),
    ]
    jobs = {
        ref.attempt_ref: [ref]
        for ref in (job(31, run_id=3, name="e2e"), job(41, run_id=4, name="e2e"))
    }
    return Evidence(runs, jobs)
