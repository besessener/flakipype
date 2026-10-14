"""One unattended run: fixed steps in code, every action through the gate, a summary at the end."""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from flakipype.agent.investigator import Status
from flakipype.agent.orchestrator import workspace_tools
from flakipype.agent.pipeline import reviewed
from flakipype.agent.tools import HeadlessGate, Mode, ToolDeclinedError, ToolError
from flakipype.agent.workcopy import unified_diff
from flakipype.fix.service import (
    FIXABLE,
    FixDeliveryError,
    FixNotMadeError,
    FixPushedError,
    FixUnavailableError,
)
from flakipype.fix.state import OpenedPull
from flakipype.flaky.findings import Finding
from flakipype.github.actions import GitHubApiError
from flakipype.investigate.chat_text import finding_title, sidebar_items
from flakipype.investigate.service import DEFAULT_KINDS, InvestigationResult
from flakipype.investigate.workspace import ChatWorkspace
from flakipype.scan.service import ScanReport
from flakipype.store.database import ScanCache
from flakipype.store.sessions import SessionKind
from flakipype.unattended.carry import carried_over
from flakipype.unattended.limits import RunLimits

POLL_SECONDS = 10.0
_NORMAL_ENDS = frozenset({Status.COMPLETED, Status.BUDGET})
# Ends the same input would likely repeat; limits and model errors are tried again.
_NO_VERDICT_REMEMBERED = frozenset({Status.NO_VERDICT, Status.LOOP})


class FixOutcomeKind(StrEnum):
    OPENED = "opened"
    KEPT = "kept"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class FixOutcome:
    finding: int
    title: str
    kind: FixOutcomeKind
    text: str
    # The diff of a fix that was made but not pushed.
    diff: str = ""


@dataclass(frozen=True)
class RunClock:
    now: Callable[[], datetime]
    sleep: Callable[[float], None]


@dataclass
class _Progress:
    fixes: list[FixOutcome] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stops: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunReport:
    mode: Mode
    started: datetime
    finished: datetime
    scan: ScanReport | None
    results: tuple[InvestigationResult, ...]
    fixes: tuple[FixOutcome, ...]
    pulls: tuple[OpenedPull, ...]
    tokens: int
    pull_requests: int
    actions: int
    limits: RunLimits
    # Limits that ended a step early, and errors that left the run incomplete.
    stops: tuple[str, ...]
    problems: tuple[str, ...]

    @property
    def complete(self) -> bool:
        """A reached limit is a normal end; a stopped scan, an error or a failed step is not."""
        investigated = all(result.status in _NORMAL_ENDS for result in self.results)
        scanned = self.scan is not None and self.scan.complete
        return scanned and investigated and not self.problems


class RunService:
    def __init__(  # noqa: PLR0913 - collaborators of a run, all keyword-only
        self,
        *,
        workspace: ChatWorkspace,
        gate: HeadlessGate,
        cache: ScanCache,
        limits: RunLimits,
        clock: RunClock,
    ) -> None:
        self._workspace = workspace
        self._gate = gate
        self._cache = cache
        self._limits = limits
        self._clock = clock
        self._fix_tool = next(tool for tool in workspace_tools(workspace) if tool.name == "fix")
        self._progress = _Progress()
        self._session_id = 0

    def show_activity(self, listener: Callable[[str], None]) -> None:
        """Scan and investigation progress as short texts; an empty text clears it."""
        self._workspace.on_activity = listener

    def run(self) -> RunReport:
        started = self._clock.now()
        deadline = started + timedelta(minutes=self._limits.minutes)
        title = f"run {started.astimezone():%Y-%m-%d %H:%M %Z} ({self._gate.mode})"
        sessions = self._cache.sessions
        self._session_id = sessions.create(
            title, now=started.isoformat(), data=json.dumps(self._document()), kind=SessionKind.RUN
        )
        self._carry_over(sessions.latest_run(before=self._session_id))
        # Saved before the scan, so a run that dies in it does not lose the adopted pull requests.
        self._save()
        try:
            try:
                self._scan_and_fix(deadline)
            except GitHubApiError as error:
                self._progress.problems.append(f"GitHub: {error}")
            if self._gate.mode is Mode.AUTO:
                self._poll_until(deadline)
        finally:
            # Also when a step crashes: its tokens count toward the daily limit.
            self._save()
        return self._report(started)

    def _carry_over(self, document: str | None) -> None:
        """Pull requests of the last run still being verified; only auto mode polls them."""
        if document is None:
            return
        pulls, runs = carried_over(json.loads(document))
        self._workspace.actions.adopt(runs)
        self._workspace.fixes.adopt(pulls)

    def _scan_and_fix(self, deadline: datetime) -> None:
        workspace, stops = self._workspace, self._progress.stops
        report = workspace.scan_report()
        self._save()
        if not report.complete:
            # Investigations would only see GitHub refuse their tools, and keep those verdicts.
            stops.append("GitHub's rate limit; investigations and fixes continue in the next run")
            return
        if self._clock.now() >= deadline:
            stops.append(f"the time limit of {self._limits.minutes} minutes")
            return
        if self._limits.tokens <= 0:
            stops.append("the token limit: today's tokens are used up")
            return
        numbers = self._to_investigate(report)
        if numbers:
            workspace.investigate(
                numbers, fresh=False, max_tokens=self._limits.tokens,
                out_of_time=lambda: self._clock.now() >= deadline,
            )  # fmt: skip
            self._remember_no_verdicts(report.host)
            self._save()
        self._fix_all(report, deadline)

    def _to_investigate(self, report: ScanReport) -> tuple[int, ...]:
        """Flaky findings and recurring errors, except those that ended without a verdict."""
        numbers: list[int] = []
        for finding in report.findings:
            if finding.kind not in DEFAULT_KINDS:
                continue
            earlier = self._cache.no_verdict(
                report.host, finding.identity, finding.last_seen.isoformat()
            )
            if earlier is None:
                numbers.append(finding.number)
                continue
            self._progress.fixes.append(_outcome(
                finding, FixOutcomeKind.SKIPPED,
                f"not investigated again: an earlier run ended without a verdict ({earlier}), "
                "and it has not failed since",
            ))  # fmt: skip
        return tuple(numbers)

    def _remember_no_verdicts(self, host: str) -> None:
        """A finding the model could not judge costs every run again; runs wait for news."""
        for result in self._workspace.results.values():
            if result.verdict is None and result.status in _NO_VERDICT_REMEMBERED:
                finding = result.finding
                self._cache.save_no_verdict(
                    host, finding.identity, last_seen=finding.last_seen.isoformat(),
                    detail=f"{result.status.value}: {_first_line(result.detail)}",
                )  # fmt: skip

    def _fix_all(self, report: ScanReport, deadline: datetime) -> None:
        self._workspace.fixes.deadline = deadline
        stopped = ""
        for result in sorted(self._workspace.results.values(), key=lambda r: r.finding.number):
            if not stopped and not _not_fixable(result):
                stopped = self._stop_before_fix(deadline)
            self._progress.fixes.append(self._fix_or_say_why(result, report.host, stopped))
            self._save()
        if stopped:
            self._progress.stops.append(stopped)

    def _fix_or_say_why(self, result: InvestigationResult, host: str, stopped: str) -> FixOutcome:
        finding = result.finding
        reason = _not_fixable(result)
        if reason:
            return _outcome(finding, FixOutcomeKind.SKIPPED, reason)
        if stopped:
            return _outcome(finding, FixOutcomeKind.SKIPPED, f"not tried: {stopped}")
        earlier = self._cache.unpushed_fix(host, finding.identity, finding.last_seen.isoformat())
        if earlier is not None:
            return _outcome(
                finding, FixOutcomeKind.SKIPPED,
                f"not tried again: an earlier run did not push its fix ({earlier}), "
                "and it has not failed since",
            )  # fmt: skip
        return self._fix(finding, host)

    def _stop_before_fix(self, deadline: datetime) -> str:
        limits = self._limits
        if self._clock.now() >= deadline:
            return f"the time limit of {limits.minutes} minutes"
        if self._workspace.fixes.opened >= limits.pull_requests:
            return f"the pull request limit ({limits.pull_requests} for this run)"
        if self._workspace.tokens >= limits.tokens:
            return f"the token limit ({limits.tokens:,} for this run)"
        return ""

    def _fix(self, finding: Finding, host: str) -> FixOutcome:
        try:
            text = self._fix_tool.invoke({"finding": finding.number}, self._gate)
        except ToolDeclinedError:
            return self._kept(finding, host)
        except (FixUnavailableError, FixDeliveryError) as error:
            # The model or GitHub failed, not the fix; only a pushed commit is not tried again.
            reason = _first_line(str(error))
            if isinstance(error, FixPushedError):
                self._remember(finding, host, f"pushed, no pull request: {reason}")
            self._progress.problems.append(reason)
            return _outcome(finding, FixOutcomeKind.FAILED, reason)
        except FixNotMadeError as error:
            reason = _first_line(str(error))
            self._remember(finding, host, reason)
            return _outcome(finding, FixOutcomeKind.SKIPPED, reason)
        except ToolError as error:
            return _outcome(finding, FixOutcomeKind.SKIPPED, str(error))
        return _outcome(finding, FixOutcomeKind.OPENED, text.splitlines()[0])

    def _kept(self, finding: Finding, host: str) -> FixOutcome:
        # A declined push always leaves its proposal behind.
        proposal = self._workspace.fixes.kept(finding)
        diff = unified_diff(list(proposal.changes))
        if self._gate.mode is Mode.ASK:
            text = (
                f"would open a draft pull request: {proposal.title} "
                "(report only, kept for the chat)"
            )
            return _outcome(finding, FixOutcomeKind.KEPT, text, diff=diff)
        self._remember(finding, host, proposal.needs_person)
        text = f"not pushed: {proposal.needs_person} (kept for the chat)"
        return _outcome(finding, FixOutcomeKind.KEPT, text, diff=diff)

    def _remember(self, finding: Finding, host: str, reason: str) -> None:
        """Auto mode only: a dry run must not stop a later run from trying."""
        if self._gate.mode is not Mode.AUTO:
            return
        self._cache.save_unpushed_fix(
            host, finding.identity, last_seen=finding.last_seen.isoformat(), outcome=reason
        )

    def _poll_until(self, deadline: datetime) -> None:
        actions, fixes = self._workspace.actions, self._workspace.fixes
        while any(not run.done for run in actions.watched) or any(
            not pull.verified for pull in fixes.pulls
        ):
            if self._clock.now() >= deadline:
                self._progress.stops.append(
                    f"the time limit of {self._limits.minutes} minutes; "
                    "verifications continue in the next run"
                )
                return
            self._clock.sleep(POLL_SECONDS)
            self._progress.notes.extend([*actions.poll(), *fixes.poll()])
            self._save()

    def _save(self) -> None:
        self._cache.sessions.update(
            self._session_id, now=self._clock.now().isoformat(), data=json.dumps(self._document())
        )

    def _document(self) -> dict[str, Any]:
        workspace, progress = self._workspace, self._progress
        texts = [f"#{f.finding} {f.title}: {f.text}" for f in progress.fixes] + progress.notes
        return {
            "entries": [{"kind": "note", "text": text} for text in texts],
            "history": [],
            "scan": asdict(workspace.request),
            "findings": [
                asdict(item) for item in sidebar_items(workspace.finding_list(), workspace.results)
            ],
            "chat_tokens": 0,
            "actions": workspace.actions.state(),
            "fix": workspace.fixes.state(),
            "tokens": workspace.tokens,
            "mode": self._gate.mode.value,
        }

    def _report(self, started: datetime) -> RunReport:
        workspace, progress = self._workspace, self._progress
        return RunReport(
            mode=self._gate.mode, started=started, finished=self._clock.now(),
            scan=workspace.report,
            results=tuple(sorted(workspace.results.values(), key=lambda r: r.finding.number)),
            fixes=tuple(sorted(progress.fixes, key=lambda fix: fix.finding)),
            pulls=tuple(workspace.fixes.pulls),
            tokens=workspace.tokens, pull_requests=workspace.fixes.opened,
            actions=workspace.actions.used, limits=self._limits,
            stops=tuple(progress.stops), problems=tuple(progress.problems),
        )  # fmt: skip


def _not_fixable(result: InvestigationResult) -> str:
    """Why the run does not fix the finding; empty when it may."""
    verdict = result.verdict
    if verdict is None:
        detail = _first_line(result.detail)
        return f"no verdict ({result.status.value})" + (f": {detail}" if detail else "")
    if verdict.classification not in FIXABLE:
        label = verdict.classification.value.replace("_", " ")
        return f"not fixed: {label}, which flakipype does not fix"
    if not reviewed(result.review):
        return (
            f"not fixed: the verdict was not reviewed ({_first_line(result.review)}); "
            "the next run investigates it again"
        )
    return ""


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


def _outcome(finding: Finding, kind: FixOutcomeKind, text: str, *, diff: str = "") -> FixOutcome:
    return FixOutcome(finding.number, finding_title(finding), kind, text, diff)
