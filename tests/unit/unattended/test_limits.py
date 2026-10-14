from flakipype.config.settings import Settings
from flakipype.store.audit import AuditEntry, AuditStatus
from flakipype.store.database import ScanCache
from flakipype.unattended.limits import Usage, day_usage, run_actions, run_fix_settings, run_limits

from support.fake_fix import Clock
from support.fake_runs import FakeRuns


def entry(
    action: str, status: AuditStatus, spent: int = 1, origin: str = "run", outcome: str = "ok"
) -> AuditEntry:
    return AuditEntry(
        "2026-10-09T06:00:00+00:00", "s", action, origin, "request", "auto", outcome, status, spent
    )


def test_the_day_counts_what_runs_started() -> None:
    entries = [
        entry("fix", AuditStatus.DONE),
        entry("fix", AuditStatus.FAILED, 0),
        entry("fix", AuditStatus.REFUSED, 0),
        entry("fix", AuditStatus.DECLINED, 0),
        entry("fix", AuditStatus.DONE, origin="command"),
        entry("verify_rerun", AuditStatus.DONE),
        entry("verify_dispatch", AuditStatus.DONE),
        entry("dispatch", AuditStatus.DONE, 3),
        entry("cancel", AuditStatus.DONE, 0),
        entry("rerun_failed", AuditStatus.DECLINED, 0),
    ]

    assert day_usage(entries, tokens=42) == Usage(pull_requests=1, actions=5, tokens=42)


def test_the_day_counts_the_status_not_the_wording_of_the_outcome() -> None:
    entries = [
        entry("fix", AuditStatus.DONE, outcome="failed to say it nicely, but opened #12"),
        entry("rerun_run", AuditStatus.FAILED, 0, outcome="Started R1."),
    ]

    assert day_usage(entries, tokens=0) == Usage(pull_requests=1, actions=0, tokens=0)


def test_a_run_gets_the_smaller_of_its_own_limit_and_what_the_day_has_left() -> None:
    settings = Settings.model_validate(
        {"run": {"max_prs_per_day": 4, "max_tokens_per_day": 1_500_000}}
    )

    fresh = run_limits(settings, Usage(0, 0, 0))
    late = run_limits(settings, Usage(pull_requests=3, actions=25, tokens=900_000))

    assert (fresh.pull_requests, fresh.actions, fresh.tokens, fresh.minutes) == (
        3, 10, 1_000_000, 120,
    )  # fmt: skip
    assert (late.pull_requests, late.actions, late.tokens) == (1, 0, 600_000)
    assert late.day_limits == Usage(4, 20, 1_500_000)
    assert late.day_used == Usage(3, 25, 900_000)


def test_a_runs_actions_and_fixes_keep_to_what_the_day_has_left(cache: ScanCache) -> None:
    settings = Settings.model_validate({"github": {"owner": "octo-org"}})
    limits = run_limits(settings, Usage(pull_requests=2, actions=18, tokens=0))
    runs = FakeRuns()

    actions = run_actions(
        runs=runs, files=runs, audit=cache.audit, settings=settings, limits=limits, now=Clock()
    )

    assert actions.max_per_session == 2
    assert run_fix_settings(settings, limits).max_prs_per_session == 1
