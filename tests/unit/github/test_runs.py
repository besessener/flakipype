import json
from datetime import UTC, datetime

import pytest

from flakipype.github.actions import GitHubApiError
from flakipype.github.runs import RunControl, workflow_file

from support.fake_gh import FakeGh

REPO = "octo-org/app"
RUNS = f"repos/{REPO}/actions/runs"
DISPATCHES = f"repos/{REPO}/actions/workflows/e2e.yml/dispatches"


def not_found(fake_gh: FakeGh, args: list[str]) -> None:
    fake_gh.record(args, stderr="gh: Not Found (HTTP 404)", exit_code=1)


def post(path: str, *fields: str) -> list[str]:
    return ["api", "-X", "POST", path, *fields]


def test_reruns_and_cancel_post_to_the_run(fake_gh: FakeGh) -> None:
    for action in ("rerun-failed-jobs", "rerun", "cancel"):
        fake_gh.record(post(f"{RUNS}/7/{action}"))
    control = RunControl(fake_gh.cli())

    control.rerun_failed_jobs(REPO, 7)
    control.rerun(REPO, 7)
    control.cancel(REPO, 7)

    assert [call["args"][3] for call in fake_gh.invocations()] == [
        f"{RUNS}/7/rerun-failed-jobs",
        f"{RUNS}/7/rerun",
        f"{RUNS}/7/cancel",
    ]


def test_a_refused_rerun_raises_with_its_status(fake_gh: FakeGh) -> None:
    fake_gh.record(
        post(f"{RUNS}/7/rerun"),
        stderr="gh: Resource not accessible by integration (HTTP 403)",
        exit_code=1,
    )

    with pytest.raises(GitHubApiError) as raised:
        RunControl(fake_gh.cli()).rerun(REPO, 7)

    assert raised.value.status == 403


def test_dispatch_returns_the_run_id_when_github_does(fake_gh: FakeGh) -> None:
    answer = {"workflow_run_id": 42, "run_url": "u", "html_url": "h"}
    fake_gh.record(post(DISPATCHES, "-f", "ref=main"), stdout=json.dumps(answer))
    fake_gh.record(post(DISPATCHES, "-f", "ref=v1"))
    control = RunControl(fake_gh.cli())

    assert control.dispatch(REPO, ".github/workflows/e2e.yml", "main") == 42
    assert control.dispatch(REPO, ".github/workflows/e2e.yml", "v1") is None


def test_dispatched_runs_are_found_by_the_logged_in_user(fake_gh: FakeGh) -> None:
    fake_gh.record(["api", "user"], stdout='{"login": "octocat"}')
    query = (
        "event=workflow_dispatch&branch=main&actor=octocat"
        "&created=>=2026-10-09T08:00:00Z&per_page=20"
    )
    runs = {
        "total_count": 2,
        "workflow_runs": [
            {"id": 9, "path": "p", "head_sha": "s", "event": "workflow_dispatch",
             "created_at": "2026-10-09T08:01:00Z", "html_url": "h"},
            {"id": 8, "path": "p", "head_sha": "s", "event": "workflow_dispatch",
             "created_at": "2026-10-09T08:00:30Z", "html_url": "h"},
        ],
    }  # fmt: skip
    fake_gh.record(
        ["api", f"repos/{REPO}/actions/workflows/e2e.yml/runs?{query}"], stdout=json.dumps(runs)
    )

    found = RunControl(fake_gh.cli()).dispatched_runs(
        REPO, ".github/workflows/e2e.yml", ref="main", since=datetime(2026, 10, 9, 8, tzinfo=UTC)
    )

    assert found == [8, 9]


def test_run_and_job_states(fake_gh: FakeGh) -> None:
    run = {
        "id": 7, "name": "E2E", "path": ".github/workflows/e2e.yml", "status": "in_progress",
        "conclusion": None, "run_attempt": 2, "head_sha": "abc", "head_branch": "main",
        "html_url": "https://github.com/octo-org/app/actions/runs/7",
    }  # fmt: skip
    jobs = {"jobs": [{"name": "e2e", "status": "completed", "conclusion": "success"}]}
    fake_gh.record(["api", f"{RUNS}/7"], stdout=json.dumps(run))
    fake_gh.record(["api", f"{RUNS}/7/attempts/2/jobs?per_page=100"], stdout=json.dumps(jobs))
    control = RunControl(fake_gh.cli())

    state = control.run_state(REPO, 7)
    (job,) = control.job_states(REPO, 7, 2)

    assert (state.workflow_name, state.attempt, state.completed) == ("E2E", 2, False)
    assert (job.name, job.status, job.conclusion) == ("e2e", "completed", "success")


def test_failed_reads_raise(fake_gh: FakeGh) -> None:
    not_found(fake_gh, ["api", f"{RUNS}/7"])

    with pytest.raises(GitHubApiError):
        RunControl(fake_gh.cli()).run_state(REPO, 7)


def test_default_branch_and_refs(fake_gh: FakeGh) -> None:
    fake_gh.record(["api", f"repos/{REPO}"], stdout='{"default_branch": "main"}')
    fake_gh.record(["api", f"repos/{REPO}/branches/main"], stdout='{"commit": {"sha": "abc"}}')
    not_found(fake_gh, ["api", f"repos/{REPO}/branches/v1"])
    fake_gh.record(["api", f"repos/{REPO}/git/ref/tags/v1"], stdout='{"object": {"sha": "def"}}')
    not_found(fake_gh, ["api", f"repos/{REPO}/branches/a%2Fb"])
    not_found(fake_gh, ["api", f"repos/{REPO}/git/ref/tags/a%2Fb"])
    fake_gh.record(
        ["api", f"repos/{REPO}/branches/boom"], stderr="gh: Error (HTTP 500)", exit_code=1
    )
    control = RunControl(fake_gh.cli())

    assert control.default_branch(REPO) == "main"
    assert control.ref_commit(REPO, "main") == "abc"
    assert control.ref_commit(REPO, "v1") == "def"
    assert control.ref_commit(REPO, "a/b") is None
    with pytest.raises(GitHubApiError):
        control.ref_commit(REPO, "boom")


def test_workflow_files_are_named_by_their_file() -> None:
    assert workflow_file(".github/workflows/my ci.yml") == "my%20ci.yml"
