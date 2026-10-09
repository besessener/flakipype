import json
from datetime import UTC, datetime

from flakipype.github.actions import Repository
from flakipype.scan.export import SCHEMA_VERSION, report_as_json
from flakipype.scan.service import ScanRequest, ScanService
from flakipype.store.database import ScanCache

from support.builders import job, run
from support.fake_actions import FakeActions

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
TIMEOUT_LOG = "2026-10-07T09:27:35Z ##[error]Test timed out after 5000ms\n"
LINT_LOG = "2026-10-07T09:27:35Z ##[error]E501 line too long\n"


def test_json_report_has_a_stable_documented_shape(cache: ScanCache) -> None:
    actions = FakeActions(
        repositories_found=[Repository("octo-org/app", "main")],
        runs_by_repository={
            "octo-org/app": [
                run(1, attempt=2),
                run(2),
                run(3),
                run(4, conclusion="failure", sha="4" * 40),
                run(5, conclusion="failure", sha="5" * 40),
            ]
        },
        jobs_by_attempt={
            (1, 1): [job(11, run_id=1)],
            (4, 1): [job(41, run_id=4, name="lint", step="Run ruff")],
            (5, 1): [job(51, run_id=5, name="lint", step="Run ruff")],
        },
        logs={11: TIMEOUT_LOG, 41: LINT_LOG, 51: LINT_LOG},
    )
    scanner = ScanService(actions=actions, cache=cache, now=lambda: NOW)
    request = ScanRequest(owner="octo-org", host="github.com", window_days=30, max_log_downloads=5)

    report = scanner.scan(request)
    exported = report_as_json(report)

    timeout = report.ranking.seen_once[0].signatures[0].fingerprint
    lint = report.recurring[0].signature.fingerprint
    assert json.loads(json.dumps(exported)) == exported
    assert exported == {
        "schema_version": SCHEMA_VERSION,
        "owner": "octo-org",
        "host": "github.com",
        "window": {"start": "2026-09-09T12:00:00Z", "end": "2026-10-09T12:00:00Z"},
        "complete": True,
        "repositories": 1,
        "runs": 5,
        "logs_not_read": 0,
        "problems": [],
        "min_flaky_runs": 2,
        "jobs": [
            {
                "finding": 1,
                "status": "seen_once",
                "repository": "octo-org/app",
                "workflow": {"name": "CI", "path": ".github/workflows/ci.yml"},
                "job": "test",
                "step": "Run tests",
                "flaky_failures": 1,
                "affected_runs": 1,
                "total_runs": 5,
                "flake_rate": 0.2,
                "signals": {"rerun_passed": 1, "same_commit": 0},
                "first_seen": "2026-10-01T09:01:00Z",
                "last_seen": "2026-10-01T09:01:00Z",
                "passing_since": "2026-10-01T09:00:00Z",
                "examples": ["https://github.com/octo-org/app/actions/runs/1/job/11"],
                "signatures": [
                    {
                        "category": "timeout",
                        "message": "Test timed out after <duration>",
                        "fingerprint": timeout,
                        "occurrences": 1,
                    }
                ],
            }
        ],
        "recurring_errors": [
            {
                "finding": 2,
                "repository": "octo-org/app",
                "workflow": {"name": "CI", "path": ".github/workflows/ci.yml"},
                "job": "lint",
                "step": "Run ruff",
                "runs": 2,
                "branches": ["main"],
                "first_seen": "2026-10-01T12:01:00Z",
                "last_seen": "2026-10-01T13:01:00Z",
                "examples": [
                    "https://github.com/octo-org/app/actions/runs/5/job/51",
                    "https://github.com/octo-org/app/actions/runs/4/job/41",
                ],
                "signature": {
                    "category": "other",
                    "message": "E501 line too long",
                    "fingerprint": lint,
                },
            }
        ],
    }
