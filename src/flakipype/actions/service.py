"""The chat's actions: targets checked, a request for the gate, budget, audit and watching."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

from flakipype.actions.api import RunApi, WorkflowFiles
from flakipype.actions.dispatchable import dispatch_problem
from flakipype.actions.targets import check_owner, newest_failed_run, newest_run
from flakipype.actions.watch import RunKind, RunWatch, WatchedRun
from flakipype.agent.tools import ActionRequest, PreparedAction, ToolError
from flakipype.config.settings import ActionSettings
from flakipype.flaky.findings import Evidence, Finding
from flakipype.flaky.model import FAILED_CONCLUSIONS, WorkflowRun
from flakipype.flaky.scoring import FlakyKey
from flakipype.github.actions import GitHubApiError
from flakipype.github.runs import RunState
from flakipype.store.audit import AuditEntry, AuditLog

_HTTP_FORBIDDEN = 403
_CONFIRMED = "confirmed"
_DECLINED = "declined"
_WATCHING = "It is watched; a note follows when it finishes."


class Origin(StrEnum):
    MODEL = "model"
    COMMAND = "command"


@dataclass(frozen=True)
class _Started:
    outcome: str
    run_id: int | None


@dataclass(frozen=True)
class _Dispatch:
    key: FlakyKey
    ref: str
    commit: str
    repeats: int


def refusal(error: GitHubApiError) -> str:
    if error.status == _HTTP_FORBIDDEN:
        return (
            f"GitHub refused: {error}. flakipype needs write access to Actions: the repo scope "
            "for a classic token or gh auth login, or 'Actions: read and write' for a "
            "fine-grained token."
        )
    return f"GitHub: {error}"


@contextmanager
def _from_github() -> Iterator[None]:
    try:
        yield
    except GitHubApiError as error:
        raise ToolError(refusal(error)) from error


class ActionService:
    def __init__(  # noqa: PLR0913 - collaborators of the actions, all keyword-only
        self,
        *,
        runs: RunApi,
        files: WorkflowFiles,
        audit: AuditLog,
        settings: ActionSettings,
        owner: str,
        now: Callable[[], datetime],
    ) -> None:
        self._runs = runs
        self._files = files
        self._audit = audit
        self._settings = settings
        self._owner = owner
        self._now = now
        self._watch = RunWatch(runs, watch_time=timedelta(hours=settings.watch_hours), now=now)
        self._origin = Origin.MODEL
        self.session = uuid4().hex
        self.used = 0

    @property
    def watched(self) -> list[WatchedRun]:
        return list(self._watch.runs)

    @contextmanager
    def commanded(self) -> Iterator[None]:
        """Actions prepared inside are recorded as asked for by a command, not by the model."""
        self._origin = Origin.COMMAND
        try:
            yield
        finally:
            self._origin = Origin.MODEL

    def rerun_failed(
        self, finding: Finding, evidence: Evidence, *, run_id: int | None
    ) -> PreparedAction:
        run = newest_failed_run(finding, evidence, run_id)
        state = self._checked_run(run)
        if state.conclusion not in FAILED_CONCLUSIONS:
            message = f"Run {run.run_id} has no failed jobs on attempt {state.attempt}."
            raise ToolError(message)
        request = self._rerun_request("Rerun failed jobs?", run, state)
        return self._prepare(
            "rerun_failed",
            request,
            lambda: self._start_rerun(run, state, self._runs.rerun_failed_jobs),
        )

    def rerun_run(
        self, finding: Finding, evidence: Evidence, *, run_id: int | None
    ) -> PreparedAction:
        run = newest_run(finding, evidence, run_id)
        state = self._checked_run(run)
        request = self._rerun_request("Rerun all jobs?", run, state)
        return self._prepare(
            "rerun_run", request, lambda: self._start_rerun(run, state, self._runs.rerun)
        )

    def dispatch(self, finding: Finding, ref: str | None, repeats: int) -> PreparedAction:
        key = finding.key
        check_owner(key.repository, self._owner)
        self._check_room(repeats)
        with _from_github():
            name = ref or self._runs.default_branch(key.repository)
            commit = self._runs.ref_commit(key.repository, name)
            if commit is None:
                message = f"{name} is neither a branch nor a tag of {key.repository}."
                raise ToolError(message)
            text = self._files.file_content(key.repository, key.workflow_path, commit)
        problem = (
            "the workflow file does not exist there" if text is None else dispatch_problem(text)
        )
        if problem is not None:
            message = f"Cannot dispatch {key.workflow_name} on {name}: {problem}."
            raise ToolError(message)
        times = f"{repeats} runs" if repeats > 1 else "1 run"
        request = ActionRequest(
            "Dispatch workflow?",
            (
                f"{key.repository} · {key.workflow_name} ({key.workflow_path})",
                f"on {name} at {commit[:7]} · {times}, without inputs",
                self._budget_line(repeats),
            ),
        )
        dispatch = _Dispatch(key, name, commit, repeats)
        return self._prepare("dispatch", request, lambda: self._start_dispatches(dispatch))

    def cancel(self, number: int) -> PreparedAction:
        run = self._watch.find(number)
        if run is None:
            message = f"R{number} is not a run started in this session; see watched_runs."
            raise ToolError(message)
        if run.done:
            message = f"R{number} has finished or is no longer watched."
            raise ToolError(message)
        run_id = run.run_id
        if run_id is None:
            message = f"R{number} has not shown up on GitHub yet; try again in a moment."
            raise ToolError(message)
        request = ActionRequest(
            "Cancel run?", (f"R{number} {run.repository} · {run.workflow_name} {run.label}",
                            f"run {run_id} · {run.state}")
        )  # fmt: skip

        def start() -> _Started:
            self._runs.cancel(run.repository, run_id)
            return _Started(f"Cancel requested for R{number}. {_WATCHING}", run_id)

        return self._prepare("cancel", request, start)

    def watched_runs(self) -> str:
        if not self._watch.runs:
            return "No runs started in this session."
        lines = [
            f"R{run.number} {run.title}: {run.state}"
            + (f" · run {run.run_id}" if run.run_id else "")
            for run in self._watch.runs
        ]
        used = f"Actions used in this session: {self.used} of {self._settings.max_per_session}."
        return "\n".join([*lines, used])

    def poll(self) -> list[str]:
        """Reads the unfinished runs once; a note for each run that finished."""
        return self._watch.poll()

    def audit_text(self) -> str:
        entries = self._audit.entries(self.session)
        if not entries:
            return "No actions requested in this session."
        lines = [
            f"- {entry.time[11:16]} `{entry.action}` asked by {entry.origin}, {entry.answer}: "
            f"{entry.outcome}"
            for entry in entries
        ]
        return "Actions in this session:\n" + "\n".join(lines)

    def state(self) -> dict[str, Any]:
        return {
            "session": self.session,
            "used": self.used,
            "runs": [run.to_dict() for run in self._watch.runs],
        }

    def restore(self, state: dict[str, Any]) -> None:
        self.session = state["session"]
        self.used = int(state["used"])
        self._watch.runs = [WatchedRun.from_dict(run) for run in state["runs"]]

    def reset(self) -> None:
        self.session = uuid4().hex
        self.used = 0
        self._watch.runs = []

    def _checked_run(self, run: WorkflowRun) -> RunState:
        check_owner(run.repository, self._owner)
        self._check_room(1)
        with _from_github():
            state = self._runs.run_state(run.repository, run.run_id)
        if not state.completed:
            message = f"Run {run.run_id} is still running; it can be rerun when it has finished."
            raise ToolError(message)
        return state

    def _rerun_request(self, title: str, run: WorkflowRun, state: RunState) -> ActionRequest:
        with _from_github():
            jobs = self._runs.job_states(run.repository, run.run_id, state.attempt)
        failed = ", ".join(
            sorted({job.name for job in jobs if job.conclusion in FAILED_CONCLUSIONS})
        )
        attempts = f"attempt {state.attempt} → {state.attempt + 1}"
        branch = state.head_branch or "—"
        return ActionRequest(
            title,
            (
                f"{run.repository} · {state.workflow_name} · run {run.run_id} ({attempts})",
                f"commit {state.head_sha[:7]} on {branch} · failed jobs: {failed or 'none'}",
                self._budget_line(1),
            ),
        )

    def _start_rerun(
        self, run: WorkflowRun, state: RunState, start: Callable[[str, int], None]
    ) -> _Started:
        start(run.repository, run.run_id)
        self.used += 1
        attempt = state.attempt + 1
        watched = self._watch.add(
            WatchedRun(
                number=0, kind=RunKind.RERUN, repository=run.repository,
                workflow_path=run.workflow_path, workflow_name=state.workflow_name,
                label=f"#{run.run_id}/{attempt}", commit=state.head_sha, ref=state.head_branch,
                started=self._now(), run_id=run.run_id, attempt=attempt, before=state.conclusion,
            )
        )  # fmt: skip
        return _Started(f"Started R{watched.number}: {watched.title}. {_WATCHING}", run.run_id)

    def _start_dispatches(self, dispatch: _Dispatch) -> _Started:
        key, repeats = dispatch.key, dispatch.repeats
        group = self._watch.next_number if repeats > 1 else None
        started: list[WatchedRun] = []
        for index in range(1, repeats + 1):
            run_id = self._runs.dispatch(key.repository, key.workflow_path, dispatch.ref)
            self.used += 1
            label = f"dispatch {index}/{repeats}" if group else "dispatch"
            started.append(
                self._watch.add(
                    WatchedRun(
                        number=0, kind=RunKind.DISPATCH, repository=key.repository,
                        workflow_path=key.workflow_path, workflow_name=key.workflow_name,
                        label=label, commit=dispatch.commit, ref=dispatch.ref,
                        started=self._now(), run_id=run_id, attempt=1, group=group,
                    )
                )
            )  # fmt: skip
        numbers = ", ".join(f"R{run.number}" for run in started)
        outcome = f"Started {numbers}: {key.workflow_name} on {dispatch.ref}. {_WATCHING}"
        return _Started(outcome, started[0].run_id)

    def _check_room(self, count: int) -> None:
        limit, left = self._settings.max_per_session, self._settings.max_per_session - self.used
        if left <= 0:
            message = (
                f"Action budget used up: {self.used} of {limit} reruns and dispatches in this "
                "session. /new starts a new session."
            )
            raise ToolError(message)
        if count > left:
            message = f"Only {left} of this session's {limit} reruns and dispatches are left."
            raise ToolError(message)
        watching, most = self._watch.active, self._settings.max_watched
        if watching + count > most:
            message = (
                f"Already watching {watching} runs (at most {most}); "
                "wait for some to finish or cancel one."
            )
            raise ToolError(message)

    def _budget_line(self, count: int) -> str:
        return f"Actions this session: {self.used + count} of {self._settings.max_per_session}"

    def _prepare(
        self, action: str, request: ActionRequest, start: Callable[[], _Started]
    ) -> PreparedAction:
        origin = self._origin

        def record(answer: str, outcome: str, run_id: int | None = None) -> None:
            text = "\n".join([request.title, *request.details])
            self._audit.record(
                AuditEntry(
                    time=self._now().isoformat(), session=self.session, action=action,
                    origin=origin, request=text, answer=answer, outcome=outcome, run_id=run_id,
                )
            )  # fmt: skip

        def run() -> str:
            try:
                started = start()
            except GitHubApiError as error:
                record(_CONFIRMED, f"failed: {error}")
                raise ToolError(refusal(error)) from error
            record(_CONFIRMED, started.outcome, started.run_id)
            return started.outcome

        return PreparedAction(request, run, lambda: record(_DECLINED, "not run"))
