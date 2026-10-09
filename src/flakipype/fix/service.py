"""The chat's fixes: which findings, the fixer, one confirmation, delivery and verification."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol

from flakipype.actions.service import ActionService
from flakipype.actions.targets import check_owner
from flakipype.agent.fix_pipeline import FixRequest, FixResult
from flakipype.agent.tools import ActionRequest, Answer, PreparedAction, ToolError
from flakipype.agent.verdict import Classification, Verdict
from flakipype.agent.workcopy import unified_diff
from flakipype.config.settings import FixSettings
from flakipype.fix.checks import DiffLimits, change_errors, change_warnings
from flakipype.fix.state import OpenedPull, Proposal
from flakipype.fix.texts import (
    BRANCH_PREFIX,
    PullRequestFacts,
    branch_name,
    commit_body,
    failure_rate,
    finding_marker,
    pull_request_body,
)
from flakipype.fix.verify import Stage, Verification, Verifier
from flakipype.flaky.findings import Evidence, Finding
from flakipype.github.actions import ApiRateLimitError, GitHubApiError
from flakipype.github.pulls import CommitRequest, PullRequest, PullRequestText, RepositoryAccess
from flakipype.store.audit import AuditEntry, AuditLog

FIXABLE = frozenset(
    {Classification.FLAKY_TEST, Classification.FLAKY_INFRASTRUCTURE, Classification.CONFIGURATION}
)
_UNREVIEWED = ("not reviewed", "revised, second review unavailable")
_HTTP_FORBIDDEN = 403
_BRANCH_ATTEMPTS = 5
_PATHS_SHOWN = 3

type ProposeFix = Callable[[FixRequest], FixResult]


class FixPulls(Protocol):
    def access(self, repository: str) -> RepositoryAccess: ...

    def branch_head(self, repository: str, branch: str) -> str: ...

    def file_bytes(self, repository: str, path: str, commit: str) -> bytes | None: ...

    def open_pulls(self, repository: str) -> list[PullRequest]: ...

    def create_branch(self, repository: str, branch: str, commit: str) -> bool: ...

    def commit_files(self, repository: str, commit: CommitRequest) -> str: ...

    def open_draft(self, repository: str, pull: PullRequestText) -> PullRequest: ...


@dataclass(frozen=True)
class FixTarget:
    finding: Finding
    evidence: Evidence
    verdict: Verdict
    # How the verdict's review went, as the investigation reports it.
    review: str


class _DeliveryError(Exception):
    """A step after the first failed; the message says what exists on GitHub already."""


def fix_refusal(error: GitHubApiError) -> str:
    if error.status == _HTTP_FORBIDDEN:
        return (
            f"GitHub refused: {error}. A fix needs the repo and workflow scopes for a classic "
            "token or gh auth login, or 'Contents', 'Pull requests' and 'Workflows: read and "
            "write' for a fine-grained token."
        )
    return f"GitHub: {error}"


@contextmanager
def _from_github() -> Iterator[None]:
    try:
        yield
    except GitHubApiError as error:
        raise ToolError(fix_refusal(error)) from error


class FixService:
    def __init__(  # noqa: PLR0913 - collaborators of the fixes, all keyword-only
        self,
        *,
        pulls: FixPulls,
        verifier: Verifier,
        actions: ActionService,
        audit: AuditLog,
        propose: ProposeFix,
        settings: FixSettings,
        now: Callable[[], datetime],
    ) -> None:
        self._pulls = pulls
        self._verifier = verifier
        self._actions = actions
        self._audit = audit
        self._propose = propose
        self._settings = settings
        self._now = now
        self._proposals: dict[str, Proposal] = {}
        # Polled from a timer thread while the chat opens pull requests: change only by index.
        self.pulls: list[OpenedPull] = []
        self.opened = 0
        self.tokens = 0

    def discard(self, finding: Finding) -> None:
        """Forget a proposal that was not pushed, so the next /fix starts over."""
        self._proposals.pop(finding.identity, None)

    def prepare(self, target: FixTarget, instructions: str = "") -> PreparedAction:
        finding = target.finding
        check_owner(finding.key.repository, self._actions.owner)
        _check_fixable(target)
        if self.opened >= self._settings.max_prs_per_session:
            message = (
                f"Pull request budget used up: {self.opened} of "
                f"{self._settings.max_prs_per_session} in this session. /new starts a new session."
            )
            raise ToolError(message)
        with _from_github():
            access = self._pulls.access(finding.key.repository)
            if not access.can_push:
                message = (
                    f"You cannot push to {finding.key.repository}. flakipype delivers fixes only "
                    "as branches of the repository itself, not through forks."
                )
                raise ToolError(message)
            self._check_no_open_pull(finding)
            proposal = self._proposals.get(finding.identity)
            if proposal is None or instructions:
                proposal = self._new_proposal(target, access.default_branch, instructions)
        if not proposal.accepted:
            message = (
                f"No pull request for #{finding.number}: the review {proposal.review}. "
                "Ask for changes, or /fix N --fresh to start over. The diff:\n"
                + unified_diff(list(proposal.changes))
            )
            raise ToolError(message)
        return self._prepared(proposal)

    def poll(self) -> list[str]:
        """Moves every unfinished verification one step; a note for each one that finished."""
        notes: list[str] = []
        for index, pull in enumerate(self.pulls):
            if pull.verification.stage is Stage.DONE:
                continue
            try:
                verification = self._verifier.poll(pull.verification)
            except ApiRateLimitError:
                return notes
            except GitHubApiError:
                continue
            self.pulls[index] = replace(pull, verification=verification)
            if verification.stage is Stage.DONE:
                notes.append(f"Pull request #{verification.pull_number}: {verification.outcome}")
        return notes

    def state(self) -> dict[str, Any]:
        return {
            "opened": self.opened,
            "proposals": [proposal.to_dict() for proposal in self._proposals.values()],
            "pulls": [pull.to_dict() for pull in self.pulls],
        }

    def restore(self, state: dict[str, Any]) -> None:
        self.opened = int(state["opened"])
        proposals = [Proposal.from_dict(item) for item in state["proposals"]]
        self._proposals = {proposal.identity: proposal for proposal in proposals}
        self.pulls = [OpenedPull.from_dict(item) for item in state["pulls"]]

    def reset(self) -> None:
        self.opened = 0
        self._proposals = {}
        self.pulls = []

    def _check_no_open_pull(self, finding: Finding) -> None:
        marker = finding_marker(finding)
        for pull in self._pulls.open_pulls(finding.key.repository):
            if pull.branch.startswith(BRANCH_PREFIX) and marker in pull.body:
                message = f"An open flakipype pull request for #{finding.number} exists: {pull.url}"
                raise ToolError(message)

    def _new_proposal(self, target: FixTarget, base: str, instructions: str) -> Proposal:
        finding, key = target.finding, target.finding.key
        earlier = self._proposals.get(finding.identity) if instructions else None
        commit = earlier.commit if earlier else self._pulls.branch_head(key.repository, base)
        limits = DiffLimits(self._settings.max_files, self._settings.max_changed_lines)
        result = self._propose(
            FixRequest(
                finding=finding, evidence=target.evidence, verdict=target.verdict, commit=commit,
                default_branch=base, check=lambda changes: change_errors(changes, limits),
                earlier=earlier.changes if earlier else (), instructions=instructions,
            )
        )  # fmt: skip
        self.tokens += result.tokens
        if result.proposal is None:
            message = f"No fix for #{finding.number}: {result.detail or result.review}"
            raise ToolError(message)
        changes = list(result.changes)
        warnings = tuple(change_warnings(changes))
        rate = failure_rate(finding, target.evidence, base)
        facts = PullRequestFacts(
            finding, target.verdict, rate, warnings, self._settings.verify_runs
        )
        fingerprints = tuple(
            signature.fingerprint
            for job_id in finding.job_ids
            if (signature := target.evidence.signatures.get(job_id)) is not None
        )
        proposal = Proposal(
            finding=finding.number, identity=finding.identity, base=base, commit=commit,
            title=result.proposal.title, explanation=result.proposal.explanation,
            body=pull_request_body(facts, result.proposal.explanation), changes=result.changes,
            warnings=warnings, accepted=result.accepted, review=result.review,
            verification=Verification(
                pull_number=0, repository=key.repository, workflow_path=key.workflow_path,
                workflow_name=key.workflow_name, job=key.job,
                branch=branch_name(finding, changes), commit=commit,
                wanted=self._settings.verify_runs, started=self._now(), rate=rate,
                fingerprints=fingerprints,
            ),
        )  # fmt: skip
        self._proposals[finding.identity] = proposal
        return proposal

    def _prepared(self, proposal: Proposal) -> PreparedAction:
        changes = list(proposal.changes)
        added = sum(len(change.added) for change in changes)
        removed = sum(len(change.removed) for change in changes)
        paths = [change.path for change in changes]
        shown = ", ".join(paths[:_PATHS_SHOWN]) + (" …" if len(paths) > _PATHS_SHOWN else "")
        verification = proposal.verification
        actions = self._actions
        details = (
            f"{proposal.repository} · base {proposal.base} @ {proposal.commit[:7]}",
            f"new branch {verification.branch}",
            f"{len(changes)} files · +{added} −{removed} · {shown}",
            f"then reruns {verification.workflow_name} on the fix branch {verification.wanted} times",
            f"Pull requests this session: {self.opened + 1} of "
            f"{self._settings.max_prs_per_session} · Actions: {actions.used} of "
            f"{actions.max_per_session}",
            "Opens a draft pull request; merging stays with you.",
            *(["Warnings: none"] if not proposal.warnings else
              ["Warnings:", *(f"⚠ {warning}" for warning in proposal.warnings)]),
        )  # fmt: skip
        request = ActionRequest(
            "Push fix and open a draft pull request?",
            details,
            model_text=f"{proposal.title}\n\n{proposal.explanation}",
            diff=unified_diff(changes),
            needs_person="the diff has warnings" if proposal.warnings else "",
            confirm_label="Push",
            decline_label="Don't push",
        )
        origin = actions.origin

        def record(answer: Answer, outcome: str) -> None:
            self._audit.record(
                AuditEntry(
                    time=self._now().isoformat(), session=actions.session, action="fix",
                    origin=origin, request="\n".join([request.title, *details]),
                    answer=answer.value, outcome=outcome,
                )
            )  # fmt: skip

        def run(answer: Answer) -> str:
            try:
                outcome = self._deliver(proposal)
            except _DeliveryError as error:
                record(answer, f"failed: {error}")
                raise ToolError(str(error)) from error
            record(answer, outcome)
            return outcome

        return PreparedAction(request, run, lambda answer: record(answer, "not pushed"))

    def _deliver(self, proposal: Proposal) -> str:
        repository = proposal.repository
        try:
            branch = self._create_branch(proposal)
        except GitHubApiError as error:
            raise _DeliveryError(fix_refusal(error)) from error
        files = {change.path: change.after.encode("utf-8") for change in proposal.changes}
        headline, body = proposal.title, commit_body(proposal.explanation)
        try:
            sha = self._pulls.commit_files(
                repository, CommitRequest(branch, proposal.commit, headline, body, files)
            )
        except GitHubApiError as error:
            message = f"Branch {branch} created; the commit failed: {fix_refusal(error)} {_LEFT}"
            raise _DeliveryError(message) from error
        text = PullRequestText(proposal.title, proposal.body, head=branch, base=proposal.base)
        try:
            pull = self._pulls.open_draft(repository, text)
        except GitHubApiError as error:
            message = (
                f"Branch {branch} with commit {sha[:7]} created; opening the pull request failed: "
                f"{fix_refusal(error)} {_LEFT}"
            )
            raise _DeliveryError(message) from error
        self.opened += 1
        self._proposals.pop(proposal.identity, None)
        verification = self._start_verification(proposal, pull.number, branch, sha)
        self.pulls.append(
            OpenedPull(proposal.finding, proposal.title, pull.url, branch, verification)
        )
        status = (
            verification.outcome
            if verification.stage is Stage.DONE
            else f"Verification: {verification.wanted} runs of {verification.workflow_name} on "
            "the branch; the result follows here and on the pull request."
        )
        return f"Opened draft pull request #{pull.number}: {pull.url} (branch {branch}).\n{status}"

    def _create_branch(self, proposal: Proposal) -> str:
        name = proposal.verification.branch
        for attempt in range(1, _BRANCH_ATTEMPTS + 1):
            branch = name if attempt == 1 else f"{name}-{attempt}"
            if self._pulls.create_branch(proposal.repository, branch, proposal.commit):
                return branch
        message = f"branches {name} to {name}-{_BRANCH_ATTEMPTS} exist already"
        raise GitHubApiError(message)

    def _start_verification(
        self, proposal: Proposal, number: int, branch: str, commit: str
    ) -> Verification:
        seed = proposal.verification
        verification = replace(
            seed, pull_number=number, branch=branch, commit=commit, started=self._now()
        )
        changed = {change.path: change.after for change in proposal.changes}
        try:
            text = changed.get(seed.workflow_path)
            if text is None:
                raw = self._pulls.file_bytes(seed.repository, seed.workflow_path, commit)
                text = raw.decode("utf-8", errors="replace") if raw else ""
            return self._verifier.begin(verification, text)
        except GitHubApiError as error:
            return replace(
                verification, stage=Stage.DONE, outcome=f"Verification could not start: {error}"
            )


_LEFT = "The branch was left as it is; flakipype never deletes branches."


def reviewed(review: str) -> bool:
    return bool(review) and not review.startswith(_UNREVIEWED)


def _check_fixable(target: FixTarget) -> None:
    number, verdict = target.finding.number, target.verdict
    if verdict.classification not in FIXABLE:
        message = (
            f"#{number} is {verdict.classification.value.replace('_', ' ')}: flakipype fixes only "
            "flaky tests, flaky infrastructure and configuration problems."
        )
        raise ToolError(message)
    if not reviewed(target.review):
        message = (
            f"The verdict for #{number} was not reviewed ({target.review or 'no review'}); "
            f"investigate it again with /investigate {number} --fresh before fixing it."
        )
        raise ToolError(message)
