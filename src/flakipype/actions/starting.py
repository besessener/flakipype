"""Starting confirmed reruns and dispatches on GitHub, and watching what started."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from flakipype.actions.api import RunApi
from flakipype.actions.refusal import refusal
from flakipype.actions.watch import RunKind, RunWatch, WatchedRun
from flakipype.flaky.model import WorkflowRun
from flakipype.flaky.scoring import FlakyKey
from flakipype.github.actions import GitHubApiError
from flakipype.github.runs import RunState

WATCHING = "It is watched; a note follows when it finishes."


@dataclass(frozen=True)
class Started:
    outcome: str
    run_id: int | None
    # Reruns and dispatches that started on GitHub; each counts against the budget.
    spent: int = 0


@dataclass(frozen=True)
class Dispatch:
    key: FlakyKey
    ref: str
    commit: str
    repeats: int


@dataclass(frozen=True)
class Starter:
    runs: RunApi
    watch: RunWatch
    now: Callable[[], datetime]

    def rerun(
        self, run: WorkflowRun, state: RunState, start: Callable[[str, int], None]
    ) -> Started:
        start(run.repository, run.run_id)
        attempt = state.attempt + 1
        watched = self.watch.add(
            WatchedRun(
                number=0, kind=RunKind.RERUN, repository=run.repository,
                workflow_path=run.workflow_path, workflow_name=state.workflow_name,
                label=f"#{run.run_id}/{attempt}", commit=state.head_sha, ref=state.head_branch,
                started=self.now(), run_id=run.run_id, attempt=attempt, before=state.conclusion,
            )
        )  # fmt: skip
        return Started(f"Started R{watched.number}: {watched.title}. {WATCHING}", run.run_id, 1)

    def dispatches(self, dispatch: Dispatch) -> Started:
        key, repeats = dispatch.key, dispatch.repeats
        group = self.watch.next_number if repeats > 1 else None
        started: list[WatchedRun] = []
        for index in range(1, repeats + 1):
            try:
                run_id = self.runs.dispatch(key.repository, key.workflow_path, dispatch.ref)
            except GitHubApiError as error:
                if not started:
                    raise
                return _partly_started(dispatch, started, index=index, error=error)
            label = f"dispatch {index}/{repeats}" if group else "dispatch"
            started.append(
                self.watch.add(
                    WatchedRun(
                        number=0, kind=RunKind.DISPATCH, repository=key.repository,
                        workflow_path=key.workflow_path, workflow_name=key.workflow_name,
                        label=label, commit=dispatch.commit, ref=dispatch.ref,
                        started=self.now(), run_id=run_id, attempt=1, group=group,
                    )
                )
            )  # fmt: skip
        numbers = ", ".join(f"R{run.number}" for run in started)
        outcome = f"Started {numbers}: {key.workflow_name} on {dispatch.ref}. {WATCHING}"
        return Started(outcome, started[0].run_id, len(started))


def _partly_started(
    dispatch: Dispatch, started: list[WatchedRun], *, index: int, error: GitHubApiError
) -> Started:
    """The runs that did start stay counted and watched, so the answer names them."""
    numbers = ", ".join(f"R{run.number}" for run in started)
    outcome = (
        f"Started {numbers}: {dispatch.key.workflow_name} on {dispatch.ref}, then dispatch "
        f"{index}/{dispatch.repeats} failed: {refusal(error).rstrip('.')}. {WATCHING}"
    )
    return Started(outcome, started[0].run_id, len(started))
