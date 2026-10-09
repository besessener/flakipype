"""An investigation world: a scan with one finding of each kind, and an agent stand-in."""

import threading
from dataclasses import dataclass, field

from flakipype.agent.budget import RunBudget
from flakipype.agent.investigator import Status
from flakipype.agent.pipeline import FindingResult
from flakipype.agent.verdict import Verdict
from flakipype.flaky.findings import Evidence, Finding
from flakipype.github.actions import Repository
from flakipype.scan.service import ScanRequest

from support.builders import job, run
from support.fake_actions import FakeActions
from support.fake_anthropic import verdict_input

APP = "octo-org/app"
LOG = "2026-10-07T09:27:35Z ##[error]Test timed out after 5000ms\n"
LINT = "2026-10-07T09:27:35Z ##[error]E501 line too long\n"
SCAN = ScanRequest(owner="octo-org", host="github.com", window_days=30, max_log_downloads=50)


def world() -> FakeActions:
    """Finding 1 flaky (CI test), 2 seen once (E2E), 3 recurring (lint)."""
    e2e = ".github/workflows/e2e.yml"
    return FakeActions(
        repositories_found=[Repository(APP, "main")],
        runs_by_repository={
            APP: [
                run(1, attempt=2),
                run(2),
                run(3, attempt=2),
                run(4, attempt=2, workflow=e2e, name="E2E"),
                run(5, conclusion="failure", sha="5" * 40),
                run(6, conclusion="failure", sha="6" * 40),
            ]
        },
        jobs_by_attempt={
            (1, 1): [job(11, run_id=1)],
            (3, 1): [job(31, run_id=3)],
            (4, 1): [job(41, run_id=4, name="e2e")],
            (5, 1): [job(51, run_id=5, name="lint", step="Run ruff")],
            (6, 1): [job(61, run_id=6, name="lint", step="Run ruff")],
        },
        logs={11: LOG, 31: LOG, 41: LOG, 51: LINT, 61: LINT},
    )


@dataclass
class FakeAgent:
    calls: list[int] = field(default_factory=list)
    status: Status = Status.COMPLETED
    tokens: int = 1_000
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __call__(
        self, finding: Finding, *, evidence: Evidence, run_budget: RunBudget
    ) -> FindingResult:
        with self.lock:
            self.calls.append(finding.number)
        assert evidence.runs
        run_budget.add(self.tokens)
        verdict = Verdict.model_validate(verdict_input("quote", "finding"))
        good = self.status is Status.COMPLETED
        return FindingResult(
            self.status, verdict if good else None, "accepted: ok", "", self.tokens, 2
        )
