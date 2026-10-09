from datetime import timedelta

from flakipype.flaky.findings import FindingKind, number_findings
from flakipype.flaky.recurring import RecurringError
from flakipype.flaky.scoring import FlakyJob, FlakyKey, SignatureCount
from flakipype.flaky.signature import Category, ErrorSignature
from flakipype.flaky.verdict import FlakyRanking

from support.builders import START

KEY = FlakyKey("octo-org/app", ".github/workflows/ci.yml", "CI", "test", "Run tests")


def flaky_job(job: str, *, passing: bool = True) -> FlakyJob:
    return FlakyJob(
        key=FlakyKey(KEY.repository, KEY.workflow_path, KEY.workflow_name, job, KEY.step),
        flaky_failures=3,
        affected_runs=2,
        total_runs=10,
        rerun_passed=2,
        same_commit=1,
        first_seen=START,
        last_seen=START + timedelta(days=1),
        recurred=True,
        passing_since=START + timedelta(days=2) if passing else None,
        examples=(),
        job_ids=(21, 11),
        signatures=(SignatureCount(Category.TIMEOUT, "wait timed out", "a" * 12, 2),),
    )


def test_findings_are_numbered_in_report_order_with_facts() -> None:
    recurring = RecurringError(
        key=KEY,
        signature=ErrorSignature(Category.ASSERTION, "expected 2", "b" * 12, "e"),
        runs=3,
        branches=("feature/x", "main"),
        first_seen=START,
        last_seen=START + timedelta(days=3),
        examples=(),
        job_ids=(31,),
    )
    ranking = FlakyRanking(2, [flaky_job("a")], [flaky_job("b", passing=False)], [flaky_job("c")])

    findings = number_findings(ranking, [recurring])

    assert [(f.number, f.kind, f.key.job) for f in findings] == [
        (1, FindingKind.FLAKY, "a"),
        (2, FindingKind.SEEN_ONCE, "b"),
        (3, FindingKind.FIXED, "c"),
        (4, FindingKind.RECURRING, "test"),
    ]
    assert "Runs with a proven flaky event: 2 of 10 finished runs" in findings[0].facts
    assert "Error signature (timeout, 2x): wait timed out" in findings[0].facts
    assert "Passing since — (not yet)" in findings[1].facts
    assert "Branches: feature/x, main" in findings[3].facts
    assert findings[0].job_ids == (21, 11)
    assert (
        findings[3].identity
        == "recurring|octo-org/app|.github/workflows/ci.yml|test|Run tests|" + "b" * 12
    )
    assert findings[0].identity.endswith("|a|Run tests|")
