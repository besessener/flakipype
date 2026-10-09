"""Runs started in this session: numbered R1, R2, … and polled until they finish."""

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from flakipype.actions.api import RunApi
from flakipype.flaky.model import FAILED_CONCLUSIONS
from flakipype.github.actions import ApiRateLimitError, GitHubApiError
from flakipype.github.runs import JobState

# GitHub's clock and ours differ a little; a dispatched run may look older than the dispatch.
_DISPATCH_SLACK = timedelta(minutes=2)
_SECONDS_PER_HOUR = 3600


class RunKind(StrEnum):
    RERUN = "rerun"
    DISPATCH = "dispatch"


@dataclass(frozen=True)
class WatchedRun:
    number: int
    kind: RunKind
    repository: str
    workflow_path: str
    workflow_name: str
    label: str
    commit: str
    ref: str
    started: datetime
    # None until a dispatched run shows up where GitHub does not return its id.
    run_id: int | None
    # The attempt with the result: the next one for a rerun, 1 for a dispatch.
    attempt: int
    # A rerun's previous conclusion; for a dispatch, the R number of the first run of its group.
    before: str | None = None
    group: int | None = None
    status: str = "queued"
    conclusion: str | None = None
    detail: str = ""
    done: bool = False

    @property
    def title(self) -> str:
        return f"{self.repository.split('/')[-1]} · {self.workflow_name} {self.label}"

    @property
    def state(self) -> str:
        if self.conclusion == "success":
            return "✓ passed"
        if self.conclusion in FAILED_CONCLUSIONS:
            return "✗ failed"
        if self.conclusion:
            return self.conclusion.replace("_", " ")
        if self.done:
            return "no longer watched"
        stage = "in progress" if self.status == "in_progress" else "queued"
        return " · ".join(part for part in (stage, self.detail) if part)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "started": self.started.isoformat()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WatchedRun":
        started = datetime.fromisoformat(data["started"])
        return cls(**{**data, "kind": RunKind(data["kind"]), "started": started})


def job_detail(jobs: list[JobState]) -> str:
    failed = [f"{job.name} ✗" for job in jobs if job.conclusion in FAILED_CONCLUSIONS]
    running = [f"{job.name} ⟳" for job in jobs if job.status == "in_progress"]
    return ", ".join(failed + running)


def finish_note(run: WatchedRun, watch_time: timedelta) -> str:
    prefix = f"R{run.number}: {run.workflow_name}"
    if run.conclusion is None:
        hours = int(watch_time.total_seconds()) // _SECONDS_PER_HOUR
        return f"R{run.number}: stopped watching {run.title} after {hours} h; it had not finished."
    if run.kind is RunKind.DISPATCH:
        return f"{prefix} {run.label} {run.state.lstrip('✓✗ ')}."
    earlier = f"attempt {run.attempt - 1}"
    if run.before in FAILED_CONCLUSIONS and run.conclusion == "success":
        return (
            f"{prefix} passed on attempt {run.attempt} (failed on {earlier}): a proven flaky event."
        )
    if run.before in FAILED_CONCLUSIONS and run.conclusion in FAILED_CONCLUSIONS:
        return f"{prefix} failed again on attempt {run.attempt}."
    return f"{prefix} {run.state.lstrip('✓✗ ')} on attempt {run.attempt}."


def group_note(runs: list[WatchedRun]) -> str:
    passed = sum(run.conclusion == "success" for run in runs)
    first = runs[0]
    return f"{first.workflow_name} on {first.commit[:7]}: {passed} of {len(runs)} passed."


class RunWatch:
    def __init__(self, api: RunApi, *, watch_time: timedelta, now: Callable[[], datetime]) -> None:
        self._api = api
        self._watch_time = watch_time
        self._now = now
        # Polled from a timer thread while the chat adds runs: change entries only by index.
        self.runs: list[WatchedRun] = []

    @property
    def active(self) -> int:
        return sum(not run.done for run in self.runs)

    @property
    def next_number(self) -> int:
        return len(self.runs) + 1

    def add(self, run: WatchedRun) -> WatchedRun:
        numbered = replace(run, number=self.next_number)
        self.runs.append(numbered)
        return numbered

    def find(self, number: int) -> WatchedRun | None:
        return next((run for run in self.runs if run.number == number), None)

    def poll(self) -> list[str]:
        """Read every unfinished run once; returns a note for each run that finished."""
        notes: list[str] = []
        for index, run in enumerate(self.runs):
            if run.done:
                continue
            try:
                updated = self._poll(run)
            except ApiRateLimitError:
                self._wait_for_rate_limit()
                return notes
            except GitHubApiError as error:
                updated = replace(run, detail=f"cannot read it: {error}")
            self.runs[index] = updated
            if updated.done:
                notes.extend(self._notes(updated))
        return notes

    def _poll(self, run: WatchedRun) -> WatchedRun:
        if self._now() - run.started > self._watch_time:
            return replace(run, done=True, detail="")
        run_id = run.run_id if run.run_id is not None else self._locate(run)
        if run_id is None:
            return run
        state = self._api.run_state(run.repository, run_id)
        if state.attempt < run.attempt:
            return replace(run, run_id=run_id, status="queued", detail="")
        if state.completed:
            return replace(
                run, run_id=run_id, status=state.status, conclusion=state.conclusion,
                attempt=state.attempt, detail="", done=True,
            )  # fmt: skip
        jobs = self._api.job_states(run.repository, run_id, state.attempt)
        return replace(run, run_id=run_id, status=state.status, detail=job_detail(jobs))

    def _locate(self, run: WatchedRun) -> int | None:
        taken = {other.run_id for other in self.runs}
        found = self._api.dispatched_runs(
            run.repository, run.workflow_path, ref=run.ref, since=run.started - _DISPATCH_SLACK
        )
        return next((run_id for run_id in found if run_id not in taken), None)

    def _wait_for_rate_limit(self) -> None:
        for index, run in enumerate(self.runs):
            if not run.done:
                self.runs[index] = replace(run, detail="waiting for GitHub's rate limit")

    def _notes(self, run: WatchedRun) -> list[str]:
        notes = [finish_note(run, self._watch_time)]
        if run.group is None:
            return notes
        group = [other for other in self.runs if other.group == run.group]
        if len(group) > 1 and all(other.done for other in group):
            notes.append(group_note(group))
        return notes
