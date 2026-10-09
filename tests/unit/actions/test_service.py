from dataclasses import replace
from datetime import datetime

import pytest

from flakipype.actions.service import ActionService
from flakipype.actions.watch import RunKind, WatchedRun
from flakipype.agent.tools import Answer, PreparedAction, ToolError
from flakipype.config.settings import ActionSettings
from flakipype.github.actions import GitHubApiError
from flakipype.github.runs import JobState
from flakipype.store.database import ScanCache

from support.builders import START
from support.fake_runs import (
    DISPATCHABLE,
    E2E,
    FakeRuns,
    e2e_evidence,
    e2e_finding,
    state,
)

FORBIDDEN = GitHubApiError("Resource not accessible by integration (HTTP 403)", 403)


def service(
    cache: ScanCache, runs: FakeRuns, settings: ActionSettings | None = None
) -> ActionService:
    return ActionService(
        runs=runs, files=runs, audit=cache.audit, settings=settings or ActionSettings(),
        owner="octo-org", now=lambda: START,
    )  # fmt: skip


def failed_run() -> FakeRuns:
    return FakeRuns(
        states={4: [state(4)]},
        jobs={(4, 1): [JobState("e2e", "completed", "failure"),
                       JobState("lint", "completed", "success")]},
        files={(E2E, "3f2a9c1"): DISPATCHABLE},
    )  # fmt: skip


def rerun_failed(actions: ActionService, run_id: int | None = None) -> PreparedAction:
    return actions.rerun_failed(e2e_finding(), e2e_evidence(), run_id=run_id)


def test_a_confirmed_rerun_of_failed_jobs_starts_and_watches_it(cache: ScanCache) -> None:
    runs = failed_run()
    actions = service(cache, runs)

    prepared = rerun_failed(actions)
    outcome = prepared.run(Answer.CONFIRMED)

    assert prepared.request.title == "Rerun failed jobs?"
    assert prepared.request.details == (
        "octo-org/app · E2E · run 4 (attempt 1 → 2)",
        "commit 3f2a9c1 on main · failed jobs: e2e",
        "Actions this session: 1 of 10",
    )
    assert outcome.startswith("Started R1: app · E2E #4/2.")
    assert "rerun_failed_jobs octo-org/app 4" in runs.calls
    assert actions.used == 1
    (entry,) = cache.audit.entries(actions.session)
    assert (entry.action, entry.origin, entry.answer, entry.run_id) == (
        "rerun_failed", "model", "confirmed", 4,
    )  # fmt: skip
    assert entry.request.startswith("Rerun failed jobs?\nocto-org/app · E2E · run 4")
    assert actions.watched_runs() == (
        "R1 app · E2E #4/2: queued · run 4\nActions used in this session: 1 of 10."
    )


def test_a_declined_action_is_audited_and_does_nothing(cache: ScanCache) -> None:
    runs = failed_run()
    actions = service(cache, runs)

    with actions.commanded():
        rerun_failed(actions).declined(Answer.DECLINED)

    assert not [call for call in runs.calls if call.startswith("rerun")]
    assert actions.used == 0
    assert actions.watched_runs() == "No runs started in this session."
    assert actions.audit_text() == (
        "Actions in this session:\n- 08:00 `rerun_failed` asked by command, declined: not run"
    )


def test_reruns_need_a_finished_run_with_failed_jobs(cache: ScanCache) -> None:
    runs = FakeRuns(states={4: [state(4, status="in_progress", conclusion=None)],
                            3: [state(3, conclusion="success", attempt=2)]})  # fmt: skip
    actions = service(cache, runs)

    with pytest.raises(ToolError, match="Run 4 is still running"):
        rerun_failed(actions)
    with pytest.raises(ToolError, match="Run 3 has no failed jobs on attempt 2"):
        rerun_failed(actions, 3)


def test_a_whole_rerun_takes_the_newest_run_of_any_result(cache: ScanCache) -> None:
    runs = FakeRuns(states={4: [state(4, conclusion="success")]})
    actions = service(cache, runs)

    prepared = actions.rerun_run(e2e_finding(), e2e_evidence(newest="success"), run_id=None)
    prepared.run(Answer.CONFIRMED)

    assert prepared.request.title == "Rerun all jobs?"
    assert "failed jobs: none" in prepared.request.details[1]
    assert "rerun octo-org/app 4" in runs.calls


def test_actions_stay_with_the_configured_owner(cache: ScanCache) -> None:
    actions = service(cache, failed_run())
    finding = e2e_finding(repository="other/app")

    with pytest.raises(ToolError, match="configured owner"):
        actions.dispatch(finding, None, 1)


def test_the_budget_is_a_hard_limit(cache: ScanCache) -> None:
    runs = failed_run()
    runs.dispatch_ids = [70, 71]
    actions = service(cache, runs, ActionSettings(max_per_session=2, max_watched=2))

    with pytest.raises(ToolError, match="Only 2 of this session's 2 reruns and dispatches"):
        actions.dispatch(e2e_finding(), None, 3)
    actions.dispatch(e2e_finding(), None, 2).run(Answer.CONFIRMED)

    with pytest.raises(ToolError, match="Action budget used up: 2 of 2"):
        rerun_failed(actions)
    actions.reset()
    with pytest.raises(ToolError, match="Already watching 0 runs"):
        ActionService(
            runs=runs, files=runs, audit=cache.audit, settings=ActionSettings(max_watched=1),
            owner="octo-org", now=lambda: START,
        ).dispatch(e2e_finding(), None, 2)  # fmt: skip
    assert actions.used == 0
    assert actions.watched == []


def test_a_repeated_dispatch_on_the_default_branch(cache: ScanCache) -> None:
    runs = failed_run()
    runs.dispatch_ids = [70]
    actions = service(cache, runs)

    with actions.commanded():
        prepared = actions.dispatch(e2e_finding(), None, 3)
        outcome = prepared.run(Answer.CONFIRMED)

    assert prepared.request.details == (
        "octo-org/app · E2E (.github/workflows/e2e.yml)",
        "on main at 3f2a9c1 · 3 runs, without inputs",
        "Actions this session: 3 of 10",
    )
    assert outcome.startswith("Started R1, R2, R3: E2E on main.")
    assert [(run.label, run.run_id, run.group) for run in actions.watched] == [
        ("dispatch 1/3", 70, 1),
        ("dispatch 2/3", None, 1),
        ("dispatch 3/3", None, 1),
    ]
    assert actions.used == 3
    (entry,) = cache.audit.entries(actions.session)
    assert (entry.origin, entry.run_id) == ("command", 70)


def test_a_single_dispatch_on_a_named_ref(cache: ScanCache) -> None:
    runs = failed_run()
    runs.refs["v1"] = "abcdef0" + "0" * 33
    runs.files[(E2E, "abcdef0")] = DISPATCHABLE
    actions = service(cache, runs)

    prepared = actions.dispatch(e2e_finding(), "v1", 1)
    prepared.run(Answer.CONFIRMED)

    assert prepared.request.details[1] == "on v1 at abcdef0 · 1 run, without inputs"
    assert actions.watched[0].label == "dispatch"
    assert "default_branch octo-org/app" not in runs.calls


@pytest.mark.parametrize(
    ("ref", "files", "problem"),
    [
        ("nope", {}, "nope is neither a branch nor a tag of octo-org/app"),
        ("main", {}, "Cannot dispatch E2E on main: the workflow file does not exist there"),
        (
            "main",
            {(E2E, "3f2a9c1"): "on: push\n"},
            "Cannot dispatch E2E on main: the workflow does not declare workflow_dispatch",
        ),
    ],
)
def test_dispatch_needs_a_ref_and_a_dispatchable_workflow(
    cache: ScanCache, ref: str, files: dict[tuple[str, str], str], problem: str
) -> None:
    actions = service(cache, FakeRuns(files=files))

    with pytest.raises(ToolError, match=problem):
        actions.dispatch(e2e_finding(), ref, 1)


def test_github_errors_become_tool_errors_with_a_next_step(cache: ScanCache) -> None:
    runs = failed_run()
    runs.errors["rerun_failed_jobs"] = FORBIDDEN
    actions = service(cache, runs)
    prepared = rerun_failed(actions)

    with pytest.raises(ToolError, match="'Actions: read and write' for a fine-grained token"):
        prepared.run(Answer.CONFIRMED)
    runs.errors["ref_commit"] = GitHubApiError("Server Error (HTTP 500)", 500)
    with pytest.raises(ToolError, match=r"GitHub: Server Error \(HTTP 500\)"):
        actions.dispatch(e2e_finding(), None, 1)

    (entry,) = cache.audit.entries(actions.session)
    assert entry.outcome == "failed: Resource not accessible by integration (HTTP 403)"
    assert actions.used == 0


def test_only_watched_unfinished_runs_can_be_cancelled(cache: ScanCache) -> None:
    runs = failed_run()
    runs.dispatch_ids = [70, None]
    actions = service(cache, runs)
    actions.dispatch(e2e_finding(), None, 2).run(Answer.CONFIRMED)

    with pytest.raises(ToolError, match="R9 is not a run started in this session"):
        actions.cancel(9)
    with pytest.raises(ToolError, match="R2 has not shown up on GitHub yet"):
        actions.cancel(2)
    prepared = actions.cancel(1)
    assert prepared.request.details == (
        "R1 octo-org/app · E2E dispatch 1/2",
        "run 70 · queued",
    )
    assert prepared.run(Answer.CONFIRMED).startswith("Cancel requested for R1.")
    assert "cancel octo-org/app 70" in runs.calls
    assert actions.used == 2

    runs.states[70] = [state(70, conclusion="cancelled")]
    runs.found = [71]
    runs.states[71] = [state(71, status="in_progress", conclusion=None)]
    assert actions.poll() == ["R1: E2E dispatch 1/2 cancelled."]
    with pytest.raises(ToolError, match="R1 has finished or is no longer watched"):
        actions.cancel(1)


def test_the_session_state_survives_a_resume(cache: ScanCache) -> None:
    runs = failed_run()
    actions = service(cache, runs)
    rerun_failed(actions).run(Answer.CONFIRMED)

    resumed = service(cache, runs)
    resumed.restore(actions.state())

    assert (resumed.session, resumed.used, resumed.watched) == (
        actions.session, 1, actions.watched,
    )  # fmt: skip
    assert resumed.audit_text().startswith("Actions in this session:\n- 08:00 `rerun_failed`")


def test_authorised_reruns_and_dispatches_use_the_budget(cache: ScanCache) -> None:
    runs = failed_run()
    runs.dispatch_ids = [70]
    actions = service(cache, runs, ActionSettings(max_per_session=2))
    template = WatchedRun(
        number=0, kind=RunKind.DISPATCH, repository="octo-org/app", workflow_path=E2E,
        workflow_name="E2E", label="verify 1/3", commit="c0ffee1", ref="flakipype/fix-e2e-1",
        started=START, run_id=None, attempt=1,
    )  # fmt: skip

    dispatched = actions.dispatch_authorised(template)
    assert dispatched is not None
    finished = replace(dispatched, conclusion="failure", done=True)
    rerun = actions.rerun_authorised(finished, "verify 2/3")

    assert rerun is not None
    assert (dispatched.number, dispatched.run_id) == (1, 70)
    assert (rerun.number, rerun.label, rerun.attempt, rerun.before, rerun.done) == (
        2, "verify 2/3", 2, "failure", False,
    )  # fmt: skip
    assert "rerun octo-org/app 70" in runs.calls
    assert actions.used == 2
    assert actions.rerun_authorised(finished, "verify 3/3") is None
    assert actions.dispatch_authorised(template) is None
    assert cache.audit.entries(actions.session) == []


def test_an_authorised_rerun_needs_a_run_id(cache: ScanCache) -> None:
    actions = service(cache, failed_run())
    unlocated = WatchedRun(
        number=1, kind=RunKind.DISPATCH, repository="octo-org/app", workflow_path=E2E,
        workflow_name="E2E", label="dispatch", commit="c0ffee1", ref="main", started=START,
        run_id=None, attempt=1,
    )  # fmt: skip

    assert actions.rerun_authorised(unlocated, "verify 2/3") is None
    assert actions.used == 0


def test_no_actions_yet(cache: ScanCache) -> None:
    assert service(cache, FakeRuns()).audit_text() == "No actions requested in this session."


def test_start_time_is_recorded(cache: ScanCache) -> None:
    runs = failed_run()
    actions = service(cache, runs)
    rerun_failed(actions).run(Answer.CONFIRMED)

    assert actions.watched[0].started == datetime.fromisoformat("2026-10-01T08:00:00+00:00")
