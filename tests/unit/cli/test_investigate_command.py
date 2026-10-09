import io
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace

import click
import pytest
from rich.console import Console
from typer.testing import CliRunner

from flakipype.agent.investigator import Status
from flakipype.agent.verdict import Verdict
from flakipype.cli import app, wiring
from flakipype.cli.investigation_report import render_investigation
from flakipype.config.settings import GitHubSettings, Settings
from flakipype.github.actions import GitHubApiError
from flakipype.investigate.service import (
    InvestigationReport,
    InvestigationRequest,
    InvestigationResult,
    InvestigationService,
    Selection,
)
from flakipype.scan.service import ScanService
from flakipype.store.database import ScanCache

from support.builders import START
from support.fake_actions import FakeActions
from support.fake_anthropic import verdict_input
from support.fake_investigation import SCAN, FakeAgent, world

runner = CliRunner()
SETTINGS = Settings(github=GitHubSettings(owner="octo-org"))


def use(
    monkeypatch: pytest.MonkeyPatch, agent: FakeAgent, actions: FakeActions | None = None
) -> None:
    @contextmanager
    def open_investigation() -> Iterator[tuple[InvestigationService, Settings]]:
        with ScanCache.in_memory() as cache:
            scan = ScanService(
                actions=actions or world(), cache=cache, now=lambda: START.replace(day=9)
            )
            yield (
                InvestigationService(
                    scan=scan, cache=cache, investigate=agent, run_tokens=10**6, parallel=2
                ),
                SETTINGS,
            )

    monkeypatch.setattr(wiring, "open_investigation", open_investigation)


def test_investigate_prints_verdicts_with_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = FakeAgent()
    use(monkeypatch, agent)

    result = runner.invoke(app, ["investigate"])

    assert result.exit_code == 0, result.output
    text = click.unstyle(result.stdout)
    assert "Investigated 2 findings · 2,000 tokens used" in text
    assert "#1 octo-org/app › CI › test" in text
    assert "flaky test · confidence high" in text
    assert "“quote”" in text
    assert "review: accepted: ok" in text
    assert sorted(agent.calls) == [1, 3]


def test_investigate_json_for_chosen_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, FakeAgent())

    result = runner.invoke(app, ["investigate", "--finding", "2", "--finding", "7", "--json"])

    exported = json.loads(result.stdout)
    assert exported["unknown_findings"] == [7]
    (investigation,) = exported["investigations"]
    assert (investigation["finding"], investigation["kind"], investigation["status"]) == (
        2,
        "seen_once",
        "completed",
    )
    assert investigation["verdict"]["classification"] == "flaky_test"
    assert exported["scan"]["jobs"][1]["finding"] == 2


def test_all_and_incomplete_runs_exit_with_one(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = FakeAgent(status=Status.NO_VERDICT)
    use(monkeypatch, agent)

    result = runner.invoke(app, ["investigate", "--all", "--fresh"])

    assert result.exit_code == 1
    assert sorted(agent.calls) == [1, 2, 3]
    assert "no verdict" in click.unstyle(result.stdout)


class NotReady:
    def __enter__(self) -> tuple[InvestigationService, Settings]:
        message = "No API key stored."
        raise wiring.NotReadyError(message)

    def __exit__(self, *_: object) -> None:
        return None


def test_not_ready_and_github_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wiring, "open_investigation", NotReady)
    assert runner.invoke(app, ["investigate"]).exit_code == 2

    broken = FakeActions(repositories_error=GitHubApiError("gh: Not Found (HTTP 404)", 404))
    use(monkeypatch, FakeAgent(), broken)
    result = runner.invoke(app, ["investigate"])
    assert result.exit_code == 1
    assert "GitHub: gh: Not Found" in click.unstyle(result.output)


def run_world() -> InvestigationReport:
    with ScanCache.in_memory() as cache:
        scan = ScanService(actions=world(), cache=cache, now=lambda: START.replace(day=9))
        service = InvestigationService(
            scan=scan, cache=cache, investigate=FakeAgent(), run_tokens=10**6, parallel=1
        )
        return service.run(InvestigationRequest(SCAN, Selection(numbers=(1,))))


def rendered(report: InvestigationReport) -> str:
    console = Console(file=io.StringIO(), width=120, record=True, color_system=None)
    console.print(render_investigation(report))
    return console.export_text()


def test_counter_evidence_open_questions_cache_and_failures_render() -> None:
    base = run_world()
    finding = base.scan.findings[0]
    detailed = Verdict.model_validate(
        {
            **verdict_input("quote " + "x" * 300, "finding"),
            "counter_evidence": [verdict_input("passes locally", "c1")["evidence"][0]],
            "open_questions": ["Does it fail on Windows runners?"],
        }
    )
    results = [
        InvestigationResult(finding, Status.COMPLETED, detailed, "", "", 0, 0, from_cache=True),
        InvestigationResult(finding, Status.LOOP, None, "", "Repeated the same call.", 900, 3),
    ]
    report = replace(base, results=results, tokens=900)

    text = rendered(report)

    assert "Counter-evidence" in text
    assert "Does it fail on Windows runners?" in text
    assert "from cache" in text
    assert "…”" in text
    assert "stopped: repeated itself" in text
    assert "900 tokens, 3 rounds" in text


def test_unknown_numbers_are_named(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, FakeAgent())

    result = runner.invoke(app, ["investigate", "--finding", "9"])

    text = click.unstyle(result.stdout)
    assert "No such finding: #9" in text
    assert "Nothing to investigate." in text


def test_nothing_to_investigate(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, FakeAgent(), FakeActions())

    result = runner.invoke(app, ["investigate"])

    assert "Nothing to investigate." in click.unstyle(result.stdout)
