from flakipype.config.settings import Settings
from flakipype.store.audit import AuditEntry
from flakipype.store.database import ScanCache
from flakipype.unattended.limits import Usage, day_usage, run_actions, run_fix_settings, run_limits

from support.fake_fix import Clock
from support.fake_runs import FakeRuns


def entry(action: str, answer: str, outcome: str = "ok", origin: str = "run") -> AuditEntry:
    return AuditEntry("2026-10-09T06:00:00+00:00", "s", action, origin, "request", answer, outcome)


def test_the_day_counts_what_runs_started() -> None:
    entries = [
        entry("fix", "auto", "Opened draft pull request #12"),
        entry("fix", "auto", "failed: Branch flakipype/fix-ci-1 created; the commit failed"),
        entry("fix", "auto", "not pushed: An open flakipype pull request for #1 exists"),
        entry("fix", "not run in auto mode", "not pushed"),
        entry("fix", "confirmed", "Opened draft pull request #13", origin="command"),
        entry("verify_rerun", "covered by the push", "Started R2."),
        entry("verify_dispatch", "covered by the push", "Started R1."),
        entry("rerun_failed", "report only", "not run"),
    ]

    assert day_usage(entries, tokens=42) == Usage(pull_requests=1, actions=2, tokens=42)


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
