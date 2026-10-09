from dataclasses import replace

from flakipype.agent.investigator import Status
from flakipype.agent.verdict import Verdict
from flakipype.flaky.findings import FindingKind
from flakipype.investigate.chat_text import findings_text, kind_label, result_text, scan_summary
from flakipype.investigate.service import InvestigationResult
from flakipype.scan.service import ScanReport
from flakipype.store.database import ScanCache

from support.fake_actions import FakeActions
from support.fake_anthropic import verdict_input
from support.fake_chat import chat_workspace
from support.fake_investigation import FakeAgent


def scanned(cache: ScanCache, actions: FakeActions | None = None) -> ScanReport:
    workspace = chat_workspace(cache, FakeAgent(), actions)
    workspace.findings()
    assert workspace.report is not None
    return workspace.report


def test_summary_counts_kinds_and_names_problems(cache: ScanCache) -> None:
    report = replace(scanned(cache), problems=["octo-org/old: Not Found"], complete=False)

    lines = scan_summary(report).splitlines()

    assert lines == [
        "Scanned 1 repositories and 6 runs of octo-org on github.com (09 Sep – 09 Oct).",
        "Findings: 1 flaky, 1 seen once, 1 recurring error.",
        "Note: octo-org/old: Not Found",
        "The scan stopped early; results are incomplete.",
    ]


def test_an_empty_scan(cache: ScanCache) -> None:
    report = scanned(cache, FakeActions())

    assert scan_summary(report).endswith("Findings: none.")
    assert findings_text(report.findings) == "No findings."
    assert kind_label(FindingKind.FIXED) == "fixed"


def test_results_show_evidence_counter_evidence_and_questions(cache: ScanCache) -> None:
    finding = scanned(cache).findings[0]
    verdict = Verdict.model_validate(
        {
            **verdict_input("quote\n  " + "x" * 400, "finding"),
            "counter_evidence": [verdict_input("passes locally", "c1")["evidence"][0]],
            "open_questions": ["Does it fail on Windows runners?"],
        }
    )
    stored = InvestigationResult(finding, Status.COMPLETED, verdict, "", "", 0, 0, from_cache=True)
    fresh = replace(stored, review="accepted: ok", tokens=1_500, from_cache=False)

    text = result_text(stored)

    assert text.startswith("#1 octo-org/app › CI › test\nClassification: flaky_test")
    assert f"“quote {'x' * 294}” — the wait timed out" in text
    assert "Counter-evidence:\n- log job 11: “passes locally”" in text
    assert "Open questions:\n- Does it fail on Windows runners?" in text
    assert text.endswith("Review: not reviewed (stored verdict)")
    assert result_text(fresh).endswith("Review: accepted: ok (1,500 tokens)")


def test_results_without_a_verdict(cache: ScanCache) -> None:
    finding = scanned(cache).findings[0]
    result = InvestigationResult(finding, Status.LOOP, None, "", "Repeated the same call.", 9, 3)

    assert result_text(result).endswith("No verdict (loop): Repeated the same call.")
