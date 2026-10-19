"""The chat's fixes: which findings, the fixer, one confirmation, delivery and verification."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol

from flakipype.actions.service import ActionService
from flakipype.actions.targets import check_owner
from flakipype.agent.fix_pipeline import FixRequest, FixResult
from flakipype.agent.fixer import FixStatus
from flakipype.agent.tools import ActionRequest, Answer, PreparedAction, ToolError
from flakipype.agent.verdict import Classification, ReviewState, Verdict
from flakipype.agent.workcopy import unified_diff
from flakipype.config.settings import FixSettings
from flakipype.fix.checks import DiffLimits, change_errors, change_warnings
from flakipype.fix.confirm import Budgets, confirmation, opened_text, retried_text
from flakipype.fix.delivery import Delivery, DeliveryError, PushedWithoutPullError, fix_refusal
from flakipype.fix.retry import failed_verification, retry_hint, why_no_retry
from flakipype.fix.state import OpenedPull, Proposal
from flakipype.fix.texts import (
    BRANCH_PREFIX,
    PullRequestFacts,
    Rate,
    branch_name,
    failure_rate,
    pull_markers,
    pull_request_body,
)
from flakipype.fix.verify import Stage, Verification, Verifier
from flakipype.flaky.findings import Evidence, Finding
from flakipype.github.actions import ApiRateLimitError, GitHubApiError
from flakipype.github.pulls import PullRequest, RepositoryAccess
from flakipype.store.audit import AuditEntry, AuditLog, AuditStatus

FIXABLE = frozenset(
    {Classification.FLAKY_TEST, Classification.FLAKY_INFRASTRUCTURE, Classification.CONFIGURATION}
)

type ProposeFix = Callable[[FixRequest], FixResult]


class FixNotMadeError(ToolError):
    """The fixer found no fix, or the review did not accept it."""


class FixUnavailableError(FixNotMadeError):
    """The model failed, not the fix: the fixer or the review could not run."""


class FixDeliveryError(ToolError):
    """A delivery step failed after the push was allowed; the message says what exists."""


class FixPushedError(FixDeliveryError):
    """The commit was pushed but no pull request opened; it counts against the limits."""


class FixGitHubError(ToolError):
    """GitHub failed before the push, not the fix: the fix may work on the next try."""

    def __init__(self, error: GitHubApiError) -> None:
        super().__init__(fix_refusal(error))
        self.login_expired = error.is_authentication_problem


class FixPulls(Protocol):
    def access(self, repository: str) -> RepositoryAccess: ...

    def branch_head(self, repository: str, branch: str) -> str: ...

    def open_pulls(self, repository: str) -> list[PullRequest]: ...


@dataclass(frozen=True)
class FixTarget:
    finding: Finding
    evidence: Evidence
    verdict: Verdict
    review_state: ReviewState
    # How the verdict's review went, as the investigation reports it; for display only.
    review: str = ""


@dataclass(frozen=True)
class _Start:
    """Where a new proposal starts: the default branch, or the pull request it retries."""

    base: str
    instructions: str
    retry_of: OpenedPull | None


@contextmanager
def _from_github() -> Generator[None]:
    try:
        yield
    except GitHubApiError as error:
        raise FixGitHubError(error) from error


class FixService:
    def __init__(  # noqa: PLR0913 - collaborators of the fixes, all keyword-only
        self,
        *,
        pulls: FixPulls,
        delivery: Delivery,
        verifier: Verifier,
        actions: ActionService,
        audit: AuditLog,
        propose: ProposeFix,
        settings: FixSettings,
        now: Callable[[], datetime],
    ) -> None:
        self._pulls = pulls
        self._delivery = delivery
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
        # An unattended run's time limit; a fix gets at most the time left until then.
        self.deadline: datetime | None = None

    def kept(self, finding: Finding) -> Proposal:
        """The fix for the finding that was made but not pushed; KeyError if there is none."""
        return self._proposals[finding.identity]

    def discard(self, finding: Finding) -> None:
        """Forget a proposal that was not pushed, so the next /fix starts over."""
        self._proposals.pop(finding.identity, None)

    def prepare(self, target: FixTarget, instructions: str = "") -> PreparedAction:
        finding = target.finding
        check_owner(finding.key.repository, self._actions.owner)
        _check_fixable(target)
        if not self._may_retry(finding):
            self._check_pull_budget()
        with _from_github():
            access = self._pulls.access(finding.key.repository)
            if not access.can_push:
                message = (
                    f"You cannot push to {finding.key.repository}. flakipype delivers fixes only "
                    "as branches of the repository itself, not through forks."
                )
                raise ToolError(message)
            markers = pull_markers(finding)
            retry_of = self._retry_of(finding, markers)
            if retry_of is None:
                self._check_pull_budget()
            proposal = self._proposals.get(finding.identity)
            if proposal is None or instructions or proposal.retry_of != retry_of:
                start = _Start(access.default_branch, instructions, retry_of)
                proposal = self._new_proposal(target, start)
        if not proposal.accepted:
            message = (
                f"No pull request for #{finding.number}: the review {proposal.review}. "
                "Ask for changes, or /fix N --fresh to start over. The diff:"
            )
            # A review that could not run is the model's failure; the fix itself may be fine.
            error = (
                FixUnavailableError
                if proposal.review_state is ReviewState.UNAVAILABLE
                else FixNotMadeError
            )
            raise error(message, unified_diff(list(proposal.changes)))
        return self._prepared(proposal, markers)

    def adopt(self, pulls: list[OpenedPull]) -> None:
        """Continue verifying pull requests an earlier session opened; costs no budget."""
        self.pulls.extend(pulls)

    def poll(self) -> list[str]:
        """Moves every unfinished verification one step; a note for each one that finished."""
        notes: list[str] = []
        # /new and /resume replace the list while a poll waits on gh; never write into the new one.
        pulls = self.pulls
        for index, pull in enumerate(pulls):
            if pull.verification.stage is Stage.DONE:
                continue
            try:
                verification = self._verifier.poll(pull.verification)
            except ApiRateLimitError:
                return notes
            if self.pulls is not pulls:
                return []
            pulls[index] = replace(pull, verification=verification)
            if verification.stage is Stage.DONE:
                hint = retry_hint(pulls[index], self._settings.max_attempts)
                notes.append(
                    f"Pull request #{verification.pull_number}: {verification.outcome}{hint}"
                )
        return notes

    def retries_pending(self) -> list[OpenedPull]:
        """Pull requests whose fix did not hold and that may get one more."""
        return [pull for pull in self.pulls if pull.may_retry(self._settings.max_attempts)]

    def state(self) -> dict[str, Any]:
        return {
            "opened": self.opened,
            "proposals": [proposal.to_dict() for proposal in self._proposals.values()],
            "pulls": [pull.to_dict() for pull in self.pulls],
        }

    def restore(self, state: dict[str, Any]) -> None:
        self.restore_proposals(state)
        self.opened = int(state["opened"])
        self.pulls = [OpenedPull.from_dict(item) for item in state["pulls"]]

    def restore_proposals(self, state: dict[str, Any]) -> None:
        """Only the fixes not pushed yet; the budget and the pull requests start empty."""
        self.reset()
        proposals = [Proposal.from_dict(item) for item in state["proposals"]]
        self._proposals = {proposal.identity: proposal for proposal in proposals}

    def reset(self) -> None:
        self.opened = 0
        self._proposals = {}
        self.pulls = []

    def _seconds_left(self) -> float | None:
        if self.deadline is None:
            return None
        return max(0.0, (self.deadline - self._now()).total_seconds())

    def _may_retry(self, finding: Finding) -> bool:
        """Whether this session holds a pull request for the finding that may get one more fix."""
        max_attempts = self._settings.max_attempts
        return any(
            pull.identity == finding.identity and pull.may_retry(max_attempts)
            for pull in self.pulls
        )

    def _check_pull_budget(self) -> None:
        if self.opened >= self._settings.max_prs_per_session:
            message = (
                f"Pull request budget used up: {self.opened} of "
                f"{self._settings.max_prs_per_session} in this session. /new starts a new session."
            )
            raise ToolError(message)

    def _open_pull(self, repository: str, markers: frozenset[str]) -> PullRequest | None:
        for pull in self._pulls.open_pulls(repository):
            # Only a branch in the repository itself with the marker code writes first counts;
            # anyone can open a fork pull request with the same branch name and marker.
            own = pull.head_repository.lower() == repository.lower()
            first_line = next(iter(pull.body.splitlines()), "")
            if own and pull.branch.startswith(BRANCH_PREFIX) and first_line in markers:
                return pull
        return None

    def _retry_of(self, finding: Finding, markers: frozenset[str]) -> OpenedPull | None:
        """This session's open pull request for the finding if its fix may be retried."""
        repository = finding.key.repository
        open_pull = self._open_pull(repository, markers)
        if open_pull is None:
            return None
        message = f"An open flakipype pull request for #{finding.number} exists: {open_pull.url}"
        ours = next(
            (
                pull
                for pull in self.pulls
                if pull.verification.repository.lower() == repository.lower()
                and pull.verification.pull_number == open_pull.number
            ),
            None,
        )
        if ours is None:
            raise ToolError(message)
        reason = why_no_retry(ours, self._settings.max_attempts)
        if reason:
            message = f"{message}; {reason}."
            raise ToolError(message)
        return ours

    def _check_still_open(self, proposal: Proposal, markers: frozenset[str]) -> None:
        """Another flakipype (the chat, a run) may have opened or closed one meanwhile."""
        open_pull = self._open_pull(proposal.repository, markers)
        retry_of = proposal.retry_of
        if retry_of is None:
            if open_pull is not None:
                message = (
                    f"An open flakipype pull request for #{proposal.finding} exists: "
                    f"{open_pull.url}"
                )
                raise ToolError(message)
            return
        number = retry_of.verification.pull_number
        if open_pull is None or open_pull.number != number:
            message = f"Pull request #{number} is no longer open; nothing was pushed."
            raise ToolError(message)

    def _new_proposal(self, target: FixTarget, start: _Start) -> Proposal:
        finding = target.finding
        earlier = self._proposals.get(finding.identity) if start.instructions else None
        if earlier is not None and earlier.retry_of != start.retry_of:
            earlier = None
        retry_of = start.retry_of
        commit = earlier.commit if earlier else self._start_commit(finding, start)
        limits = DiffLimits(self._settings.max_files, self._settings.max_changed_lines)
        result = self._propose(
            FixRequest(
                finding=finding, evidence=target.evidence, verdict=target.verdict, commit=commit,
                default_branch=retry_of.branch if retry_of else start.base,
                check=lambda changes: change_errors(changes, limits),
                earlier=earlier.changes if earlier else (), instructions=start.instructions,
                max_seconds=self._seconds_left(),
                failed_verification=failed_verification(retry_of) if retry_of else None,
            )
        )  # fmt: skip
        self.tokens += result.tokens
        if result.proposal is None:
            message = f"No fix for #{finding.number}: {result.detail or result.review}"
            if result.status is FixStatus.MODEL_ERROR:
                raise FixUnavailableError(message)
            raise FixNotMadeError(message)
        changes = list(result.changes)
        warnings = tuple(change_warnings(changes))
        rate = failure_rate(finding, target.evidence, start.base)
        facts = PullRequestFacts(
            finding, target.verdict, rate, warnings, self._settings.verify_runs
        )
        proposal = Proposal(
            finding=finding.number, identity=finding.identity, base=start.base, commit=commit,
            title=result.proposal.title, explanation=result.proposal.explanation,
            body=pull_request_body(facts, result.proposal.explanation), changes=result.changes,
            warnings=warnings, accepted=result.accepted, review_state=result.review_state,
            review=result.review, retry_of=retry_of,
            verification=(
                retry_of.verification.restarted(commit, self._now()) if retry_of
                else self._verification(target, branch_name(finding, changes), commit, rate=rate)
            ),
        )  # fmt: skip
        self._proposals[finding.identity] = proposal
        return proposal

    def _start_commit(self, finding: Finding, start: _Start) -> str:
        """A retry edits on top of the pushed fix; a new fix on the default branch's head."""
        if start.retry_of is not None:
            return start.retry_of.verification.commit
        return self._pulls.branch_head(finding.key.repository, start.base)

    def _verification(
        self, target: FixTarget, branch: str, commit: str, *, rate: Rate
    ) -> Verification:
        finding, key = target.finding, target.finding.key
        fingerprints = tuple(
            signature.fingerprint
            for job_id in finding.job_ids
            if (signature := target.evidence.signatures.get(job_id)) is not None
        )
        return Verification(
            pull_number=0, repository=key.repository, workflow_path=key.workflow_path,
            workflow_name=key.workflow_name, job=key.job, branch=branch, commit=commit,
            wanted=self._settings.verify_runs, started=self._now(), rate=rate,
            fingerprints=fingerprints,
        )  # fmt: skip

    def _prepared(self, proposal: Proposal, markers: frozenset[str]) -> PreparedAction:
        retry_of = proposal.retry_of
        title, details = confirmation(proposal, self._budgets())
        request = ActionRequest(
            title,
            details,
            model_text=f"{proposal.title}\n\n{proposal.explanation}",
            diff=unified_diff(list(proposal.changes)),
            needs_person=proposal.needs_person,
            confirm_label="Push",
            decline_label="Don't push",
        )
        session, origin = self._actions.session, self._actions.origin

        def record(answer: Answer, outcome: str, *, status: AuditStatus) -> None:
            # A retry adds a commit to an open pull request; it opens none.
            spent = int(status is AuditStatus.DONE and retry_of is None)
            self._audit.record(
                AuditEntry(
                    time=self._now().isoformat(), session=session, action="fix", origin=origin,
                    request="\n".join([request.title, *details]), answer=answer.value,
                    outcome=outcome, status=status, spent=spent,
                )
            )  # fmt: skip

        def run(answer: Answer) -> str:
            try:
                with _from_github():
                    self._check_still_open(proposal, markers)
            except ToolError as error:
                record(answer, f"not pushed: {error}", status=AuditStatus.REFUSED)
                raise
            try:
                outcome = self._deliver(proposal)
            except PushedWithoutPullError as error:
                # Counted like an opened pull request, so no run pushes it again and again.
                self.opened += 1
                self._proposals.pop(proposal.identity, None)
                record(answer, f"pushed, no pull request: {error}", status=AuditStatus.DONE)
                raise FixPushedError(str(error)) from error
            except DeliveryError as error:
                record(answer, f"failed: {error}", status=AuditStatus.FAILED)
                raise FixDeliveryError(str(error)) from error
            record(answer, outcome, status=AuditStatus.DONE)
            return outcome

        return PreparedAction(
            request, run, lambda answer: record(answer, "not pushed", status=AuditStatus.DECLINED)
        )

    def _deliver(self, proposal: Proposal) -> str:
        if proposal.retry_of is not None:
            return self._deliver_retry(proposal)
        opened = self._delivery.deliver(proposal)
        self.opened += 1
        self._proposals.pop(proposal.identity, None)
        self.pulls.append(opened)
        return opened_text(opened)

    def _deliver_retry(self, proposal: Proposal) -> str:
        max_attempts = self._settings.max_attempts
        retried = self._delivery.deliver_retry(proposal, max_attempts)
        self._proposals.pop(proposal.identity, None)
        pull = retried.pull
        # Polled from a timer thread: change only by index. A finished verification is not polled.
        pulls = self.pulls
        index = next((i for i, item in enumerate(pulls) if item.same_pull(pull)), None)
        if index is None:
            pulls.append(pull)
        else:
            pulls[index] = pull
        return retried_text(pull, max_attempts, retried.problem)

    def _budgets(self) -> Budgets:
        settings, actions = self._settings, self._actions
        return Budgets(
            pulls_opened=self.opened, max_pulls=settings.max_prs_per_session,
            actions_used=actions.used, max_actions=actions.max_per_session,
            max_attempts=settings.max_attempts,
        )  # fmt: skip


def _check_fixable(target: FixTarget) -> None:
    number, verdict = target.finding.number, target.verdict
    if verdict.classification not in FIXABLE:
        message = (
            f"#{number} is {verdict.classification.value.replace('_', ' ')}: flakipype fixes only "
            "flaky tests, flaky infrastructure and configuration problems."
        )
        raise ToolError(message)
    if not target.review_state.reviewed:
        message = (
            f"The verdict for #{number} was not reviewed ({target.review or 'no review'}); "
            f"investigate it again with /investigate {number} --fresh before fixing it."
        )
        raise ToolError(message)
