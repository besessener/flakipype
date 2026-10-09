"""Verification: the finding's workflow on the fix commit, run until there are enough results."""

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from flakipype.actions.dispatchable import dispatch_problem, triggers
from flakipype.actions.service import ActionService
from flakipype.actions.watch import RunKind, WatchedRun
from flakipype.fix.texts import Rate, VerificationFacts, verification_text
from flakipype.flaky.model import FAILED_CONCLUSIONS, JobResult
from flakipype.flaky.signature import signature_from_log
from flakipype.github.actions import GitHubApiError
from flakipype.github.runs import CommitRun

WAIT_FOR_RUN = timedelta(minutes=10)
_STARTED_BY_PUSH = frozenset({"pull_request", "push"})
_EVENTS = _STARTED_BY_PUSH | {"workflow_dispatch"}
_UNREADABLE = "failed (its log could not be read)"


class Stage(StrEnum):
    WAITING = "waiting"
    WATCHING = "watching"
    DONE = "done"


@dataclass(frozen=True)
class Verification:
    pull_number: int
    repository: str
    workflow_path: str
    workflow_name: str
    job: str
    branch: str
    commit: str
    wanted: int
    started: datetime
    rate: Rate
    # Error signatures of the finding: a failure with one of them means the fix did not hold.
    fingerprints: tuple[str, ...]
    stage: Stage = Stage.WAITING
    watched: tuple[int, ...] = ()
    results: tuple[str, ...] = ()
    outcome: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "started": self.started.isoformat()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Verification":
        return cls(**{
            **data, "started": datetime.fromisoformat(data["started"]),
            "rate": Rate(**data["rate"]), "fingerprints": tuple(data["fingerprints"]),
            "stage": Stage(data["stage"]),
            "watched": tuple(data["watched"]), "results": tuple(data["results"]),
        })  # fmt: skip


class CommitRuns(Protocol):
    def commit_runs(self, repository: str, workflow_path: str, commit: str) -> list[CommitRun]: ...


class JobLogs(Protocol):
    def attempt_jobs(self, repository: str, run_id: int, attempt: int) -> list[JobResult]: ...

    def job_log(self, repository: str, job_id: int) -> str | None: ...


class Comments(Protocol):
    def comment(self, repository: str, number: int, body: str) -> None: ...


@dataclass(frozen=True)
class VerifyGitHub:
    runs: CommitRuns
    logs: JobLogs
    comments: Comments


class Verifier:
    def __init__(
        self, *, github: VerifyGitHub, actions: ActionService, now: Callable[[], datetime]
    ) -> None:
        self._github = github
        self._actions = actions
        self._now = now

    def begin(self, verification: Verification, workflow_text: str) -> Verification:
        """Waits for the pull request's run, or dispatches when nothing else starts one."""
        if triggers(workflow_text) & _STARTED_BY_PUSH:
            return verification
        if dispatch_problem(workflow_text) is not None:
            return self._finish(
                verification,
                "the workflow runs neither on push, pull_request nor workflow_dispatch",
            )
        dispatched = self._actions.dispatch_authorised(self._run(verification, run_id=None))
        if dispatched is None:
            return self._finish(verification, "the action budget of this session is used up")
        return replace(verification, stage=Stage.WATCHING, watched=(dispatched.number,))

    def poll(self, verification: Verification) -> Verification:
        if verification.stage is Stage.WAITING:
            return self._find_run(verification)
        if verification.stage is Stage.WATCHING:
            return self._follow(verification)
        return verification

    def _find_run(self, verification: Verification) -> Verification:
        found = self._github.runs.commit_runs(
            verification.repository, verification.workflow_path, verification.commit
        )
        runs = [run for run in found if run.event in _EVENTS]
        if runs:
            watched = self._actions.watch(self._run(verification, run_id=runs[0].run_id))
            return replace(verification, stage=Stage.WATCHING, watched=(watched.number,))
        if self._now() - verification.started > WAIT_FOR_RUN:
            minutes = int(WAIT_FOR_RUN.total_seconds() // 60)
            return self._finish(
                verification,
                f"no run of the workflow started on the fix branch in {minutes} minutes",
            )
        return verification

    def _follow(self, verification: Verification) -> Verification:
        run = self._actions.find(verification.watched[-1])
        if run is None or not run.done:
            return verification
        if run.conclusion is None:
            return self._finish(verification, "a run did not finish while it was watched")
        updated = replace(
            verification, results=(*verification.results, self._result(verification, run))
        )
        if len(updated.results) >= updated.wanted:
            return self._finish(updated)
        return self._rerun(updated, run)

    def _rerun(self, verification: Verification, run: WatchedRun) -> Verification:
        if run.conclusion not in {"success", *FAILED_CONCLUSIONS}:
            return self._finish(verification, f"a run ended as {run.conclusion}")
        label = f"verify {len(verification.results) + 1}/{verification.wanted}"
        try:
            rerun = self._actions.rerun_authorised(run, label)
        except GitHubApiError as error:
            return self._finish(verification, f"GitHub refused the rerun: {error}")
        if rerun is None:
            return self._finish(verification, "the action budget of this session is used up")
        return replace(verification, watched=(*verification.watched, rerun.number))

    def _result(self, verification: Verification, run: WatchedRun) -> str:
        if run.conclusion == "success":
            return "passed"
        if run.conclusion not in FAILED_CONCLUSIONS or run.run_id is None:
            return str(run.conclusion).replace("_", " ")
        return self._classify_failure(verification, run, run.run_id)

    def _classify_failure(self, verification: Verification, run: WatchedRun, run_id: int) -> str:
        try:
            jobs = self._github.logs.attempt_jobs(run.repository, run_id, run.attempt)
            failed = [job for job in jobs if job.failed and job.name == verification.job]
            if not failed:
                others = (
                    ", ".join(sorted({job.name for job in jobs if job.failed})) or "another job"
                )
                return f"failed in {others}, not in {verification.job}"
            log = self._github.logs.job_log(run.repository, failed[0].job_id)
        except GitHubApiError:
            return _UNREADABLE
        return _signature_result(verification.fingerprints, log)

    def _run(self, verification: Verification, *, run_id: int | None) -> WatchedRun:
        return WatchedRun(
            number=0, kind=RunKind.RERUN if run_id else RunKind.DISPATCH,
            repository=verification.repository, workflow_path=verification.workflow_path,
            workflow_name=verification.workflow_name, label=f"verify 1/{verification.wanted}",
            commit=verification.commit, ref=verification.branch, started=self._now(),
            run_id=run_id, attempt=1,
        )  # fmt: skip

    def _finish(self, verification: Verification, stopped: str = "") -> Verification:
        if verification.results:
            facts = VerificationFacts(
                verification.workflow_name, verification.results, verification.wanted,
                verification.rate, stopped,
            )  # fmt: skip
            text = verification_text(facts)
        else:
            text = f"flakipype verification: cannot verify automatically: {stopped}."
        try:
            self._github.comments.comment(verification.repository, verification.pull_number, text)
        except GitHubApiError as error:
            text += f"\n(The comment could not be posted on the pull request: {error})"
        return replace(verification, stage=Stage.DONE, outcome=text)


def _signature_result(fingerprints: tuple[str, ...], log: str | None) -> str:
    signature = signature_from_log(log) if log else None
    if signature is None:
        return _UNREADABLE
    if signature.fingerprint in fingerprints:
        return "failed with the same error as before: the fix did not hold"
    return f"failed with another error: {signature.message}"
