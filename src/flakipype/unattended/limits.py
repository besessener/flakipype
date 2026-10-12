"""What the runs of the last 24 hours used, what one run may still use, and its actions."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from flakipype.actions.api import RunApi, WorkflowFiles
from flakipype.actions.service import COVERED_BY_PUSH, ActionService, Origin
from flakipype.agent.tools import Answer
from flakipype.config.settings import FixSettings, Settings
from flakipype.store.audit import AuditEntry, AuditLog
from flakipype.store.database import ScanCache

DAY = timedelta(hours=24)
_ACTIONS = frozenset({"rerun_failed", "rerun_run", "dispatch", "verify_rerun", "verify_dispatch"})
_RAN = frozenset({Answer.AUTO.value, Answer.CONFIRMED.value, COVERED_BY_PUSH})
_NOT_DONE = ("failed", "not pushed", "not run")


@dataclass(frozen=True)
class Usage:
    pull_requests: int
    actions: int
    tokens: int


@dataclass(frozen=True)
class RunLimits:
    """Per run: the smaller of the run's own limit and what the day has left."""

    pull_requests: int
    actions: int
    tokens: int
    minutes: int
    # Used by earlier runs in the last 24 hours, and the daily limits.
    day_used: Usage
    day_limits: Usage


def day_usage(entries: list[AuditEntry], tokens: int) -> Usage:
    """Pull requests and actions that runs started, from the audit entries of the last day."""
    started = [
        entry
        for entry in entries
        if entry.origin == Origin.RUN
        and entry.answer in _RAN
        and not entry.outcome.startswith(_NOT_DONE)
    ]
    return Usage(
        pull_requests=sum(entry.action == "fix" for entry in started),
        actions=sum(entry.action in _ACTIONS for entry in started),
        tokens=tokens,
    )


def run_limits(settings: Settings, day_used: Usage) -> RunLimits:
    run = settings.run
    day_limits = Usage(run.max_prs_per_day, run.max_actions_per_day, run.max_tokens_per_day)
    return RunLimits(
        pull_requests=_left(settings.fix.max_prs_per_session, day_limits.pull_requests,
                            day_used.pull_requests),
        actions=_left(settings.actions.max_per_session, day_limits.actions, day_used.actions),
        tokens=_left(settings.agent.max_tokens_per_run, day_limits.tokens, day_used.tokens),
        minutes=run.max_minutes,
        day_used=day_used,
        day_limits=day_limits,
    )  # fmt: skip


def run_limits_for(settings: Settings, cache: ScanCache, now: datetime) -> RunLimits:
    """What one run may use after what the runs of the 24 hours before `now` used."""
    since = (now - DAY).isoformat()
    used = day_usage(cache.audit.since(since), cache.sessions.run_tokens_since(since))
    return run_limits(settings, used)


def run_actions(  # noqa: PLR0913 - collaborators of the run's actions, all keyword-only
    *,
    runs: RunApi,
    files: WorkflowFiles,
    audit: AuditLog,
    settings: Settings,
    limits: RunLimits,
    now: Callable[[], datetime],
) -> ActionService:
    """Within the run's action limit, audited as the run's so that later runs count them."""
    return ActionService(
        runs=runs, files=files, audit=audit,
        settings=settings.actions.model_copy(update={"max_per_session": limits.actions}),
        owner=settings.github.owner, now=now, origin=Origin.RUN,
    )  # fmt: skip


def run_fix_settings(settings: Settings, limits: RunLimits) -> FixSettings:
    return settings.fix.model_copy(update={"max_prs_per_session": limits.pull_requests})


def _left(per_run: int, per_day: int, used_today: int) -> int:
    return max(0, min(per_run, per_day - used_today))
