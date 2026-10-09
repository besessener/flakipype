"""Compact Markdown views of scans, findings and verdicts, for the model and the chat window."""

from flakipype.agent.verdict import EvidenceItem
from flakipype.flaky.findings import Finding, FindingKind
from flakipype.investigate.service import InvestigationResult
from flakipype.scan.service import ScanReport

_KIND_LABEL = {
    FindingKind.FLAKY: "flaky",
    FindingKind.SEEN_ONCE: "seen once",
    FindingKind.FIXED: "fixed",
    FindingKind.RECURRING: "recurring error",
}
_QUOTE_LENGTH = 300

HELP = """\
**Commands**

- `/scan [days]` – scan the workflow runs and number the findings
- `/findings` – list the findings of the current scan
- `/investigate N [N …] | all [--fresh]` – let the agent investigate findings
- `/why N` – show the verdict for finding N with its evidence
- `/fix N [--fresh]` – write a fix for finding N and push it as a draft pull request
- `/rerun N [--all]` – rerun the failed jobs (or all jobs) of finding N's newest run
- `/dispatch N [ref] [xK]` – start finding N's workflow on the default branch or `ref`, K times
- `/runs` – runs started in this session · `/cancel R` – cancel run R
- `/actions` – the actions requested in this session
- `/mode ask|auto` – confirm every action, or let them run within the budgets
- `/budget` – tokens used in this session
- `/sessions` – recent sessions · `/resume N` – continue one · `/new` – start over
- `/help` – this list · `/quit` – leave (also Ctrl+Q)

Or just ask, e.g. *why does the E2E test of Archivist fail?*"""


def finding_title(finding: Finding) -> str:
    key = finding.key
    return f"{key.repository} › {key.workflow_name} › {key.job}"


def kind_label(kind: FindingKind) -> str:
    return _KIND_LABEL[kind]


def scan_summary(report: ScanReport) -> str:
    counts = dict.fromkeys(FindingKind, 0)
    for finding in report.findings:
        counts[finding.kind] += 1
    parts = ", ".join(f"{count} {_KIND_LABEL[kind]}" for kind, count in counts.items() if count)
    window = f"{report.window.start:%d %b} – {report.window.end:%d %b}"
    lines = [
        (
            f"Scanned {report.repositories} repositories and {report.runs:,} runs of "
            f"{report.owner} on {report.host} ({window})."
        ),
        f"Findings: {parts or 'none'}.",
    ]
    lines.extend(f"Note: {problem}" for problem in report.problems)
    if not report.complete:
        lines.append("The scan stopped early; results are incomplete.")
    return "\n".join(lines)


def findings_text(findings: list[Finding]) -> str:
    if not findings:
        return "No findings."
    blocks = []
    for finding in findings:
        facts = "\n".join(f"  - {fact}" for fact in finding.facts)
        blocks.append(
            f"#{finding.number} [{_KIND_LABEL[finding.kind]}] {finding_title(finding)}\n{facts}"
        )
    return "\n\n".join(blocks)


def _evidence(items: list[EvidenceItem]) -> list[str]:
    lines = []
    for item in items:
        quote = " ".join(item.quote.split())[:_QUOTE_LENGTH]
        lines.append(f"- {item.kind.value} {item.location}: “{quote}” — {item.why_it_matters}")
    return lines


def result_text(result: InvestigationResult) -> str:
    header = f"#{result.finding.number} {finding_title(result.finding)}"
    verdict = result.verdict
    if verdict is None:
        return f"{header}\nNo verdict ({result.status.value}): {result.detail}"
    lines = [
        header,
        f"Classification: {verdict.classification.value}, confidence {verdict.confidence.value}",
        f"Summary: {verdict.summary}",
        f"Cause: {verdict.cause}",
        f"Suggested fix: {verdict.suggested_fix}",
        "Evidence:",
        *_evidence(verdict.evidence),
    ]
    if verdict.counter_evidence:
        lines.extend(["Counter-evidence:", *_evidence(verdict.counter_evidence)])
    if verdict.open_questions:
        lines.extend(["Open questions:", *(f"- {q}" for q in verdict.open_questions)])
    review = result.review or "not reviewed"
    source = "stored verdict" if result.from_cache else f"{result.tokens:,} tokens"
    lines.append(f"Review: {review} ({source})")
    return "\n".join(lines)
