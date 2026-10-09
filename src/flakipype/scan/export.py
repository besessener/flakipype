"""The machine-readable scan result (`flakipype scan --json`). Documented in docs/reference."""

from datetime import datetime
from typing import Any

from flakipype.flaky.recurring import RecurringError
from flakipype.flaky.scoring import FlakyJob
from flakipype.flaky.signature import Category
from flakipype.flaky.verdict import Verdict
from flakipype.scan.service import ScanReport

SCHEMA_VERSION = 1


def _timestamp(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _flaky_job(flaky: FlakyJob, status: Verdict) -> dict[str, Any]:
    return {
        "status": status.value,
        "repository": flaky.key.repository,
        "workflow": {"name": flaky.key.workflow_name, "path": flaky.key.workflow_path},
        "job": flaky.key.job,
        "step": flaky.key.step,
        "flaky_failures": flaky.flaky_failures,
        "affected_runs": flaky.affected_runs,
        "total_runs": flaky.total_runs,
        "flake_rate": round(flaky.flake_rate, 4),
        "signals": {"rerun_passed": flaky.rerun_passed, "same_commit": flaky.same_commit},
        "first_seen": _timestamp(flaky.first_seen),
        "last_seen": _timestamp(flaky.last_seen),
        "passing_since": _timestamp(flaky.passing_since) if flaky.passing_since else None,
        "examples": list(flaky.examples),
        "signatures": [
            {
                **_signature(signature.category, signature.message, signature.fingerprint),
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
        "min_flaky_runs": report.ranking.min_runs,
        "jobs": [_flaky_job(job, Verdict.FLAKY) for job in report.ranking.flaky]
        + [_flaky_job(job, Verdict.SEEN_ONCE) for job in report.ranking.seen_once]
        + [_flaky_job(job, Verdict.FIXED) for job in report.ranking.fixed],
        "recurring_errors": [_recurring_error(error) for error in report.recurring],
    }


def _recurring_error(error: RecurringError) -> dict[str, Any]:
    return {
        "repository": error.key.repository,
        "workflow": {"name": error.key.workflow_name, "path": error.key.workflow_path},
        "job": error.key.job,
        "step": error.key.step,
        "runs": error.runs,
        "branches": list(error.branches),
        "first_seen": _timestamp(error.first_seen),
        "last_seen": _timestamp(error.last_seen),
        "examples": list(error.examples),
        "signature": _signature(
            error.signature.category, error.signature.message, error.signature.fingerprint
        ),
    }


def _signature(category: Category, message: str, fingerprint: str) -> dict[str, Any]:
    return {"category": category.value, "message": message, "fingerprint": fingerprint}
