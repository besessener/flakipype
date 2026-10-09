"""Render a scan report for the terminal."""

from datetime import datetime, timedelta

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from flakipype.flaky.recurring import RecurringError
from flakipype.flaky.scoring import FlakyJob, FlakyKey, SignatureCount
from flakipype.flaky.signature import Category
from flakipype.scan.service import ScanReport

_BAR_WIDTH = 10
_RED_FROM = 0.10
_YELLOW_FROM = 0.02
_MESSAGE_WIDTH = 140
# With the default min_flaky_runs of 2, fewer runs simply means once.
_ONCE = 2
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


def noun(count: int, word: str) -> str:
    return word if count == 1 else f"{word}s"


def plural(count: int, word: str) -> str:
    return f"{count} {noun(count, word)}"


def shorten(message: str) -> str:
    if len(message) <= _MESSAGE_WIDTH:
        return message
    return message[: _MESSAGE_WIDTH - 1].rstrip() + "…"


def seen_once_label(min_runs: int) -> str:
    if min_runs == _ONCE:
        return "seen once"
    return f"seen in fewer than {min_runs} runs"


def _summary(report: ScanReport) -> Panel:
    start, end = report.window.start, report.window.end
    ranking = report.ranking
    lines = Text()
    lines.append(f"{report.repositories} repositories · {report.runs:,} runs · ")
    lines.append(f"last {(end - start).days} days ")
    lines.append(f"({start:%d %b} – {end:%d %b %Y})", style="dim")
    lines.append("\n")
    if ranking.flaky:
        workflows = {(job.key.repository, job.key.workflow_path) for job in ranking.flaky}
        lines.append(plural(len(ranking.flaky), "flaky job"), style="bold red")
        lines.append(f" in {plural(len(workflows), 'workflow')}")
    else:
        lines.append("No flaky jobs found", style="bold green")
    extras = [
        (len(ranking.seen_once), seen_once_label(ranking.min_runs)),
        (len(ranking.fixed), "fixed"),
        (len(report.recurring), noun(len(report.recurring), "recurring error")),
    ]
    for count, label in extras:
        if count:
            lines.append(f" · {count} {label}", style="yellow")
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


def _job_text(key: FlakyKey, signatures: tuple[SignatureCount, ...], example: str) -> Text:
    text = Text(key.repository, style="bold")
    path = " › ".join(part for part in (key.workflow_name, key.job, key.step) if part)
    text.append(f"\n{path}")
    for signature in signatures[:2]:
        style = _CATEGORY_STYLE.get(signature.category, "white")
        text.append(
            f"\n{signature.category.value} ×{signature.occurrences} ", style=f"bold {style}"
        )
        text.append(shorten(signature.message), style="dim")
    if example:
        # A terminal hyperlink: the full URL would wrap across lines; --json has it in full.
        text.append("\nlatest failure ↗", style=f"underline cyan link {example}")
    return text


def _flaky_text(flaky: FlakyJob) -> Text:
    return _job_text(flaky.key, flaky.signatures, flaky.examples[0] if flaky.examples else "")


def _recurring_text(error: RecurringError) -> Text:
    signature = error.signature
    count = SignatureCount(signature.category, signature.message, signature.fingerprint, error.runs)
    return _job_text(error.key, (count,), error.examples[0] if error.examples else "")


def _table(title: str = "", style: str = "") -> Table:
    return Table(
        title=title or None, title_justify="left", title_style=style, header_style="bold",
        expand=True, show_lines=True, border_style="grey37",
    )  # fmt: skip


def _flaky_table(report: ScanReport, now: datetime) -> Table:
    table = _table()
    table.add_column("#", justify="right", width=3)
    table.add_column("Flaky job", ratio=3, overflow="fold")
    table.add_column("Runs", justify="right", no_wrap=True)
    table.add_column("Flake rate", no_wrap=True)
    table.add_column("Signal", no_wrap=True)
    table.add_column("Last seen", justify="right", no_wrap=True)
    for rank, flaky in enumerate(report.ranking.flaky, start=1):
        table.add_row(
            str(rank),
            _flaky_text(flaky),
            f"{flaky.affected_runs}/{flaky.total_runs}",
            rate_bar(flaky.flake_rate),
            _signals(flaky),
            relative_time(flaky.last_seen, now),
        )
    return table


def _seen_once_table(report: ScanReport, now: datetime) -> Table:
    label = seen_once_label(report.ranking.min_runs).capitalize()
    table = _table(f"{label} — could be a one-off outage or a fix, not counted", "yellow")
    table.add_column("#", justify="right", width=3)
    table.add_column("Job", ratio=3, overflow="fold")
    table.add_column("Signal", no_wrap=True)
    table.add_column("Last seen", justify="right", no_wrap=True)
    first = len(report.ranking.flaky) + 1
    for number, flaky in enumerate(report.ranking.seen_once, start=first):
        last_seen = relative_time(flaky.last_seen, now)
        table.add_row(str(number), _flaky_text(flaky), _signals(flaky), last_seen)
    return table


def _fixed_table(report: ScanReport, now: datetime) -> Table:
    table = _table("Fixed — failed in several runs, then kept passing; not flaky", "green")
    table.add_column("#", justify="right", width=3)
    table.add_column("Job", ratio=3, overflow="fold")
    table.add_column("Failed", justify="right", no_wrap=True)
    table.add_column("Passing since", justify="right", no_wrap=True)
    first = len(report.ranking.flaky) + len(report.ranking.seen_once) + 1
    for number, flaky in enumerate(report.ranking.fixed, start=first):
        since = relative_time(flaky.passing_since, now) if flaky.passing_since else "—"
        table.add_row(str(number), _flaky_text(flaky), plural(flaky.affected_runs, "run"), since)
    return table


def _recurring_table(report: ScanReport, now: datetime) -> Table:
    title = "Recurring errors — same error in several runs, no proof: flaky or a real bug"
    table = _table(title, "magenta")
    table.add_column("#", justify="right", width=3)
    table.add_column("Job", ratio=3, overflow="fold")
    table.add_column("Runs", justify="right", no_wrap=True)
    table.add_column("Branches", ratio=1, overflow="fold")
    table.add_column("Last seen", justify="right", no_wrap=True)
    ranking = report.ranking
    first = len(ranking.flaky) + len(ranking.seen_once) + len(ranking.fixed) + 1
    for number, error in enumerate(report.recurring, start=first):
        table.add_row(
            str(number),
            _recurring_text(error),
            str(error.runs),
            ", ".join(error.branches),
            relative_time(error.last_seen, now),
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
    sections = (
        (report.ranking.flaky, _flaky_table),
        (report.ranking.seen_once, _seen_once_table),
        (report.ranking.fixed, _fixed_table),
        (report.recurring, _recurring_table),
    )
    parts.extend(build(report, now) for entries, build in sections if entries)
    notes = _notes(report)
    if notes:
        parts.append(notes)
    return Group(*parts)
