"""An unattended run over the investigation world: real services, fake GitHub, a settable clock."""

from dataclasses import dataclass, field

from flakipype.agent.budget import RunBudget
from flakipype.agent.investigator import Status
from flakipype.agent.pipeline import FindingResult
from flakipype.agent.tools import HeadlessGate, Mode
from flakipype.agent.verdict import ReviewState, Verdict
from flakipype.config.settings import FixSettings, GitHubSettings, Settings
from flakipype.fix.delivery import Delivery
from flakipype.fix.service import FixService
from flakipype.fix.verify import Verifier, VerifyGitHub
from flakipype.flaky.findings import Evidence, Finding
from flakipype.investigate.service import InvestigationService
from flakipype.investigate.workspace import ChatWorkspace
from flakipype.scan.service import ScanService
from flakipype.store.database import ScanCache
from flakipype.unattended.limits import RunLimits, Usage, run_actions, run_fix_settings
from flakipype.unattended.service import RunClock, RunService

from support.builders import START
from support.fake_actions import FakeActions
from support.fake_anthropic import verdict_input
from support.fake_fix import PROSE, Clock, FakeFixer, FakePullRequests, fixed
from support.fake_investigation import SCAN, world
from support.fake_runs import FakeRuns

DAY_LIMITS = Usage(pull_requests=3, actions=20, tokens=3_000_000)
NOW = START.replace(day=9)


def limits(
    *, pull_requests: int = 3, actions: int = 10, tokens: int = 1_000_000, minutes: int = 120
) -> RunLimits:
    return RunLimits(
        pull_requests=pull_requests, actions=actions, tokens=tokens, minutes=minutes,
        day_used=Usage(0, 0, 0), day_limits=DAY_LIMITS,
    )  # fmt: skip


@dataclass
class ClassifyingAgent:
    """The `flaky` findings (default: 1, the CI test) are flaky tests; all others real bugs."""

    flaky: frozenset[int] = frozenset({1})
    status: Status = Status.COMPLETED
    tokens: int = 1_000
    detail: str = ""
    # The review per finding number; answered with "accepted: ok" for the others.
    reviews: dict[int, tuple[ReviewState, str]] = field(default_factory=dict)
    calls: list[int] = field(default_factory=list)

    def __call__(
        self, finding: Finding, *, evidence: Evidence, run_budget: RunBudget
    ) -> FindingResult:
        del evidence
        self.calls.append(finding.number)
        run_budget.add(self.tokens)
        classification = "flaky_test" if finding.number in self.flaky else "real_bug"
        verdict = Verdict.model_validate(
            verdict_input("quote", "finding", classification=classification)
        )
        if self.status is not Status.COMPLETED:
            return FindingResult(
                self.status, None, ReviewState.NOTHING_SUBMITTED, "", self.detail, self.tokens, 2
            )
        state, review = self.reviews.get(finding.number, (ReviewState.ANSWERED, "accepted: ok"))
        return FindingResult(self.status, verdict, state, review, self.detail, self.tokens, 2)


@dataclass
class RunWorld:
    cache: ScanCache
    mode: Mode = Mode.AUTO
    limits: RunLimits = field(default_factory=limits)
    clock: Clock = field(default_factory=lambda: Clock(NOW))
    source: FakeActions = field(default_factory=world)
    agent: ClassifyingAgent = field(default_factory=ClassifyingAgent)
    runs: FakeRuns = field(default_factory=FakeRuns)
    github: FakePullRequests = field(default_factory=FakePullRequests)
    fixer: FakeFixer = field(default_factory=lambda: FakeFixer([fixed((PROSE,))]))
    fix_settings: FixSettings = field(default_factory=FixSettings)
    sleeps: list[float] = field(default_factory=list)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.clock.advance(seconds=seconds)

    def service(self) -> RunService:
        scan = ScanService(actions=self.source, cache=self.cache, now=self.clock)
        investigations = InvestigationService(
            scan=scan, cache=self.cache, investigate=self.agent, run_tokens=10**6, parallel=1
        )
        settings = Settings(github=GitHubSettings(owner=SCAN.owner), fix=self.fix_settings)
        actions = run_actions(
            runs=self.runs, files=self.runs, audit=self.cache.audit, settings=settings,
            limits=self.limits, now=self.clock,
        )  # fmt: skip
        verifier = Verifier(
            github=VerifyGitHub(runs=self.github, logs=self.source, comments=self.github),
            actions=actions, now=self.clock,
        )  # fmt: skip
        fixes = FixService(
            pulls=self.github, delivery=Delivery(pulls=self.github, verifier=verifier,
                                                 now=self.clock),
            verifier=verifier, actions=actions, audit=self.cache.audit, propose=self.fixer,
            settings=run_fix_settings(settings, self.limits), now=self.clock,
        )  # fmt: skip
        workspace = ChatWorkspace(investigations, SCAN, actions=actions, fixes=fixes)
        return RunService(
            workspace=workspace, gate=HeadlessGate(self.mode), cache=self.cache,
            limits=self.limits, clock=RunClock(now=self.clock, sleep=self.sleep),
        )  # fmt: skip
