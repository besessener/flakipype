from datetime import UTC, datetime, timedelta

import pytest
from rich.console import Console

from flakipype.cli.scan_report import rate_bar, relative_time, render_report, shorten
from flakipype.flaky.scoring import FlakyJob, FlakyKey, SignatureCount
from flakipype.flaky.signature import Category
from flakipype.github.actions import TimeWindow
from flakipype.scan.service import ScanReport

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
WINDOW = TimeWindow(NOW - timedelta(days=30), NOW)


def flaky_job(**changes: object) -> FlakyJob:
    base = FlakyJob(
        key=FlakyKey("besessener/Archivist", ".github/workflows/ci.yml", "CI", "test", "E2E"),
        flaky_failures=4,
        affected_runs=4,
        total_runs=365,
        rerun_passed=4,
        same_commit=1,
        last_seen=NOW - timedelta(days=2),
        examples=("https://github.com/besessener/Archivist/actions/runs/1/job/2",),
        job_ids=(2,),
        signatures=(
            SignatureCount(Category.TIMEOUT, "toHaveCount timed out", "a" * 12, 4),
            SignatureCount(Category.OTHER, "something else", "b" * 12, 1),
        ),
    )
    return type(base)(**{**base.__dict__, **changes})


def report(flaky: list[FlakyJob], **changes: object) -> ScanReport:
    base = ScanReport(
        owner="besessener",
        host="github.com",
        window=WINDOW,
        repositories=18,
        runs=1370,
        flaky=flaky,
        problems=[],
        logs_not_read=0,
        complete=True,
    )
    return type(base)(**{**base.__dict__, **changes})


def rendered(scan_report: ScanReport) -> str:
    console = Console(width=140, record=True, color_system=None)
    console.print(render_report(scan_report, now=NOW))
    return console.export_text()


def test_report_with_flaky_jobs() -> None:
    text = rendered(report([flaky_job()]))

    assert "flakipype scan · besessener on github.com" in text
    assert "18 repositories · 1,370 runs · last 30 days (09 Sep – 09 Oct 2026)" in text
    assert "1 flaky jobs in 1 workflows" in text
    assert "CI › test › E2E" in text
    assert "timeout ×4 toHaveCount timed out" in text
    assert "↻ 4 passed on rerun" in text
    assert "≡ 1 same commit passed" in text
    assert "4/365" in text
    assert "2 d ago" in text
    assert "latest failure ↗" in text
    assert "Notes" not in text


def test_long_messages_are_shortened() -> None:
    assert shorten("short") == "short"
    assert shorten("x" * 140) == "x" * 140
    assert shorten("word " * 40) == ("word " * 28).rstrip() + "…"


def test_same_commit_only_and_no_signatures() -> None:
    text = rendered(report([flaky_job(rerun_passed=0, signatures=(), examples=())]))

    assert "≡ 1 same commit passed" in text
    assert "passed on rerun" not in text


def test_clean_report_with_notes() -> None:
    problems = ["octo-org/docs: could not list runs: gh: Not Found (HTTP 404)"]

    text = rendered(report([], problems=problems, logs_not_read=3))

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
