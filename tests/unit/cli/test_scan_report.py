from datetime import UTC, datetime, timedelta

import pytest
from rich.console import Console

from flakipype.cli.scan_report import (
    plural,
    rate_bar,
    relative_time,
    render_report,
    seen_once_label,
    shorten,
)
from flakipype.flaky.recurring import RecurringError
from flakipype.flaky.scoring import FlakyJob, FlakyKey, SignatureCount
from flakipype.flaky.signature import Category, ErrorSignature
from flakipype.flaky.verdict import FlakyRanking
from flakipype.github.actions import TimeWindow
from flakipype.scan.service import ScanReport

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
WINDOW = TimeWindow(NOW - timedelta(days=30), NOW)
KEY = FlakyKey("besessener/Archivist", ".github/workflows/ci.yml", "CI", "test", "E2E")


def flaky_job(**changes: object) -> FlakyJob:
    base = FlakyJob(
        key=KEY,
        flaky_failures=4,
        affected_runs=4,
        total_runs=365,
        rerun_passed=4,
        same_commit=1,
        first_seen=NOW - timedelta(days=9),
        last_seen=NOW - timedelta(days=2),
        recurred=True,
        passing_since=NOW - timedelta(days=2),
        examples=("https://github.com/besessener/Archivist/actions/runs/1/job/2",),
        job_ids=(2,),
        signatures=(
            SignatureCount(Category.TIMEOUT, "toHaveCount timed out", "a" * 12, 4),
            SignatureCount(Category.OTHER, "something else", "b" * 12, 1),
        ),
    )
    return type(base)(**{**base.__dict__, **changes})


def recurring_error(**changes: object) -> RecurringError:
    base = RecurringError(
        key=FlakyKey("besessener/Archivist", ".github/workflows/ci.yml", "CI", "lint", "Run ruff"),
        signature=ErrorSignature(Category.ASSERTION, "expected 2 rows", "c" * 12, "excerpt"),
        runs=3,
        branches=("feature/x", "main"),
        first_seen=NOW - timedelta(days=20),
        last_seen=NOW - timedelta(hours=5),
        examples=(),
    )
    return type(base)(**{**base.__dict__, **changes})


def report(ranking: FlakyRanking, **changes: object) -> ScanReport:
    base = ScanReport(
        owner="besessener",
        host="github.com",
        window=WINDOW,
        repositories=18,
        runs=1370,
        ranking=ranking,
        recurring=[],
        problems=[],
        logs_not_read=0,
        complete=True,
    )
    return type(base)(**{**base.__dict__, **changes})


def ranking(
    flaky: list[FlakyJob] | None = None,
    seen_once: list[FlakyJob] | None = None,
    fixed: list[FlakyJob] | None = None,
) -> FlakyRanking:
    return FlakyRanking(2, flaky or [], seen_once or [], fixed or [])


def rendered(scan_report: ScanReport) -> str:
    console = Console(width=140, record=True, color_system=None)
    console.print(render_report(scan_report, now=NOW))
    return console.export_text()


def test_report_with_flaky_jobs() -> None:
    text = rendered(report(ranking(flaky=[flaky_job()])))

    assert "flakipype scan · besessener on github.com" in text
    assert "18 repositories · 1,370 runs · last 30 days (09 Sep – 09 Oct 2026)" in text
    assert "1 flaky job in 1 workflow" in text
    assert "CI › test › E2E" in text
    assert "timeout ×4 toHaveCount timed out" in text
    assert "↻ 4 passed on rerun" in text
    assert "≡ 1 same commit passed" in text
    assert "4/365" in text
    assert "2 d ago" in text
    assert "latest failure ↗" in text
    assert "Notes" not in text
    assert "Seen once" not in text


def test_seen_once_fixed_and_recurring_get_their_own_sections() -> None:
    once = flaky_job(affected_runs=1, rerun_passed=0, signatures=(), examples=())
    fixed = flaky_job(recurred=False)
    still_failing = flaky_job(recurred=False, passing_since=None)
    scan_report = report(
        ranking(seen_once=[once], fixed=[fixed, still_failing]),
        recurring=[recurring_error(), recurring_error(runs=2)],
    )

    text = rendered(scan_report)

    assert "No flaky jobs found · 1 seen once · 2 fixed · 2 recurring errors" in text
    assert "Seen once — could be a one-off outage or a fix, not counted" in text
    assert "≡ 1 same commit passed" in text
    assert "Fixed — failed in several runs, then kept passing; not flaky" in text
    assert "4 runs" in text
    assert "—" in text
    assert "Recurring errors — same error in several runs, no proof: flaky or a real bug" in text
    assert "assertion ×3 expected 2 rows" in text
    assert "feature/x, main" in text
    assert "5 h ago" in text


def test_long_messages_are_shortened() -> None:
    assert shorten("short") == "short"
    assert shorten("x" * 140) == "x" * 140
    assert shorten("word " * 40) == ("word " * 28).rstrip() + "…"


def test_labels_and_plurals() -> None:
    assert (plural(1, "run"), plural(2, "run")) == ("1 run", "2 runs")
    assert seen_once_label(2) == "seen once"
    assert seen_once_label(3) == "seen in fewer than 3 runs"


def test_clean_report_with_notes() -> None:
    problems = ["octo-org/docs: could not list runs: gh: Not Found (HTTP 404)"]

    text = rendered(report(ranking(), problems=problems, logs_not_read=3))

    assert "No flaky jobs found" in text
    assert "• octo-org/docs: could not list runs" in text
    assert "3 logs not read (limit: scan.max_log_downloads)" in text


@pytest.mark.parametrize(
    ("age", "text"),
    [
        (timedelta(seconds=30), "0 min ago"),
        (timedelta(minutes=59), "59 min ago"),
        (timedelta(hours=5), "5 h ago"),
        (timedelta(days=3, hours=4), "3 d ago"),
        (timedelta(minutes=-5), "0 min ago"),
    ],
)
def test_relative_time(age: timedelta, text: str) -> None:
    assert relative_time(NOW - age, NOW) == text


@pytest.mark.parametrize(
    ("rate", "filled", "style"),
    [
        (0.0, 0, "green"),
        (0.011, 1, "green"),
        (0.05, 1, "yellow"),
        (0.5, 5, "red"),
        (1.0, 10, "red"),
    ],
)
def test_rate_bar(rate: float, filled: int, style: str) -> None:
    bar = rate_bar(rate)

    assert bar.plain.count("█") == filled
    assert bar.plain.endswith(f"{rate:6.1%}")
    if filled:
        assert bar.spans[0].style == style
        assert bar.spans[0].end == filled
