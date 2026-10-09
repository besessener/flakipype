"""The chat's workspace: one scan at a time and the verdicts investigated on it."""

from collections.abc import Callable
from dataclasses import replace

from flakipype.actions.service import ActionService
from flakipype.agent.tools import PreparedAction, ToolError
from flakipype.fix.service import FixService, FixTarget
from flakipype.flaky.findings import Finding
from flakipype.investigate.chat_text import findings_text, result_text, scan_summary
from flakipype.investigate.service import (
    EventKind,
    InvestigationEvent,
    InvestigationRequest,
    InvestigationResult,
    InvestigationService,
    Selection,
)
from flakipype.scan.progress import Progress
from flakipype.scan.service import ScanReport, ScanRequest

type ActivityListener = Callable[[str], None]


def ignore_activity(activity: str) -> None:
    del activity


class ChatWorkspace:
    """Implements the chat agent's Workspace; scans on demand with the last scan's options."""

    def __init__(
        self,
        service: InvestigationService,
        request: ScanRequest,
        *,
        actions: ActionService,
        fixes: FixService,
    ) -> None:
        self._service = service
        self.request = request
        self.actions = actions
        self.fixes = fixes
        self.report: ScanReport | None = None
        self.results: dict[int, InvestigationResult] = {}
        self.tokens = 0
        self.on_activity: ActivityListener = ignore_activity

    def scan(self, days: int | None, repositories: tuple[str, ...]) -> str:
        self.request = replace(
            self.request,
            window_days=days or self.request.window_days,
            repositories=repositories or self.request.repositories,
        )
        report = self._run_scan()
        return scan_summary(report) + "\n\n" + findings_text(report.findings)

    def findings(self) -> str:
        return findings_text(self._report().findings)

    def finding_list(self) -> list[Finding]:
        return self.report.findings if self.report else []

    def investigate(self, numbers: tuple[int, ...], *, fresh: bool) -> str:
        report = self._report()
        request = InvestigationRequest(self.request, Selection(numbers=numbers), fresh=fresh)
        outcome = self._service.investigate(report, request, self._investigation_progress)
        self.on_activity("")
        self.tokens += outcome.tokens
        self.results.update({result.finding.number: result for result in outcome.results})
        texts = [result_text(result) for result in outcome.results]
        texts.extend(f"#{number}: no such finding." for number in outcome.unknown_numbers)
        return "\n\n".join(texts)

    def verdict(self, number: int) -> str:
        if number in self.results:
            return result_text(self.results[number])
        return self.investigate((number,), fresh=False)

    def rerun_failed(self, finding: int, run_id: int | None) -> PreparedAction:
        report = self._report()
        return self.actions.rerun_failed(_finding(report, finding), report.evidence, run_id=run_id)

    def rerun_run(self, finding: int, run_id: int | None) -> PreparedAction:
        report = self._report()
        return self.actions.rerun_run(_finding(report, finding), report.evidence, run_id=run_id)

    def dispatch(self, finding: int, ref: str | None, repeats: int) -> PreparedAction:
        return self.actions.dispatch(_finding(self._report(), finding), ref, repeats)

    def cancel(self, run: int) -> PreparedAction:
        return self.actions.cancel(run)

    def watched_runs(self) -> str:
        return self.actions.watched_runs()

    def fix(self, finding: int, instructions: str) -> PreparedAction:
        """The fix for a finding with a reviewed verdict; investigates first if there is none."""
        report = self._report()
        target = _finding(report, finding)
        if finding not in self.results:
            self.investigate((finding,), fresh=False)
        result = self.results.get(finding)
        if result is None or result.verdict is None:
            reason = result.detail if result and result.detail else "the investigation ended"
            message = f"#{finding} has no verdict ({reason}); a fix needs one."
            raise ToolError(message)
        before = self.fixes.tokens
        self.on_activity(f"Fixing #{finding} {target.key.job}")
        try:
            return self.fixes.prepare(
                FixTarget(target, report.evidence, result.verdict, result.review), instructions
            )
        finally:
            self.tokens += self.fixes.tokens - before
            self.on_activity("")

    def discard_fix(self, finding: int) -> None:
        for item in self._report().findings:
            if item.number == finding:
                self.fixes.discard(item)

    def _report(self) -> ScanReport:
        return self.report or self._run_scan()

    def _run_scan(self) -> ScanReport:
        report = self._service.scan(self.request, self._scan_progress)
        self.report = report
        self.results = {}
        self.on_activity("")
        return report

    def _scan_progress(self, event: Progress) -> None:
        detail = f" · {event.detail}" if event.detail else ""
        self.on_activity(f"{event.stage.value} {event.done}/{event.total}{detail}")

    def _investigation_progress(self, event: InvestigationEvent) -> None:
        if event.kind is EventKind.STARTED:
            self.on_activity(f"Investigating #{event.finding.number} {event.finding.key.job}")
        else:
            self.on_activity(f"Investigated {event.done}/{event.total}")


def _finding(report: ScanReport, number: int) -> Finding:
    for finding in report.findings:
        if finding.number == number:
            return finding
    message = f"#{number}: no such finding in the current scan."
    raise ToolError(message)
