from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from flakipype.github.actions import ApiRateLimitError, GitHubApiError, Repository
from flakipype.scan.progress import Progress, Stage
from flakipype.scan.service import ScanRequest, ScanService, select_repositories
from flakipype.store.database import ScanCache

from support.builders import job, run
from support.fake_actions import FakeActions

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
APP = "octo-org/app"
LOG = "2026-10-07T09:27:35Z ##[error]Test timed out after 5000ms\n"


BASE_REQUEST = ScanRequest(
    owner="octo-org",
    host="github.com",
    window_days=30,
    max_log_downloads=50,
    # The mechanics tests use single runs; verdict thresholds have their own tests.
    min_flaky_runs=1,
)


def request(**changes: Any) -> ScanRequest:
    return replace(BASE_REQUEST, **changes)


def flaky_world() -> FakeActions:
    """One run that failed once and passed on rerun, plus an ordinary passing run."""
    return FakeActions(
        repositories_found=[Repository(APP, "main"), Repository("octo-org/docs", "main")],
        runs_by_repository={APP: [run(1, attempt=2), run(2)]},
        jobs_by_attempt={(1, 1): [job(11, run_id=1), job(12, run_id=1, conclusion="success")]},
        logs={11: LOG},
    )


def service(actions: FakeActions, cache: ScanCache) -> ScanService:
    return ScanService(actions=actions, cache=cache, now=lambda: NOW)


def test_scan_finds_ranks_and_explains_a_flaky_job(cache: ScanCache) -> None:
    actions = flaky_world()

    report = service(actions, cache).scan(request())

    assert report.complete
    assert (report.repositories, report.runs, report.problems) == (2, 2, [])
    (flaky,) = report.ranking.flaky
    assert (flaky.key.repository, flaky.key.job, flaky.affected_runs, flaky.total_runs) == (
        APP,
        "test",
        1,
        2,
    )
    assert flaky.signatures[0].category.value == "timeout"
    assert report.window.end == NOW
    assert report.window.start == NOW - timedelta(days=30)
    assert actions.windows[0] == report.window


def test_second_scan_reuses_cached_jobs_and_logs(cache: ScanCache) -> None:
    actions = flaky_world()
    scanner = service(actions, cache)
    scanner.scan(request())
    actions.calls.clear()

    report = scanner.scan(request())

    assert actions.calls == ["repositories octo-org", f"runs {APP}", "runs octo-org/docs"]
    assert report.ranking.flaky[0].signatures


def test_default_threshold_separates_flaky_from_one_offs(cache: ScanCache) -> None:
    actions = flaky_world()
    actions.runs_by_repository[APP] = [
        run(1, attempt=2),
        run(2),
        run(3, attempt=2),
        run(4, attempt=2, workflow=".github/workflows/pages.yml", name="Pages"),
    ]
    actions.jobs_by_attempt[3, 1] = [job(31, run_id=3)]
    actions.jobs_by_attempt[4, 1] = [job(41, run_id=4, name="deploy")]

    report = service(actions, cache).scan(request(min_flaky_runs=2))

    assert [job.key.job for job in report.ranking.flaky] == ["test"]
    assert [job.key.job for job in report.ranking.seen_once] == ["deploy"]
    assert report.ranking.fixed == []


def test_recurring_errors_without_proof_are_listed_apart(cache: ScanCache) -> None:
    actions = FakeActions(
        repositories_found=[Repository(APP, "main")],
        runs_by_repository={
            APP: [
                run(1, conclusion="failure", sha="1" * 40),
                run(2, sha="2" * 40),
                run(3, conclusion="failure", sha="3" * 40),
                run(4, conclusion="failure", sha="4" * 40),
            ]
        },
        jobs_by_attempt={
            (1, 1): [job(11, run_id=1)],
            (3, 1): [job(31, run_id=3)],
            (4, 1): [job(41, run_id=4, name="lint", step="Run ruff")],
        },
        logs={11: LOG, 31: LOG, 41: "2026-10-07T09:27:35Z ##[error]E501 line too long\n"},
    )

    report = service(actions, cache).scan(request(min_flaky_runs=2))

    assert report.ranking.flaky == []
    (recurring,) = report.recurring
    assert (recurring.key.job, recurring.runs, recurring.branches) == ("test", 2, ("main",))
    assert recurring.signature.category.value == "timeout"


def test_proven_failures_get_their_logs_read_first(cache: ScanCache) -> None:
    actions = flaky_world()
    actions.runs_by_repository[APP] = [
        run(1, attempt=2),
        run(9, conclusion="failure", sha="9" * 40),
    ]
    actions.jobs_by_attempt[9, 1] = [job(91, run_id=9)]
    actions.logs[91] = LOG

    service(actions, cache).scan(request(max_log_downloads=1))

    assert [call for call in actions.calls if call.startswith("log")] == [f"log {APP} 11"]


def test_log_downloads_are_capped_newest_first(cache: ScanCache) -> None:
    actions = flaky_world()
    actions.runs_by_repository[APP] = [run(1, attempt=2), run(3, attempt=2)]
    actions.jobs_by_attempt[3, 1] = [job(31, run_id=3)]
    actions.logs[31] = LOG

    report = service(actions, cache).scan(request(max_log_downloads=1))

    assert [call for call in actions.calls if call.startswith("log")] == [f"log {APP} 31"]
    assert report.logs_not_read == 1


def test_expired_and_quiet_logs_are_cached_without_signature(cache: ScanCache) -> None:
    actions = flaky_world()
    actions.runs_by_repository[APP] = [run(1, attempt=2), run(3, attempt=2)]
    actions.jobs_by_attempt[3, 1] = [job(31, run_id=3)]
    actions.logs = {11: None, 31: "2026-10-07T09:27:35Z all quiet\n"}
    scanner = service(actions, cache)

    report = scanner.scan(request())
    actions.calls.clear()
    scanner.scan(request())

    assert report.ranking.flaky[0].signatures == ()
    assert not [call for call in actions.calls if call.startswith("log")]


def test_repository_errors_are_reported_and_skipped(cache: ScanCache) -> None:
    actions = flaky_world()
    actions.runs_by_repository["octo-org/docs"] = GitHubApiError("gh: Not Found (HTTP 404)", 404)
    actions.truncated.add(APP)

    report = service(actions, cache).scan(request())

    assert report.complete
    assert len(report.ranking.flaky) == 1
    assert report.problems == [
        f"{APP}: too many runs per minute; GitHub listed only some.",
        "octo-org/docs: could not list runs: gh: Not Found (HTTP 404)",
    ]


def test_failed_job_and_log_reads_are_retried_next_time(cache: ScanCache) -> None:
    actions = flaky_world()
    actions.jobs_by_attempt[1, 1] = GitHubApiError("gh: Server Error (HTTP 502)", 502)
    scanner = service(actions, cache)

    first = scanner.scan(request())
    actions.jobs_by_attempt = flaky_world().jobs_by_attempt
    actions.logs[11] = GitHubApiError("gh: Server Error (HTTP 502)", 502)
    second = scanner.scan(request())
    actions.logs[11] = LOG
    third = scanner.scan(request())

    assert first.ranking.flaky == []
    assert "could not read the jobs of run 1" in first.problems[0]
    assert second.ranking.flaky[0].signatures == ()
    assert "could not read the log of job 11" in second.problems[0]
    assert third.ranking.flaky[0].signatures


def test_rate_limit_stops_early_but_keeps_what_was_found(cache: ScanCache) -> None:
    actions = flaky_world()
    actions.runs_by_repository["octo-org/docs"] = ApiRateLimitError("API rate limit exceeded", 403)

    report = service(actions, cache).scan(request())

    assert not report.complete
    assert report.problems == ["Stopped early: API rate limit exceeded. Run the scan again later."]
    assert report.runs == 2


def test_rate_limit_while_reading_logs_counts_the_unread_ones(cache: ScanCache) -> None:
    actions = flaky_world()
    actions.logs[11] = ApiRateLimitError("API rate limit exceeded", 403)

    report = service(actions, cache).scan(request())

    assert not report.complete
    assert report.logs_not_read == 1
    assert len(report.ranking.flaky) == 1


def test_progress_reports_every_stage(cache: ScanCache) -> None:
    events: list[Progress] = []

    service(flaky_world(), cache).scan(request(), events.append)

    assert [event.stage for event in events] == [
        Stage.REPOSITORIES,
        Stage.RUNS,
        Stage.RUNS,
        Stage.RUNS,
        Stage.JOBS,
        Stage.JOBS,
        Stage.LOGS,
        Stage.LOGS,
    ]
    assert events[1] == Progress(Stage.RUNS, 0, 2, APP)
    assert events[-1] == Progress(Stage.LOGS, 1, 1)


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        ((), ["octo-org/app", "octo-org/docs"]),
        (("APP",), ["octo-org/app"]),
        (("octo-org/docs", "missing"), ["octo-org/docs"]),
    ],
)
def test_select_repositories(names: tuple[str, ...], expected: list[str]) -> None:
    repositories = [Repository("octo-org/app", "main"), Repository("octo-org/docs", "main")]

    selected = select_repositories(repositories, names)

    assert [repository.full_name for repository in selected] == expected
