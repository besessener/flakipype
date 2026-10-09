"""Fakes for fixes: a settable clock, GitHub for verification and pull requests, builders."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from flakipype.actions.service import ActionService
from flakipype.agent.fix_pipeline import FixRequest, FixResult
from flakipype.agent.fixer import FixProposal, FixStatus
from flakipype.agent.verdict import Verdict
from flakipype.agent.workcopy import FileChange
from flakipype.config.settings import ActionSettings, FixSettings
from flakipype.fix.delivery import Delivery
from flakipype.fix.service import FixService
from flakipype.fix.texts import Rate
from flakipype.fix.verify import Verification, Verifier, VerifyGitHub
from flakipype.github.pulls import CommitRequest, PullRequest, PullRequestText, RepositoryAccess
from flakipype.github.runs import CommitRun
from flakipype.store.database import ScanCache

from support.builders import START
from support.fake_actions import FakeActions
from support.fake_anthropic import verdict_input
from support.fake_runs import APP, E2E, FakeRuns

COMMIT = "3f2a9c1" + "0" * 33
FIX_COMMIT = "c0ffee1" + "0" * 33
BRANCH = "flakipype/fix-e2e-abc123"
TITLE = "Wait for the document rows"
EXPLANATION = "The test counts rows before the import finished."
CHANGE = FileChange(
    "tests/e2e/scan.spec.ts", "await page.waitForTimeout(500)\n", "await rows.waitFor()\n"
)


@dataclass
class Clock:
    now: datetime = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def verdict(classification: str = "flaky_test") -> Verdict:
    return Verdict.model_validate(
        verdict_input("timed out", "toolu_9", classification=classification)
    )


def verification(*, wanted: int = 3, fingerprints: tuple[str, ...] = ()) -> Verification:
    return Verification(
        pull_number=12, repository=APP, workflow_path=E2E, workflow_name="E2E", job="e2e",
        branch=BRANCH, commit=FIX_COMMIT, wanted=wanted, started=START,
        rate=Rate(4, 31, "main"), fingerprints=fingerprints,
    )  # fmt: skip


def action_service(
    cache: ScanCache, runs: FakeRuns, clock: Clock, settings: ActionSettings | None = None
) -> ActionService:
    return ActionService(
        runs=runs, files=runs, audit=cache.audit, settings=settings or ActionSettings(),
        owner="octo-org", now=clock,
    )  # fmt: skip


def fixed(
    changes: tuple[FileChange, ...] = (CHANGE,),
    *,
    accepted: bool = True,
    review: str = "accepted: ok",
) -> FixResult:
    return FixResult(
        status=FixStatus.PROPOSED, proposal=FixProposal(title=TITLE, explanation=EXPLANATION),
        changes=changes, accepted=accepted, review=review, detail="", tokens=1_000,
    )  # fmt: skip


def no_fix(detail: str) -> FixResult:
    return FixResult(FixStatus.NO_FIX, None, (), accepted=False, review="", detail=detail, tokens=5)


@dataclass
class FakeFixer:
    """Answers each fix request with the next scripted result; the last one repeats."""

    results: list[FixResult] = field(default_factory=lambda: [fixed()])
    requests: list[FixRequest] = field(default_factory=list)

    def __call__(self, request: FixRequest) -> FixResult:
        self.requests.append(request)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


@dataclass
class FakePullRequests:
    """Commit runs, comments and pull requests in memory; stored exceptions are raised."""

    runs_by_commit: dict[str, list[CommitRun]] = field(default_factory=dict)
    can_push: bool = True
    open: list[PullRequest] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)
    taken_branches: set[str] = field(default_factory=set)
    errors: dict[str, Exception] = field(default_factory=dict)
    comments: list[str] = field(default_factory=list)
    commits: list[CommitRequest] = field(default_factory=list)
    drafts: list[PullRequestText] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    def _call(self, call: str) -> None:
        self.calls.append(call)
        error = self.errors.get(call.split(maxsplit=1)[0])
        if error is not None:
            raise error

    def commit_runs(self, repository: str, workflow_path: str, commit: str) -> list[CommitRun]:
        self._call(f"commit_runs {repository} {workflow_path} {commit[:7]}")
        return self.runs_by_commit.get(commit, [])

    def comment(self, repository: str, number: int, body: str) -> None:
        self._call(f"comment {repository} {number}")
        self.comments.append(body)

    def access(self, repository: str) -> RepositoryAccess:
        self._call(f"access {repository}")
        return RepositoryAccess(can_push=self.can_push, default_branch="main")

    def branch_head(self, repository: str, branch: str) -> str:
        self._call(f"branch_head {repository} {branch}")
        return COMMIT

    def open_pulls(self, repository: str) -> list[PullRequest]:
        self._call(f"open_pulls {repository}")
        return self.open

    def file_bytes(self, repository: str, path: str, commit: str) -> bytes | None:
        self._call(f"file_bytes {repository} {path} {commit[:7]}")
        return self.files.get(path)

    def create_branch(self, repository: str, branch: str, commit: str) -> bool:
        self._call(f"create_branch {repository} {branch} {commit[:7]}")
        if branch in self.taken_branches:
            return False
        self.taken_branches.add(branch)
        return True

    def commit_files(self, repository: str, commit: CommitRequest) -> str:
        self._call(f"commit_files {repository} {commit.branch}")
        self.commits.append(commit)
        return FIX_COMMIT

    def open_draft(self, repository: str, pull: PullRequestText) -> PullRequest:
        self._call(f"open_draft {repository} {pull.head}")
        self.drafts.append(pull)
        number = 12 + len(self.drafts) - 1
        return PullRequest(
            number=number, url=f"https://github.com/{repository}/pull/{number}",
            branch=pull.head, body=pull.body,
        )  # fmt: skip


@dataclass
class FixWorld:
    """A FixService with its verifier, delivery and actions over in-memory GitHub fakes."""

    cache: ScanCache
    clock: Clock = field(default_factory=Clock)
    runs: FakeRuns = field(default_factory=FakeRuns)
    github: FakePullRequests = field(default_factory=FakePullRequests)
    logs: FakeActions = field(default_factory=FakeActions)
    fixer: FakeFixer = field(default_factory=FakeFixer)
    settings: ActionSettings = field(default_factory=ActionSettings)
    fix_settings: FixSettings = field(default_factory=FixSettings)

    def __post_init__(self) -> None:
        self.actions = action_service(self.cache, self.runs, self.clock, self.settings)
        self.verifier = Verifier(
            github=VerifyGitHub(runs=self.github, logs=self.logs, comments=self.github),
            actions=self.actions,
            now=self.clock,
        )
        self.delivery = Delivery(pulls=self.github, verifier=self.verifier, now=self.clock)
        self.fixes = FixService(
            pulls=self.github, delivery=self.delivery, verifier=self.verifier,
            actions=self.actions, audit=self.cache.audit, propose=self.fixer,
            settings=self.fix_settings, now=self.clock,
        )  # fmt: skip

    def step(self, current: Verification) -> Verification:
        self.actions.poll()
        return self.verifier.poll(current)
