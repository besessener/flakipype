"""The machine-readable scan result (`flakipype scan --json`). Documented in docs/reference."""

from datetime import datetime
from typing import Any

from flakipype.flaky.scoring import FlakyJob
from flakipype.scan.service import ScanReport

SCHEMA_VERSION = 1


def _timestamp(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _flaky_job(flaky: FlakyJob) -> dict[str, Any]:
    return {
        "repository": flaky.key.repository,
        "workflow": {"name": flaky.key.workflow_name, "path": flaky.key.workflow_path},
        "job": flaky.key.job,
        "step": flaky.key.step,
        "flaky_failures": flaky.flaky_failures,
        "affected_runs": flaky.affected_runs,
        "total_runs": flaky.total_runs,
        "flake_rate": round(flaky.flake_rate, 4),
        "signals": {"rerun_passed": flaky.rerun_passed, "same_commit": flaky.same_commit},
        "last_seen": _timestamp(flaky.last_seen),
        "examples": list(flaky.examples),
        "signatures": [
            {
                "category": signature.category.value,
                "message": signature.message,
                "fingerprint": signature.fingerprint,
                "occurrences": signature.occurrences,
            }
            for signature in flaky.signatures
        ],
    }


def report_as_json(report: ScanReport) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "owner": report.owner,
        "host": report.host,
        "window": {"start": _timestamp(report.window.start), "end": _timestamp(report.window.end)},
        "complete": report.complete,
        "repositories": report.repositories,
        "runs": report.runs,
        "logs_not_read": report.logs_not_read,
        "problems": list(report.problems),
        "flaky": [_flaky_job(flaky) for flaky in report.flaky],
    }
