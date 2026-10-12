from flakipype.agent.investigator import Status
from flakipype.flaky.findings import FindingKind
from flakipype.investigate.service import (
    EventKind,
    InvestigationEvent,
    InvestigationRequest,
    InvestigationService,
    Selection,
)
from flakipype.scan.service import ScanService
from flakipype.store.database import ScanCache

from support.builders import START
from support.fake_investigation import SCAN, FakeAgent, world


def service(
    cache: ScanCache, agent: FakeAgent, *, run_tokens: int = 1_000_000, parallel: int = 2
) -> InvestigationService:
    scan = ScanService(actions=world(), cache=cache, now=lambda: START.replace(day=9))
    return InvestigationService(
        scan=scan, cache=cache, investigate=agent, run_tokens=run_tokens, parallel=parallel
    )


def test_default_selection_is_flaky_and_recurring(cache: ScanCache) -> None:
    agent = FakeAgent()
    events: list[InvestigationEvent] = []

    report = service(cache, agent).run(
        InvestigationRequest(SCAN, Selection()), on_event=events.append
    )

    findings = report.scan.findings
    assert [(f.number, f.kind) for f in findings] == [
        (1, FindingKind.FLAKY),
        (2, FindingKind.SEEN_ONCE),
        (3, FindingKind.RECURRING),
    ]
    assert sorted(agent.calls) == [1, 3]
    assert [r.finding.number for r in report.results] == [1, 3]
    assert report.complete
    assert report.tokens == 2_000
    assert sorted(e.kind for e in events) == [EventKind.FINISHED] * 2 + [EventKind.STARTED] * 2


def test_verdicts_are_reused_until_fresh_is_asked(cache: ScanCache) -> None:
    agent = FakeAgent()
    scanner = service(cache, agent)
    scanner.run(InvestigationRequest(SCAN, Selection(numbers=(1,))))

    cached = scanner.run(InvestigationRequest(SCAN, Selection(numbers=(1,))))
    fresh = scanner.run(InvestigationRequest(SCAN, Selection(numbers=(1,)), fresh=True))

    assert agent.calls == [1, 1]
    (result,) = cached.results
    assert result.from_cache
    assert result.verdict is not None
    assert result.review == "accepted: ok"
    assert not fresh.results[0].from_cache


def test_failed_investigations_are_not_cached(cache: ScanCache) -> None:
    agent = FakeAgent(status=Status.BUDGET)
    scanner = service(cache, agent)

    first = scanner.run(InvestigationRequest(SCAN, Selection(numbers=(2,))))
    scanner.run(InvestigationRequest(SCAN, Selection(numbers=(2,))))

    assert not first.complete
    assert agent.calls == [2, 2]


def test_one_crashing_investigation_keeps_the_others_and_their_tokens(cache: ScanCache) -> None:
    agent = FakeAgent(crash_on=3)
    scanner = service(cache, agent)

    report = scanner.run(InvestigationRequest(SCAN, Selection()))
    again = scanner.run(InvestigationRequest(SCAN, Selection(numbers=(1,))))

    first, crashed = report.results
    assert first.status is Status.COMPLETED
    assert crashed.status is Status.FAILED
    assert crashed.detail.startswith("Investigation failed: UnicodeDecodeError")
    assert report.tokens == 2_000
    assert again.results[0].from_cache


def test_verdicts_whose_review_failed_are_investigated_again(cache: ScanCache) -> None:
    unreviewed = FakeAgent(review="not reviewed: Error code: 400 - tool_choice not supported")
    scanner = service(cache, unreviewed)
    first = scanner.run(InvestigationRequest(SCAN, Selection(numbers=(1,))))
    finding = first.results[0].finding
    # As an older version stored it, before failed reviews were left out of the cache.
    cache.save_verdict(
        SCAN.host, finding.identity, last_seen=finding.last_seen.isoformat(),
        result=first.results[0].stored(),
    )  # fmt: skip

    second = scanner.run(InvestigationRequest(SCAN, Selection(numbers=(1,))))
    revised = FakeAgent(review="revised, second review unavailable: HTTP 500")
    service(cache, revised).run(InvestigationRequest(SCAN, Selection(numbers=(1,))))
    service(cache, revised).run(InvestigationRequest(SCAN, Selection(numbers=(1,))))

    assert unreviewed.calls == [1, 1]
    assert not second.results[0].from_cache
    assert revised.calls == [1, 1]


def test_a_lower_token_limit_for_one_call(cache: ScanCache) -> None:
    agent = FakeAgent(tokens=5_000)

    report = service(cache, agent, parallel=1).run(
        InvestigationRequest(SCAN, Selection(), max_tokens=1_000)
    )

    assert [result.status for result in report.results] == [Status.COMPLETED, Status.BUDGET]


def test_unknown_numbers_and_all_kinds(cache: ScanCache) -> None:
    agent = FakeAgent()

    report = service(cache, agent).run(InvestigationRequest(SCAN, Selection(numbers=(2, 9))))
    everything = service(cache, FakeAgent()).run(
        InvestigationRequest(SCAN, Selection(kinds=tuple(FindingKind)), fresh=True)
    )

    assert report.unknown_numbers == (9,)
    assert agent.calls == [2]
    assert len(everything.results) == 3


def test_run_budget_stops_further_investigations(cache: ScanCache) -> None:
    agent = FakeAgent(tokens=5_000)
    # One at a time makes the order deterministic.
    investigation = service(cache, agent, run_tokens=1_000, parallel=1)

    report = investigation.run(InvestigationRequest(SCAN, Selection(kinds=tuple(FindingKind))))

    statuses = [result.status for result in report.results]
    assert statuses.count(Status.BUDGET) == 2
    assert len(agent.calls) == 1
    assert "token limit is used up" in report.results[-1].detail


def test_a_lower_token_limit_for_one_call_stops_further_investigations(cache: ScanCache) -> None:
    agent = FakeAgent(tokens=5_000)
    investigation = service(cache, agent, run_tokens=1_000_000, parallel=1)

    report = investigation.run(InvestigationRequest(SCAN, Selection(), max_tokens=5_000))

    assert agent.calls == [1]
    assert report.tokens == 5_000
    assert [result.status for result in report.results] == [Status.COMPLETED, Status.BUDGET]
