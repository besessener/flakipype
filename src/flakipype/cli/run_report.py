"""The summary of a `flakipype run`: plain lines for the journal, or JSON."""

from collections import Counter
from dataclasses import asdict
from typing import Any

from flakipype.fix.state import OpenedPull
from flakipype.investigate.chat_text import kind_label
from flakipype.scan.export import report_as_json
from flakipype.unattended.service import RunReport

SCHEMA_VERSION = 1
_INDENT = " " * 14


def render_run(report: RunReport) -> str:
    owner = report.scan.owner if report.scan else "—"
    # Local time, like the timer's schedule and the journal; the JSON keeps UTC.
    started, finished = report.started.astimezone(), report.finished.astimezone()
    lines = [
        f"flakipype run · {owner} · {report.mode} · {started:%Y-%m-%d %H:%M}–{finished:%H:%M %Z}",
        _scan_line(report),
        _investigated_line(report),
        *_block("Fixes", [f"#{fix.finding} {fix.title}: {fix.text}" for fix in report.fixes]),
        *_block("Verification", [_pull_line(pull) for pull in report.pulls]),
        _budget_line(report),
        *_block("Stopped by", list(report.stops)),
        *_block("Problems", [*(report.scan.problems if report.scan else []), *report.problems]),
    ]
    return "\n".join(lines)


def _scan_line(report: RunReport) -> str:
    scan = report.scan
    if scan is None:
        return "Scan: not finished"
    counts = Counter(kind_label(finding.kind) for finding in scan.findings)
    found = ", ".join(f"{count} {label}" for label, count in counts.items()) or "no findings"
    stopped = "; stopped early" if not scan.complete else ""
    return f"Scan: {scan.repositories} repositories, {scan.runs:,} runs, {found}{stopped}"


def _investigated_line(report: RunReport) -> str:
    fresh = [result for result in report.results if not result.from_cache]
    cached = len(report.results) - len(fresh)
    verdicts = Counter(
        result.verdict.classification.value if result.verdict else f"no verdict ({result.status})"
        for result in fresh
    )
    parts = ", ".join(f"{count} {label}" for label, count in verdicts.items())
    return (
        f"Investigated: {len(fresh)}"
        + (f" ({parts})" if parts else "")
        + (f", {cached} verdicts from the cache" if cached else "")
    )


def _pull_line(pull: OpenedPull) -> str:
    verification = pull.verification
    name = f"{verification.repository}#{verification.pull_number}"
    if pull.verified:
        return f"{name}: {verification.outcome.splitlines()[0]}"
    done = len(verification.results)
    unread = f" ({verification.detail})" if verification.detail else ""
    return f"{name}: {done} of {verification.wanted} runs, continues in the next run{unread}"


def _budget_line(report: RunReport) -> str:
    limits, used = report.limits, report.limits.day_used
    return (
        f"Budget: pull requests today {used.pull_requests + report.pull_requests} of "
        f"{limits.day_limits.pull_requests} · actions today {used.actions + report.actions} of "
        f"{limits.day_limits.actions} · tokens {report.tokens:,} of {limits.tokens:,} "
        f"(today {used.tokens + report.tokens:,} of {limits.day_limits.tokens:,})"
    )


def _block(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    label = f"{title}: "
    return [label + items[0], *(_INDENT[: len(label)] + item for item in items[1:])]


def run_as_json(report: RunReport) -> dict[str, Any]:
    limits = report.limits
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": report.mode.value,
        "started": report.started.isoformat(),
        "finished": report.finished.isoformat(),
        "complete": report.complete,
        "investigations": [
            {
                "finding": result.finding.number,
                "status": result.status.value,
                "classification": result.verdict.classification.value if result.verdict else None,
                "review": result.review,
                "from_cache": result.from_cache,
            }
            for result in report.results
        ],
        "fixes": [{**asdict(fix), "kind": fix.kind.value} for fix in report.fixes],
        "pull_requests": [
            {
                "url": pull.url,
                "finding": pull.finding,
                "verified": pull.verified,
                "results": list(pull.verification.results),
                "outcome": pull.verification.outcome,
            }
            for pull in report.pulls
        ],
        "budget": {
            "run": {"pull_requests": report.pull_requests, "actions": report.actions,
                    "tokens": report.tokens},
            "run_limits": {"pull_requests": limits.pull_requests, "actions": limits.actions,
                           "tokens": limits.tokens, "minutes": limits.minutes},
            "day_before": asdict(limits.day_used),
            "day_limits": asdict(limits.day_limits),
        },
        "stops": list(report.stops),
        "problems": list(report.problems),
        "scan": report_as_json(report.scan) if report.scan else None,
    }  # fmt: skip
