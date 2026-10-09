from dataclasses import replace
from datetime import datetime, timedelta

from flakipype.actions.watch import RunKind, RunWatch, WatchedRun, finish_note
from flakipype.github.actions import ApiRateLimitError, GitHubApiError
from flakipype.github.runs import JobState

from support.builders import START
from support.fake_runs import APP, E2E, FakeRuns, state

SIX_HOURS = timedelta(hours=6)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def rerun(run_id: int = 4, *, before: str | None = "failure") -> WatchedRun:
    return WatchedRun(
        number=0, kind=RunKind.RERUN, repository=APP, workflow_path=E2E, workflow_name="E2E",
        label=f"#{run_id}/2", commit="3f2a9c1" + "0" * 33, ref="main", started=START,
        run_id=run_id, attempt=2, before=before,
    )  # fmt: skip


def dispatch(group: int | None, label: str, run_id: int | None = None) -> WatchedRun:
    return replace(
        rerun(), kind=RunKind.DISPATCH, label=label, run_id=run_id, attempt=1, before=None,
        group=group,
    )  # fmt: skip


def watch(runs: FakeRuns, clock: Clock | None = None) -> RunWatch:
    return RunWatch(runs, watch_time=SIX_HOURS, now=clock or Clock())


def test_a_rerun_is_queued_then_in_progress_then_a_proven_flaky_event() -> None:
    runs = FakeRuns(
        states={
            4: [
                state(4, attempt=1),
                state(4, status="in_progress", conclusion=None, attempt=2),
                state(4, conclusion="success", attempt=2),
            ]
        },
        jobs={(4, 2): [JobState("e2e", "in_progress", None), JobState("lint", "completed",
                                                                     "failure")]},
    )  # fmt: skip
    watcher = watch(runs)
    watcher.add(rerun())

    assert watcher.poll() == []
    assert watcher.runs[0].state == "queued"
    assert watcher.poll() == []
    assert watcher.runs[0].state == "in progress · lint ✗, e2e ⟳"
    assert watcher.poll() == [
        "R1: E2E passed on attempt 2 (failed on attempt 1): a proven flaky event."
    ]
    assert (watcher.runs[0].state, watcher.active) == ("✓ passed", 0)
    assert watcher.poll() == []


def test_finish_notes_of_reruns() -> None:
    finished = replace(rerun(), number=1, done=True)

    def note(run: WatchedRun) -> str:
        return finish_note(run, SIX_HOURS)

    assert note(replace(finished, conclusion="failure")) == "R1: E2E failed again on attempt 2."
    assert note(replace(finished, conclusion="success", before="success")) == (
        "R1: E2E passed on attempt 2."
    )
    assert note(replace(finished, conclusion="cancelled")) == "R1: E2E cancelled on attempt 2."
    assert note(finished) == ("R1: stopped watching app · E2E #4/2 after 6 h; it had not finished.")


def test_state_labels() -> None:
    run = rerun()

    assert replace(run, conclusion="timed_out").state == "✗ failed"
    assert replace(run, conclusion="startup_failure").state == "startup failure"
    assert replace(run, done=True).state == "no longer watched"
    assert replace(run, status="in_progress").state == "in progress"


def test_dispatched_runs_without_an_id_are_found_and_summed_up() -> None:
    runs = FakeRuns(
        states={
            7: [state(7, conclusion="success")],
            8: [state(8, conclusion="failure")],
            9: [state(9, conclusion="success")],
        },
        found=[6, 7, 8],
    )
    watcher = watch(runs)
    watcher.add(dispatch(None, "dispatch", run_id=6))
    for index in (1, 2, 3):
        watcher.add(dispatch(2, f"dispatch {index}/3", run_id=9 if index == 3 else None))
    runs.states[6] = [state(6, status="queued", conclusion=None)]

    notes = watcher.poll()

    assert [run.run_id for run in watcher.runs] == [6, 7, 8, 9]
    assert notes == [
        "R2: E2E dispatch 1/3 passed.",
        "R3: E2E dispatch 2/3 failed.",
        "R4: E2E dispatch 3/3 passed.",
        "E2E on 3f2a9c1: 2 of 3 passed.",
    ]
    assert "dispatched_runs octo-org/app .github/workflows/e2e.yml main 07:58" in runs.calls


def test_a_dispatched_run_not_shown_yet_stays_queued() -> None:
    watcher = watch(FakeRuns())
    watcher.add(dispatch(None, "dispatch"))

    assert watcher.poll() == []
    assert (watcher.runs[0].run_id, watcher.runs[0].state) == (None, "queued")


def test_runs_are_watched_for_a_limited_time() -> None:
    clock = Clock()
    watcher = watch(FakeRuns(states={4: [state(4, attempt=1)]}), clock)
    watcher.add(rerun())
    clock.now = START + SIX_HOURS + timedelta(seconds=1)

    assert watcher.poll() == ["R1: stopped watching app · E2E #4/2 after 6 h; it had not finished."]
    assert watcher.runs[0].state == "no longer watched"


def test_a_rate_limit_stops_the_round_and_errors_are_shown() -> None:
    runs = FakeRuns(states={4: [GitHubApiError("gone (HTTP 404)", 404)],
                            5: [ApiRateLimitError("rate limit")]})  # fmt: skip
    watcher = watch(runs)
    watcher.add(rerun(4))
    watcher.add(rerun(5))
    watcher.add(replace(rerun(6), done=True))

    assert watcher.poll() == []
    assert [run.state for run in watcher.runs] == [
        "queued · waiting for GitHub's rate limit",
        "queued · waiting for GitHub's rate limit",
        "no longer watched",
    ]
    runs.states[5] = [state(5, attempt=1)]
    watcher.poll()
    assert watcher.runs[0].state == "queued · cannot read it: gone (HTTP 404)"


def test_watched_runs_survive_a_round_trip() -> None:
    run = replace(rerun(), number=3, group=2, done=True)

    assert WatchedRun.from_dict(run.to_dict()) == run
    assert watch(FakeRuns()).find(1) is None
