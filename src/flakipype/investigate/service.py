import json
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from flakipype.agent.budget import RunBudget
from flakipype.agent.investigator import Status
from flakipype.agent.pipeline import FindingResult
from flakipype.agent.verdict import ReviewState, Verdict
from flakipype.flaky.findings import Evidence, Finding, FindingKind
from flakipype.scan.progress import ProgressListener, ignore_progress
from flakipype.scan.service import ScanReport, ScanRequest, ScanService, no_time_limit
from flakipype.store.database import ScanCache

DEFAULT_KINDS = (FindingKind.FLAKY, FindingKind.RECURRING)


class InvestigateFinding(Protocol):
    def __call__(
        self, finding: Finding, *, evidence: Evidence, run_budget: RunBudget
    ) -> FindingResult: ...


class EventKind(StrEnum):
    STARTED = "started"
    FINISHED = "finished"


@dataclass(frozen=True)
class InvestigationEvent:
    kind: EventKind
    finding: Finding
    done: int
    total: int


type EventListener = Callable[[InvestigationEvent], None]


def ignore_events(event: InvestigationEvent) -> None:
    del event


@dataclass(frozen=True)
class Selection:
    """Explicit finding numbers win; otherwise all findings of the given kinds."""

    numbers: tuple[int, ...] = ()
    kinds: tuple[FindingKind, ...] = DEFAULT_KINDS
    # Finding references, which name the same finding in any later scan.
    references: tuple[str, ...] = ()

    def pick(self, findings: Sequence[Finding]) -> list[Finding]:
        if self.numbers or self.references:
            numbers, references = set(self.numbers), set(self.references)
            return [
                finding
                for finding in findings
                if finding.number in numbers or finding.reference in references
            ]
        return [finding for finding in findings if finding.kind in self.kinds]


@dataclass(frozen=True)
class InvestigationResult:
    finding: Finding
    status: Status
    verdict: Verdict | None
    # For display only; decisions use review_state.
    review: str
    detail: str
    tokens: int
    rounds: int
    review_state: ReviewState = ReviewState.NOTHING_SUBMITTED
    from_cache: bool = False

    def stored(self) -> str:
        return json.dumps({
            "status": self.status.value,
            "verdict": self.verdict.model_dump(mode="json") if self.verdict else None,
            "review_state": self.review_state.value, "review": self.review,
            "detail": self.detail, "tokens": self.tokens, "rounds": self.rounds,
        })  # fmt: skip

    @classmethod
    def restored(cls, finding: Finding, stored: str) -> "InvestigationResult":
        data: dict[str, Any] = json.loads(stored)
        verdict = Verdict.model_validate(data["verdict"]) if data["verdict"] else None
        # Verdicts stored before the state was kept count as not reviewed.
        state = ReviewState(data.get("review_state", ReviewState.UNAVAILABLE))
        return cls(
            finding,
            Status(data["status"]),
            verdict,
            data["review"],
            data["detail"],
            0,
            0,
            review_state=state,
            from_cache=True,
        )


@dataclass(frozen=True)
class InvestigationReport:
    scan: ScanReport
    results: list[InvestigationResult]
    tokens: int
    unknown_numbers: tuple[int, ...]
    unknown_references: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return all(result.status is Status.COMPLETED for result in self.results)


@dataclass(frozen=True)
class InvestigationRequest:
    scan: ScanRequest
    selection: Selection
    # Ignore stored verdicts and investigate again.
    fresh: bool = False
    # A lower token limit than the configured one for this call, e.g. what a day has left.
    max_tokens: int | None = None
    # True once no new investigation may start; investigations already running finish.
    out_of_time: Callable[[], bool] | None = None


class InvestigationService:
    def __init__(  # noqa: PLR0913 - collaborators, all keyword-only
        self,
        *,
        scan: ScanService,
        cache: ScanCache,
        investigate: InvestigateFinding,
        run_tokens: int,
        parallel: int,
    ) -> None:
        self._scan = scan
        self._cache = cache
        self._investigate = investigate
        self._run_tokens = run_tokens
        self._parallel = parallel

    def run(
        self,
        request: InvestigationRequest,
        on_progress: ProgressListener = ignore_progress,
        on_event: EventListener = ignore_events,
    ) -> InvestigationReport:
        report = self.scan(request.scan, on_progress)
        return self.investigate(report, request, on_event)

    def scan(
        self,
        request: ScanRequest,
        on_progress: ProgressListener = ignore_progress,
        *,
        out_of_time: Callable[[], bool] = no_time_limit,
    ) -> ScanReport:
        return self._scan.scan(request, on_progress, out_of_time=out_of_time)

    def budget_for(self, request: InvestigationRequest) -> RunBudget:
        """The token budget investigate uses for the request; it counts even if a step crashes."""
        limit = self._run_tokens
        if request.max_tokens is not None:
            limit = min(limit, request.max_tokens)
        if request.out_of_time is None:
            return RunBudget(limit)
        return RunBudget(limit, out_of_time=request.out_of_time)

    def investigate(
        self,
        report: ScanReport,
        request: InvestigationRequest,
        on_event: EventListener = ignore_events,
        *,
        budget: RunBudget | None = None,
    ) -> InvestigationReport:
        """Investigate findings of an existing scan; `request.scan` names its host."""
        findings = report.findings
        chosen = request.selection.pick(findings)
        known = {finding.number for finding in findings}
        unknown = tuple(number for number in request.selection.numbers if number not in known)
        referenced = {finding.reference for finding in findings}
        unknown_references = tuple(
            reference for reference in request.selection.references if reference not in referenced
        )
        host = request.scan.host
        results = {} if request.fresh else self._cached(host, chosen)
        budget = budget or self.budget_for(request)
        todo = [finding for finding in chosen if finding.number not in results]
        results.update(
            self._investigate_all(todo, evidence=report.evidence, budget=budget, on_event=on_event)
        )
        for result in results.values():
            # A review that could not run (e.g. an HTTP error) is retried next time, not kept.
            if (
                not result.from_cache
                and result.status is Status.COMPLETED
                and result.review_state.reviewed
            ):
                finding = result.finding
                self._cache.save_verdict(
                    host,
                    finding.identity,
                    last_seen=finding.last_seen.isoformat(),
                    result=result.stored(),
                )
        ordered = [results[finding.number] for finding in chosen]
        return InvestigationReport(report, ordered, budget.used, unknown, unknown_references)

    def _cached(self, host: str, findings: Sequence[Finding]) -> dict[int, InvestigationResult]:
        cached = {}
        for finding in findings:
            stored = self._cache.cached_verdict(
                host, finding.identity, finding.last_seen.isoformat()
            )
            if stored is None:
                continue
            restored = InvestigationResult.restored(finding, stored)
            # Older versions kept verdicts whose review failed; they are investigated again.
            if restored.review_state.reviewed:
                cached[finding.number] = restored
        return cached

    def _investigate_all(
        self,
        findings: Sequence[Finding],
        *,
        evidence: Evidence,
        budget: RunBudget,
        on_event: EventListener,
    ) -> dict[int, InvestigationResult]:
        results: dict[int, InvestigationResult] = {}
        total = len(findings)
        with ThreadPoolExecutor(max_workers=self._parallel) as pool:
            futures = {
                pool.submit(
                    self._one, finding, evidence=evidence, budget=budget, events=(on_event, total)
                ): finding
                for finding in findings
            }
            for future in as_completed(futures):
                finding = futures[future]
                results[finding.number] = future.result()
                on_event(InvestigationEvent(EventKind.FINISHED, finding, len(results), total))
        return results

    def _one(
        self,
        finding: Finding,
        *,
        evidence: Evidence,
        budget: RunBudget,
        events: tuple[EventListener, int],
    ) -> InvestigationResult:
        on_event, total = events
        if budget.exhausted:
            return InvestigationResult(
                finding,
                Status.BUDGET,
                None,
                "",
                "Not started: the run's token limit is used up.",
                0,
                0,
            )
        if budget.out_of_time():
            detail = "Not started: the run's time limit is reached."
            return InvestigationResult(finding, Status.BUDGET, None, "", detail, 0, 0)
        on_event(InvestigationEvent(EventKind.STARTED, finding, 0, total))
        try:
            outcome = self._investigate(finding, evidence=evidence, run_budget=budget)
        # One finding's unexpected error must not discard the batch; its tokens are in budget.
        except Exception as error:  # noqa: BLE001 - reported as this finding's failed result
            detail = f"Investigation failed: {type(error).__name__}: {error}"
            return InvestigationResult(finding, Status.FAILED, None, "", detail, 0, 0)
        return InvestigationResult(
            finding, outcome.status, outcome.verdict, outcome.review, outcome.detail,
            outcome.tokens, outcome.rounds, review_state=outcome.review_state,
        )  # fmt: skip
