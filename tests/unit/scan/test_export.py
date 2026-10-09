import json
from datetime import UTC, datetime

from flakipype.github.actions import Repository
from flakipype.scan.export import SCHEMA_VERSION, report_as_json
from flakipype.scan.service import ScanRequest, ScanService
from flakipype.store.database import ScanCache

from support.builders import job, run
from support.fake_actions import FakeActions

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def test_json_report_has_a_stable_documented_shape(cache: ScanCache) -> None:
    actions = FakeActions(
        repositories_found=[Repository("octo-org/app", "main")],
        runs_by_repository={"octo-org/app": [run(1, attempt=2), run(2), run(3)]},
        jobs_by_attempt={(1, 1): [job(11, run_id=1)]},
        logs={11: "2026-10-07T09:27:35Z ##[error]Test timed out after 5000ms\n"},
    )
    scanner = ScanService(actions=actions, cache=cache, now=lambda: NOW)
    report = scanner.scan(
        ScanRequest(owner="octo-org", host="github.com", window_days=30, max_log_downloads=5)
    )

    exported = report_as_json(report)

    assert json.loads(json.dumps(exported)) == exported
    assert exported == {
        "schema_version": SCHEMA_VERSION,
        "owner": "octo-org",
        "host": "github.com",
        "window": {"start": "2026-09-09T12:00:00Z", "end": "2026-10-09T12:00:00Z"},
        "complete": True,
        "repositories": 1,
        "runs": 3,
        "logs_not_read": 0,
        "problems": [],
        "flaky": [
            {
                "repository": "octo-org/app",
                "workflow": {"name": "CI", "path": ".github/workflows/ci.yml"},
                "job": "test",
                "step": "Run tests",
                "flaky_failures": 1,
                "affected_runs": 1,
                "total_runs": 3,
                "flake_rate": 0.3333,
                "signals": {"rerun_passed": 1, "same_commit": 0},
                "last_seen": "2026-10-01T09:01:00Z",
                "examples": ["https://github.com/octo-org/app/actions/runs/1/job/11"],
                "signatures": [
                    {
                        "category": "timeout",
                        "message": "Test timed out after <duration>",
                        "fingerprint": report.flaky[0].signatures[0].fingerprint,
                        "occurrences": 1,
                    }
                ],
            }
        ],
    }
