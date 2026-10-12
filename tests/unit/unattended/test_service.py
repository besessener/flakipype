import json
from dataclasses import dataclass, field

import pytest

from flakipype.agent.budget import RunBudget
from flakipype.agent.fix_pipeline import FixRequest, FixResult
from flakipype.agent.fixer import FixStatus
from flakipype.agent.investigator import Status
from flakipype.agent.pipeline import FindingResult
from flakipype.agent.tools import Mode
from flakipype.agent.workcopy import FileChange
from flakipype.config.settings import FixSettings
from flakipype.flaky.findings import Evidence, Finding
from flakipype.github.actions import ApiRateLimitError, GitHubApiError
from flakipype.github.pulls import PullRequest
from flakipype.github.runs import CommitRun
from flakipype.store.database import ScanCache
from flakipype.store.sessions import SessionKind
from flakipype.unattended.limits import day_usage
from flakipype.unattended.service import FixOutcomeKind, RunReport

from support.fake_fix import CHANGE, FIX_COMMIT, Clock, FakeFixer, fixed
from support.fake_run import NOW, ClassifyingAgent, RunWorld, limits
from support.fake_runs import passed_job, state

CI = ".github/workflows/ci.yml"
WARNED = (CHANGE, FileChange(CI, "on: push\njobs: {}\n", "on: [push]\njobs: {}\n"))
SERVER_ERROR = GitHubApiError("Server Error (HTTP 500)", 500)
# Finding 3, the recurring lint error, is a real bug in this world: never fixed, always listed.
REAL_BUG = (3, FixOutcomeKind.SKIPPED)


def run_once(world: RunWorld) -> RunReport:
    return world.service().run()


def kinds(report: RunReport) -> list[tuple[int, FixOutcomeKind]]:
    return [(fix.finding, fix.kind) for fix in report.fixes]


def test_auto_mode_opens_a_draft_pull_request_for_a_fixable_verdict(cache: ScanCache) -> None:
    world = RunWorld(cache)

    report = run_once(world)

    assert [result.finding.number for result in report.results] == [1, 3]
    assert kinds(report) == [(1, FixOutcomeKind.OPENED), REAL_BUG]
    assert report.fixes[0].text.startswith("Opened draft pull request #12: https://github.com/")
    assert world.github.drafts[0].head.startswith("flakipype/fix-ci-")
    assert (report.pull_requests, report.tokens, report.complete) == (1, 3_000, True)
    assert report.pulls[0].verified
    assert world.sleeps == []
    entry = cache.audit.since("2026")[0]
    assert (entry.action, entry.origin, entry.answer) == ("fix", "run", "auto")


def test_the_run_is_kept_as_a_session_for_the_chat(cache: ScanCache) -> None:
    world = RunWorld(cache)

    run_once(world)

    (summary,) = cache.sessions.recent(5)
    assert (summary.title, summary.kind) == ("run 2026-10-09 08:00 (auto)", SessionKind.RUN)
    document = json.loads(cache.sessions.load(summary.session_id) or "{}")
    assert (document["mode"], document["tokens"], document["history"]) == ("auto", 3_000, [])
    assert document["entries"][0]["text"].startswith("#1 octo-org/app › CI › test: Opened draft")
    assert [item["verdict"] for item in document["findings"]][:1] == ["flaky test (high)"]
    assert document["fix"]["opened"] == 1


def test_ask_mode_only_reports_and_keeps_the_fix(cache: ScanCache) -> None:
    world = RunWorld(cache, mode=Mode.ASK)

    report = run_once(world)

    outcome = report.fixes[0]
    assert outcome.kind is FixOutcomeKind.KEPT
    assert outcome.text == (
        "would open a draft pull request: Wait for the document rows "
        "(report only, kept for the chat)"
    )
    assert "+await rows.waitFor()" in outcome.diff
    assert world.github.drafts == []
    assert cache.audit.since("2026")[0].answer == "report only"
    assert run_once(RunWorld(cache, mode=Mode.ASK)).fixes[0].kind is FixOutcomeKind.KEPT


def test_a_fix_with_warnings_is_kept_and_not_tried_again(cache: ScanCache) -> None:
    fixer = FakeFixer([fixed(WARNED)])
    world = RunWorld(cache, fixer=fixer)

    first = run_once(world)
    second = run_once(RunWorld(cache, fixer=fixer))

    assert first.fixes[0].kind is FixOutcomeKind.KEPT
    assert first.fixes[0].text == (
        f"not pushed: the diff has warnings: changes .github/: {CI} (kept for the chat)"
    )
    assert world.github.drafts == []
    assert second.fixes[0].kind is FixOutcomeKind.SKIPPED
    assert second.fixes[0].text.startswith("not tried again: an earlier run did not push its fix")
    assert len(fixer.requests) == 1
    assert first.complete


def test_a_rejected_fix_is_remembered(cache: ScanCache) -> None:
    fixer = FakeFixer([fixed(accepted=False, review="rejected: it only waits longer")])

    first = run_once(RunWorld(cache, fixer=fixer))
    second = run_once(RunWorld(cache, fixer=fixer))

    assert first.fixes[0].text == (
        "No pull request for #1: the review rejected: it only waits longer. "
        "Ask for changes, or /fix N --fresh to start over. The diff:"
    )
    assert second.fixes[0].kind is FixOutcomeKind.SKIPPED
    assert len(fixer.requests) == 1


@pytest.mark.parametrize(
    "result",
    [
        FixResult(FixStatus.MODEL_ERROR, None, (), accepted=False, review="",
                  detail="Error code: 529 - overloaded", tokens=5),
        fixed(accepted=False, review="not reviewed: Error code: 529 - overloaded"),
    ],
)  # fmt: skip
def test_a_model_error_during_the_fix_fails_the_run_and_is_tried_again(
    cache: ScanCache, result: FixResult
) -> None:
    fixer = FakeFixer([result])

    first = run_once(RunWorld(cache, fixer=fixer))
    run_once(RunWorld(cache, fixer=fixer))

    assert kinds(first) == [(1, FixOutcomeKind.FAILED), REAL_BUG]
    assert "529 - overloaded" in first.problems[0]
    assert not first.complete
    assert len(fixer.requests) == 2


def test_a_pushed_fix_without_pull_request_counts_and_is_not_pushed_again(
    cache: ScanCache,
) -> None:
    world = RunWorld(cache)
    world.github.errors["open_draft"] = GitHubApiError(
        "Draft pull requests are not supported in this repository (HTTP 422)", 422
    )

    first = run_once(world)
    second = run_once(RunWorld(cache, fixer=world.fixer))

    assert kinds(first) == [(1, FixOutcomeKind.FAILED), REAL_BUG]
    assert first.pull_requests == 1
    assert not first.complete
    assert len(world.fixer.requests) == 1
    assert second.fixes[0].text.startswith(
        "not tried again: an earlier run did not push its fix (pushed, no pull request: Branch "
    )
    assert day_usage(cache.audit.since(""), 0).pull_requests == 1


def test_a_dry_run_remembers_nothing(cache: ScanCache) -> None:
    fixer = FakeFixer([fixed(accepted=False, review="rejected: it only waits longer")])

    run_once(RunWorld(cache, mode=Mode.ASK, fixer=fixer))
    later = run_once(RunWorld(cache, fixer=fixer))

    assert later.fixes[0].text.startswith("No pull request for #1: the review rejected")
    assert len(fixer.requests) == 2


def test_a_failed_delivery_makes_the_run_incomplete(cache: ScanCache) -> None:
    world = RunWorld(cache)
    world.github.errors["commit_files"] = SERVER_ERROR

    report = run_once(world)

    assert kinds(report) == [(1, FixOutcomeKind.FAILED), REAL_BUG]
    assert report.problems[0].startswith("Branch flakipype/fix-ci-")
    assert not report.complete


def test_a_finding_that_cannot_be_pushed_is_skipped(cache: ScanCache) -> None:
    world = RunWorld(cache)
    world.github.can_push = False

    report = run_once(world)

    assert kinds(report) == [(1, FixOutcomeKind.SKIPPED), REAL_BUG]
    assert report.fixes[0].text.startswith("You cannot push to octo-org/app")
    assert report.complete


def test_a_github_error_ends_the_run_with_a_problem(cache: ScanCache) -> None:
    world = RunWorld(cache)
    world.source.repositories_error = GitHubApiError("Bad credentials (HTTP 401)", 401)

    report = run_once(world)

    assert report.problems == ("GitHub: Bad credentials (HTTP 401)",)
    assert report.scan is None
    assert not report.complete


def test_failed_investigations_make_the_run_incomplete(cache: ScanCache) -> None:
    report = run_once(RunWorld(cache, agent=ClassifyingAgent(status=Status.MODEL_ERROR)))

    assert [fix.text for fix in report.fixes] == ["no verdict (model_error)"] * 2
    assert not report.complete
    assert cache.no_verdict("github.com", report.results[0].finding.identity,
                            report.results[0].finding.last_seen.isoformat()) is None  # fmt: skip


def test_an_investigation_without_verdict_is_not_repeated_until_a_newer_failure(
    cache: ScanCache,
) -> None:
    agent = ClassifyingAgent(status=Status.NO_VERDICT, detail="Verdict rejected: cite a log")

    first = run_once(RunWorld(cache, agent=agent))
    second = run_once(RunWorld(cache, agent=agent))

    assert first.fixes[0].text == "no verdict (no_verdict): Verdict rejected: cite a log"
    assert agent.calls == [1, 3]
    assert second.results == ()
    assert second.fixes[0].text == (
        "not investigated again: an earlier run ended without a verdict "
        "(no_verdict: Verdict rejected: cite a log), and it has not failed since"
    )
    assert second.tokens == 0


def test_every_investigated_finding_says_why_it_was_not_fixed(cache: ScanCache) -> None:
    reviews = {1: "not reviewed: Error code: 400 - tool_choice is not supported"}

    report = run_once(RunWorld(cache, agent=ClassifyingAgent(reviews=reviews)))

    unreviewed = (
        "not fixed: the verdict was not reviewed (not reviewed: Error code: 400 - tool_choice "
        "is not supported); the next run investigates it again"
    )
    assert [fix.text for fix in report.fixes] == [
        unreviewed,
        "not fixed: real bug, which flakipype does not fix",
    ]


def test_no_investigation_without_tokens_left(cache: ScanCache) -> None:
    world = RunWorld(cache, limits=limits(tokens=0))

    report = run_once(world)

    assert report.stops == ("the token limit: today's tokens are used up",)
    assert (world.agent.calls, report.results) == ([], ())
    assert report.complete


def test_the_pull_request_limit_stops_further_fixes(cache: ScanCache) -> None:
    both = ClassifyingAgent(flaky=frozenset({1, 3}))

    report = run_once(RunWorld(cache, limits=limits(pull_requests=1), agent=both))

    assert kinds(report) == [(1, FixOutcomeKind.OPENED), REAL_BUG]
    assert report.stops == ("the pull request limit (1 for this run)",)


def test_the_token_limit_stops_fixes(cache: ScanCache) -> None:
    report = run_once(RunWorld(cache, limits=limits(tokens=1_500)))

    assert report.tokens == 2_000
    assert kinds(report) == [(1, FixOutcomeKind.SKIPPED), REAL_BUG]
    assert report.fixes[0].text == "not tried: the token limit (1,500 for this run)"
    assert report.stops == ("the token limit (1,500 for this run)",)


@dataclass
class SlowFixer(FakeFixer):
    """Each fix takes three hours on the run's clock."""

    clock: Clock = field(default_factory=Clock)

    def __call__(self, request: FixRequest) -> FixResult:
        self.clock.advance(hours=3)
        return super().__call__(request)


def test_the_time_limit_stops_before_the_scan_ends_and_between_fixes(cache: ScanCache) -> None:
    clock = Clock(NOW)
    both = ClassifyingAgent(flaky=frozenset({1, 3}))
    report = run_once(RunWorld(cache, clock=clock, agent=both, fixer=SlowFixer(clock=clock)))
    none_left = run_once(RunWorld(cache, limits=limits(minutes=0)))

    assert kinds(report) == [(1, FixOutcomeKind.OPENED), REAL_BUG]
    assert report.stops == ("the time limit of 120 minutes",)
    assert none_left.stops == ("the time limit of 0 minutes",)
    assert none_left.results == ()


@dataclass
class SlowAgent(ClassifyingAgent):
    """Each investigation takes two hours on the run's clock."""

    clock: Clock = field(default_factory=Clock)

    def __call__(
        self, finding: Finding, *, evidence: Evidence, run_budget: RunBudget
    ) -> FindingResult:
        self.clock.advance(hours=2)
        return super().__call__(finding, evidence=evidence, run_budget=run_budget)


def test_no_investigation_starts_after_the_time_limit(cache: ScanCache) -> None:
    clock = Clock(NOW)
    agent = SlowAgent(clock=clock)

    report = run_once(RunWorld(cache, clock=clock, agent=agent))

    assert agent.calls == [1]
    assert report.results[1].detail == "Not started: the run's time limit is reached."
    assert report.fixes[0].text == "not tried: the time limit of 120 minutes"
    assert report.stops == ("the time limit of 120 minutes",)


def test_a_fix_gets_at_most_the_time_the_run_has_left(cache: ScanCache) -> None:
    world = RunWorld(cache, limits=limits(minutes=30))

    run_once(world)

    assert [request.max_seconds for request in world.fixer.requests] == [1800.0]


def verifying_world(cache: ScanCache, mode: Mode = Mode.AUTO, minutes: int = 120) -> RunWorld:
    world = RunWorld(
        cache, mode=mode, limits=limits(minutes=minutes), fix_settings=FixSettings(verify_runs=1)
    )
    world.github.files[CI] = b"on: pull_request\njobs: {}\n"
    world.github.runs_by_commit[FIX_COMMIT] = [CommitRun(91, "pull_request")]
    world.runs.states[91] = [state(91, name="CI", status="in_progress", conclusion=None)]
    return world


def opened_meanwhile(first: RunWorld, later: RunWorld) -> None:
    """The first run's pull request is open on GitHub when the later run looks."""
    draft = first.github.drafts[0]
    marker = draft.body.splitlines()[0]
    later.github.open = [
        PullRequest(
            12, "https://github.com/octo-org/app/pull/12", draft.head, marker, "octo-org/app"
        )
    ]


def test_verifications_left_at_the_time_limit_continue_in_the_next_auto_run(
    cache: ScanCache,
) -> None:
    first_world = verifying_world(cache, minutes=10)
    first = run_once(first_world)
    second_world = verifying_world(cache, mode=Mode.ASK)
    opened_meanwhile(first_world, second_world)
    second = run_once(second_world)
    third_world = verifying_world(cache)
    opened_meanwhile(first_world, third_world)
    third_world.runs.states[91] = [state(91, name="CI", conclusion="success")]
    third_world.source.jobs_by_attempt[91, 1] = [passed_job(91, name="test")]
    third = run_once(third_world)

    assert first.stops == ("the time limit of 10 minutes; verifications continue in the next run",)
    assert not first.pulls[0].verified
    assert len(first_world.sleeps) == 60
    assert (second.pulls[0].verified, second_world.sleeps) == (False, [])
    assert third.pulls[0].verified
    assert third.pulls[0].verification.outcome.startswith("flakipype verification: CI passed 1")
    assert third.pull_requests == 0
    assert kinds(third) == [(1, FixOutcomeKind.SKIPPED), REAL_BUG]
    assert third.fixes[0].text.startswith("An open flakipype pull request for #1 exists")


def test_pull_requests_taken_over_survive_a_run_that_dies_in_its_scan(
    cache: ScanCache,
) -> None:
    first_world = verifying_world(cache, minutes=10)
    run_once(first_world)
    crashing = verifying_world(cache)
    crashing.source.repositories_error = TimeoutError("gh did not answer")

    with pytest.raises(TimeoutError):
        run_once(crashing)

    stored = cache.sessions.latest_run(before=10**6)
    assert stored is not None
    assert len(json.loads(stored)["fix"]["pulls"]) == 1


def test_the_tokens_of_a_crashed_step_are_stored(cache: ScanCache) -> None:
    world = RunWorld(cache)
    service = world.service()

    def crash_after_an_investigation(text: str) -> None:
        if text.startswith("Investigated"):
            raise RuntimeError("display failed")

    service.show_activity(crash_after_an_investigation)
    with pytest.raises(RuntimeError):
        service.run()

    assert world.agent.calls
    assert cache.sessions.run_tokens_since("") == 1_000 * len(world.agent.calls)


def test_a_scan_stopped_by_the_rate_limit_investigates_nothing(cache: ScanCache) -> None:
    world = RunWorld(cache)
    world.source.logs = dict.fromkeys(
        world.source.logs, ApiRateLimitError("API rate limit exceeded", 403)
    )

    report = run_once(world)

    assert (world.agent.calls, report.results, report.fixes) == ([], (), ())
    assert report.stops == (
        "GitHub's rate limit; investigations and fixes continue in the next run",
    )
    assert not report.complete


def test_activity_is_shown_while_it_runs(cache: ScanCache) -> None:
    service = RunWorld(cache).service()
    shown: list[str] = []

    service.show_activity(shown.append)
    service.run()

    assert any(text.startswith("Investigating #1") for text in shown)
