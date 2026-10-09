"""Render a scan report for the terminal."""

from datetime import datetime, timedelta

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from flakipype.flaky.scoring import FlakyJob
from flakipype.flaky.signature import Category
from flakipype.scan.service import ScanReport

_BAR_WIDTH = 10
_RED_FROM = 0.10
_YELLOW_FROM = 0.02
_MESSAGE_WIDTH = 140
_CATEGORY_STYLE = {
    Category.TIMEOUT: "yellow",
    Category.NETWORK: "magenta",
    Category.RATE_LIMIT: "magenta",
    Category.RESOURCES: "red",
    Category.RUNNER: "red",
    Category.DEPENDENCIES: "blue",
    Category.ASSERTION: "cyan",
}


def relative_time(moment: datetime, now: datetime) -> str:
    age = now - moment
    if age < timedelta(hours=1):
        return f"{max(int(age.total_seconds() // 60), 0)} min ago"
    if age < timedelta(days=1):
        return f"{int(age.total_seconds() // 3600)} h ago"
    return f"{age.days} d ago"


def rate_bar(rate: float) -> Text:
    filled = round(rate * _BAR_WIDTH)
    if rate > 0:
        filled = max(filled, 1)
    style = "red" if rate >= _RED_FROM else "yellow" if rate >= _YELLOW_FROM else "green"
    bar = Text()
    bar.append("█" * filled, style=style)
    bar.append("░" * (_BAR_WIDTH - filled), style="grey37")
    bar.append(f" {rate:6.1%}")
    return bar


def _summary(report: ScanReport) -> Panel:
    start, end = report.window.start, report.window.end
    days = (end - start).days
    lines = Text()
    lines.append(f"{report.repositories} repositories · {report.runs:,} runs · last {days} days ")
    lines.append(f"({start:%d %b} – {end:%d %b %Y})", style="dim")
    lines.append("\n")
    if report.flaky:
        workflows = {(f.key.repository, f.key.workflow_path) for f in report.flaky}
        lines.append(f"{len(report.flaky)} flaky jobs", style="bold red")
        lines.append(f" in {len(workflows)} workflows")
    else:
        lines.append("No flaky jobs found", style="bold green")
    title = f"[bold]flakipype scan[/] · {report.owner} on {report.host}"
    return Panel(lines, title=title, title_align="left", border_style="cyan")


def _signals(flaky: FlakyJob) -> Text:
    text = Text()
    if flaky.rerun_passed:
        text.append(f"↻ {flaky.rerun_passed} passed on rerun", style="bold")
    if flaky.same_commit:
        text.append("\n" if text else "")
        text.append(f"≡ {flaky.same_commit} same commit passed")
    return text


def _description(flaky: FlakyJob) -> Text:
    text = Text(flaky.key.repository, style="bold")
    path = " › ".join(
        part for part in (flaky.key.workflow_name, flaky.key.job, flaky.key.step) if part
    )
    text.append(f"\n{path}")
    for signature in flaky.signatures[:2]:
        style = _CATEGORY_STYLE.get(signature.category, "white")
        text.append(
            f"\n{signature.category.value} ×{signature.occurrences} ", style=f"bold {style}"
        )
        text.append(shorten(signature.message), style="dim")
    if flaky.examples:
        # A terminal hyperlink: the full URL would wrap across lines; --json has it in full.
        text.append("\nlatest failure ↗", style=f"underline cyan link {flaky.examples[0]}")
    return text


def shorten(message: str) -> str:
    if len(message) <= _MESSAGE_WIDTH:
        return message
    return message[: _MESSAGE_WIDTH - 1].rstrip() + "…"


def _flaky_table(report: ScanReport, now: datetime) -> Table:
    table = Table(header_style="bold", expand=True, show_lines=True, border_style="grey37")
    table.add_column("#", justify="right", width=3)
    table.add_column("Flaky job", ratio=3, overflow="fold")
    table.add_column("Runs", justify="right", no_wrap=True)
    table.add_column("Flake rate", no_wrap=True)
    table.add_column("Signal", no_wrap=True)
    table.add_column("Last seen", justify="right", no_wrap=True)
    for rank, flaky in enumerate(report.flaky, start=1):
        table.add_row(
            str(rank),
            _description(flaky),
            f"{flaky.affected_runs}/{flaky.total_runs}",
            rate_bar(flaky.flake_rate),
            _signals(flaky),
            relative_time(flaky.last_seen, now),
        )
    return table


def _notes(report: ScanReport) -> Panel | None:
    notes = list(report.problems)
    if report.logs_not_read:
        notes.append(
            f"{report.logs_not_read} logs not read (limit: scan.max_log_downloads). "
            "Run the scan again to read more; read logs are cached."
        )
    if not notes:
        return None
    body = Text("\n".join(f"• {note}" for note in notes))
    return Panel(body, title="Notes", title_align="left", border_style="yellow")


def render_report(report: ScanReport, now: datetime) -> RenderableType:
    parts: list[RenderableType] = [_summary(report)]
    if report.flaky:
        parts.append(_flaky_table(report, now))
    notes = _notes(report)
    if notes:
        parts.append(notes)
    return Group(*parts)
