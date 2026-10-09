"""Render investigation results: the model's assessment, always with its evidence."""

from typing import Any

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from flakipype.agent.investigator import Status
from flakipype.agent.verdict import Classification, Confidence, EvidenceItem, Verdict
from flakipype.investigate.service import InvestigationReport, InvestigationResult
from flakipype.scan.export import report_as_json

SCHEMA_VERSION = 1
_QUOTE_WIDTH = 220
_CLASSIFICATION_STYLE = {
    Classification.FLAKY_TEST: "bold yellow",
    Classification.FLAKY_INFRASTRUCTURE: "bold magenta",
    Classification.REAL_BUG: "bold red",
    Classification.CONFIGURATION: "bold blue",
    Classification.FIXED: "bold green",
    Classification.UNCLEAR: "bold white",
}
_CONFIDENCE_STYLE = {Confidence.HIGH: "green", Confidence.MEDIUM: "yellow", Confidence.LOW: "red"}
_STATUS_TEXT = {
    Status.BUDGET: "stopped by a limit",
    Status.LOOP: "stopped: repeated itself",
    Status.NO_VERDICT: "no verdict",
    Status.MODEL_ERROR: "model error",
}


def _quote(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _QUOTE_WIDTH else flat[: _QUOTE_WIDTH - 1] + "…"


def _evidence(title: str, items: list[EvidenceItem]) -> Text:
    text = Text(f"\n{title}\n", style="bold")
    for item in items:
        text.append(f" • {item.kind.value} ", style="cyan")
        text.append(f"{item.location}: ", style="dim")
        text.append(f"“{_quote(item.quote)}”\n")
        text.append(f"   {item.why_it_matters}\n", style="italic")
    return text


def _verdict_body(verdict: Verdict) -> Text:
    body = Text()
    body.append(
        verdict.classification.value.replace("_", " "),
        style=_CLASSIFICATION_STYLE[verdict.classification],
    )
    body.append(" · confidence ")
    body.append(verdict.confidence.value, style=_CONFIDENCE_STYLE[verdict.confidence])
    body.append(f"\n\n{verdict.summary}\n")
    body.append("\nCause: ", style="bold")
    body.append(verdict.cause)
    body.append("\nSuggested fix: ", style="bold")
    body.append(verdict.suggested_fix)
    body.append(_evidence("Evidence", verdict.evidence))
    if verdict.counter_evidence:
        body.append(_evidence("Counter-evidence", verdict.counter_evidence))
    if verdict.open_questions:
        body.append("\nOpen questions\n", style="bold")
        body.append("".join(f" • {question}\n" for question in verdict.open_questions))
    return body


def _panel(result: InvestigationResult) -> Panel:
    key = result.finding.key
    title = f"[bold]#{result.finding.number}[/] {key.repository} › {key.workflow_name} › {key.job}"
    if result.verdict is None:
        body = Text(_STATUS_TEXT.get(result.status, result.status.value), style="bold red")
        body.append(f"\n{result.detail}")
    else:
        body = _verdict_body(result.verdict)
    footer = [result.finding.kind.value.replace("_", " ")]
    if result.review:
        footer.append(f"review: {result.review}")
    footer.append(
        "from cache" if result.from_cache else f"{result.tokens:,} tokens, {result.rounds} rounds"
    )
    return Panel(
        body,
        title=title,
        title_align="left",
        subtitle=" · ".join(footer),
        subtitle_align="left",
        border_style="cyan" if result.verdict else "red",
    )


def render_investigation(report: InvestigationReport) -> RenderableType:
    header = Text()
    header.append(f"Investigated {len(report.results)} findings", style="bold")
    header.append(f" · {report.tokens:,} tokens used\n")
    header.append("Assessments by the model, with the evidence it cites. ", style="dim")
    header.append("The scan's facts: flakipype scan.", style="dim")
    if report.unknown_numbers:
        unknown = ", ".join(f"#{number}" for number in report.unknown_numbers)
        header.append(f"\nNo such finding: {unknown}", style="yellow")
    if not report.results:
        header.append("\nNothing to investigate.", style="green")
    return Group(header, *(_panel(result) for result in report.results))


def _result_json(result: InvestigationResult) -> dict[str, Any]:
    key = result.finding.key
    return {
        "finding": result.finding.number,
        "kind": result.finding.kind.value,
        "repository": key.repository,
        "workflow": {"name": key.workflow_name, "path": key.workflow_path},
        "job": key.job,
        "step": key.step,
        "status": result.status.value,
        "from_cache": result.from_cache,
        "review": result.review,
        "detail": result.detail,
        "tokens": result.tokens,
        "rounds": result.rounds,
        "verdict": result.verdict.model_dump(mode="json") if result.verdict else None,
    }


def investigation_as_json(report: InvestigationReport) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tokens": report.tokens,
        "unknown_findings": list(report.unknown_numbers),
        "investigations": [_result_json(result) for result in report.results],
        "scan": report_as_json(report.scan),
    }
