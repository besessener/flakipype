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
from flakipype.agent.pipeline import reviewed
from flakipype.agent.tools import ActionRequest, Answer, PreparedAction, ToolError
from flakipype.agent.verdict import Classification, Verdict
from flakipype.agent.workcopy import unified_diff
from flakipype.config.settings import FixSettings
from flakipype.fix.checks import DiffLimits, change_errors, change_warnings
from flakipype.fix.delivery import Delivery, DeliveryError, PushedWithoutPullError, fix_refusal
from flakipype.fix.state import OpenedPull, Proposal
from flakipype.fix.texts import (
    BRANCH_PREFIX,
    PullRequestFacts,
    branch_name,
    failure_rate,
    identity_marker,
    pull_request_body,
)
from flakipype.fix.verify import Stage, Verification, Verifier
from flakipype.flaky.findings import Evidence, Finding
from flakipype.github.actions import ApiRateLimitError, GitHubApiError
from flakipype.github.pulls import PullRequest, RepositoryAccess
from flakipype.store.audit import AuditEntry, AuditLog

FIXABLE = frozenset(
    {Classification.FLAKY_TEST, Classification.FLAKY_INFRASTRUCTURE, Classification.CONFIGURATION}
)
_PATHS_SHOWN = 3
# Reviews that could not run, e.g. on an HTTP error; the fix itself may be fine.
_REVIEW_UNAVAILABLE = ("not reviewed", "revised, not reviewed again")

type ProposeFix = Callable[[FixRequest], FixResult]


class FixNotMadeError(ToolError):
    """The fixer found no fix, or the review did not accept it."""


class FixUnavailableError(FixNotMadeError):
    """The model failed, not the fix: the fixer or the review could not run."""


class FixDeliveryError(ToolError):
    """A delivery step failed after the push was allowed; the message says what exists."""


class FixPushedError(FixDeliveryError):
    """The commit was pushed but no pull request opened; it counts against the limits."""


class FixPulls(Protocol):
    def access(self, repository: str) -> RepositoryAccess: ...

    def branch_head(self, repository: str, branch: str) -> str: ...

    def open_pulls(self, repository: str) -> list[PullRequest]: ...


@dataclass(frozen=True)
class FixTarget:
    finding: Finding
    evidence: Evidence
    verdict: Verdict
    # How the verdict's review went, as the investigation reports it.
    review: str


@contextmanager
def _from_github() -> Generator[None]:
    try:
        yield
    except GitHubApiError as error:
        raise ToolError(fix_refusal(error)) from error


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
            self._check_no_open_pull(finding.key.repository, finding.identity, finding.number)
            proposal = self._proposals.get(finding.identity)
            if proposal is None or instructions:
                proposal = self._new_proposal(target, access.default_branch, instructions)
        if not proposal.accepted:
            message = (
                f"No pull request for #{finding.number}: the review {proposal.review}. "
                "Ask for changes, or /fix N --fresh to start over. The diff:"
            )
            error = (
                FixUnavailableError
                if proposal.review.startswith(_REVIEW_UNAVAILABLE)
                else FixNotMadeError
            )
            raise error(message, unified_diff(list(proposal.changes)))
        return self._prepared(proposal)

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
            except GitHubApiError:
                continue
            if self.pulls is not pulls:
                return []
            pulls[index] = replace(pull, verification=verification)
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

    def _check_no_open_pull(self, repository: str, identity: str, number: int) -> None:
        marker = identity_marker(identity)
        for pull in self._pulls.open_pulls(repository):
            # Only a branch in the repository itself with the marker code writes first counts;
            # anyone can open a fork pull request with the same branch name and marker.
            own = pull.head_repository.lower() == repository.lower()
            first_line = pull.body.splitlines()[:1]
            if own and pull.branch.startswith(BRANCH_PREFIX) and first_line == [marker]:
                message = f"An open flakipype pull request for #{number} exists: {pull.url}"
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
                max_seconds=self._seconds_left(),
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
        details = self._details(proposal)
        request = ActionRequest(
            "Push fix and open a draft pull request?",
            details,
            model_text=f"{proposal.title}\n\n{proposal.explanation}",
            diff=unified_diff(list(proposal.changes)),
            needs_person="the diff has warnings" if proposal.warnings else "",
            confirm_label="Push",
            decline_label="Don't push",
        )
        session, origin = self._actions.session, self._actions.origin

        def record(answer: Answer, outcome: str) -> None:
            self._audit.record(
                AuditEntry(
                    time=self._now().isoformat(), session=session, action="fix", origin=origin,
                    request="\n".join([request.title, *details]), answer=answer.value,
                    outcome=outcome,
                )
            )  # fmt: skip

        def run(answer: Answer) -> str:
            # Another flakipype (the chat, a run) may have opened one since the fixer started.
            try:
                with _from_github():
                    self._check_no_open_pull(
                        proposal.repository, proposal.identity, proposal.finding
                    )
            except ToolError as error:
                record(answer, f"not pushed: {error}")
                raise
            try:
                outcome = self._deliver(proposal)
            except PushedWithoutPullError as error:
                # Counted like an opened pull request, so no run pushes it again and again.
                self.opened += 1
                self._proposals.pop(proposal.identity, None)
                record(answer, f"pushed, no pull request: {error}")
                raise FixPushedError(str(error)) from error
            except DeliveryError as error:
                record(answer, f"failed: {error}")
                raise FixDeliveryError(str(error)) from error
            record(answer, outcome)
            return outcome

        return PreparedAction(request, run, lambda answer: record(answer, "not pushed"))

    def _details(self, proposal: Proposal) -> tuple[str, ...]:
        changes = proposal.changes
        added = sum(len(change.added) for change in changes)
        removed = sum(len(change.removed) for change in changes)
        paths = [change.path for change in changes]
        shown = ", ".join(paths[:_PATHS_SHOWN]) + (" …" if len(paths) > _PATHS_SHOWN else "")
        verification, actions = proposal.verification, self._actions
        warnings = (
            ["Warnings:", *(f"⚠ {item}" for item in proposal.warnings)]
            if proposal.warnings
            else ["Warnings: none"]
        )
        return (
            f"{proposal.repository} · base {proposal.base} @ {proposal.commit[:7]}",
            f"new branch {verification.branch}",
            f"{len(changes)} files · +{added} −{removed} · {shown}",
            (
                f"then reruns {verification.workflow_name} on the fix branch "
                f"{verification.wanted} times"
            ),
            (
                f"Pull requests this session: {self.opened + 1} of "
                f"{self._settings.max_prs_per_session} · Actions: {actions.used} of "
                f"{actions.max_per_session}"
            ),
            "Opens a draft pull request; merging stays with you.",
            *warnings,
        )

    def _deliver(self, proposal: Proposal) -> str:
        opened = self._delivery.deliver(proposal)
        self.opened += 1
        self._proposals.pop(proposal.identity, None)
        self.pulls.append(opened)
        verification = opened.verification
        status = (
            verification.outcome
            if verification.stage is Stage.DONE
            else (
                f"Verification: {verification.wanted} runs of {verification.workflow_name} on "
                "the branch; the result follows here and on the pull request."
            )
        )
        return (
            f"Opened draft pull request #{verification.pull_number}: {opened.url} "
            f"(branch {opened.branch}).\n{status}"
        )


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
