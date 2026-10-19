"""Delivery of a confirmed fix: branch, one signed commit, draft pull request, verification."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from flakipype.fix.state import OpenedPull, Proposal
from flakipype.fix.texts import RetryFacts, commit_body, retry_comment
from flakipype.fix.verify import Verification, Verifier
from flakipype.github.actions import ApiRateLimitError, GitHubApiError
from flakipype.github.pulls import CommitRequest, PullRequest, PullRequestText

_HTTP_FORBIDDEN = 403
_BRANCH_ATTEMPTS = 5
_LEFT = "The branch was left as it is; flakipype never deletes branches."


class DeliveryPulls(Protocol):
    def file_bytes(self, repository: str, path: str, commit: str) -> bytes | None: ...

    def create_branch(self, repository: str, branch: str, commit: str) -> bool: ...

    def commit_files(self, repository: str, commit: CommitRequest) -> str: ...

    def open_draft(self, repository: str, pull: PullRequestText) -> PullRequest: ...

    def comment(self, repository: str, number: int, body: str) -> None: ...


@dataclass(frozen=True)
class Retried:
    pull: OpenedPull
    # Why the comment about the new commit is missing on the pull request; empty if posted.
    problem: str


class DeliveryError(Exception):
    """A delivery step failed; the message says what exists on GitHub already."""


class PushedWithoutPullError(DeliveryError):
    """The fix's commit is on GitHub, but its pull request could not be opened."""


def fix_refusal(error: GitHubApiError) -> str:
    if isinstance(error, ApiRateLimitError):
        return error.next_step()
    if error.status == _HTTP_FORBIDDEN:
        return (
            f"GitHub refused: {error}. A fix needs the repo and workflow scopes for a classic "
            "token or gh auth login, or 'Contents', 'Pull requests' and 'Workflows: read and "
            "write' for a fine-grained token."
        )
    return f"GitHub: {error}"


class Delivery:
    def __init__(
        self, *, pulls: DeliveryPulls, verifier: Verifier, now: Callable[[], datetime]
    ) -> None:
        self._pulls = pulls
        self._verifier = verifier
        self._now = now

    def deliver(self, proposal: Proposal) -> OpenedPull:
        """Each step runs only if the one before succeeded; raises DeliveryError otherwise."""
        try:
            branch = self._create_branch(proposal)
        except GitHubApiError as error:
            raise DeliveryError(fix_refusal(error)) from error
        files = {change.path: change.after.encode("utf-8") for change in proposal.changes}
        commit = CommitRequest(
            branch, proposal.commit, proposal.title, commit_body(proposal.explanation), files
        )
        try:
            sha = self._pulls.commit_files(proposal.repository, commit)
        except GitHubApiError as error:
            message = f"Branch {branch} created; the commit failed: {fix_refusal(error)} {_LEFT}"
            raise DeliveryError(message) from error
        text = PullRequestText(proposal.title, proposal.body, head=branch, base=proposal.base)
        try:
            pull = self._pulls.open_draft(proposal.repository, text)
        except GitHubApiError as error:
            message = (
                f"Branch {branch} with commit {sha[:7]} created; opening the pull request failed: "
                f"{fix_refusal(error)} {_LEFT}"
            )
            raise PushedWithoutPullError(message) from error
        verification = self._start_verification(
            proposal, replace(proposal.verification, pull_number=pull.number, branch=branch,
                              commit=sha, started=self._now()),
        )  # fmt: skip
        return OpenedPull(
            proposal.finding, proposal.title, pull.url, branch, verification,
            identity=proposal.identity,
        )  # fmt: skip

    def deliver_retry(self, proposal: Proposal, max_attempts: int) -> Retried:
        """One more commit on the pull request's branch, only on top of flakipype's own commit."""
        pull = proposal.retry_of
        if pull is None:
            message = "the proposal is not a retry"
            raise DeliveryError(message)
        files = {change.path: change.after.encode("utf-8") for change in proposal.changes}
        commit = CommitRequest(
            pull.branch, proposal.commit, proposal.title, commit_body(proposal.explanation), files
        )
        try:
            sha = self._pulls.commit_files(proposal.repository, commit)
        except GitHubApiError as error:
            message = (
                f"Nothing was pushed to {pull.branch}: {fix_refusal(error)} flakipype adds a "
                f"commit only while the branch still ends at its own commit {proposal.commit[:7]}."
            )
            raise DeliveryError(message) from error
        attempt = pull.attempt + 1
        facts = RetryFacts(
            sha, attempt, max_attempts, pull.verification.workflow_name,
            proposal.verification.wanted,
        )  # fmt: skip
        problem = ""
        try:
            self._pulls.comment(
                proposal.repository, pull.verification.pull_number,
                retry_comment(facts, proposal.title, proposal.explanation),
            )  # fmt: skip
        except GitHubApiError as error:
            problem = f"(The comment could not be posted on the pull request: {error})"
        verification = self._start_verification(
            proposal, proposal.verification.restarted(sha, self._now())
        )
        opened = replace(pull, title=proposal.title, verification=verification, attempt=attempt)
        return Retried(opened, problem)

    def _create_branch(self, proposal: Proposal) -> str:
        name = proposal.verification.branch
        for attempt in range(1, _BRANCH_ATTEMPTS + 1):
            branch = name if attempt == 1 else f"{name}-{attempt}"
            if self._pulls.create_branch(proposal.repository, branch, proposal.commit):
                return branch
        message = f"branches {name} to {name}-{_BRANCH_ATTEMPTS} exist already"
        raise GitHubApiError(message)

    def _start_verification(self, proposal: Proposal, verification: Verification) -> Verification:
        changed = {change.path: change.after for change in proposal.changes}
        try:
            text = changed.get(verification.workflow_path)
            if text is None:
                raw = self._pulls.file_bytes(
                    verification.repository, verification.workflow_path, verification.commit
                )
                text = raw.decode("utf-8", errors="replace") if raw else ""
            return self._verifier.begin(verification, text)
        # The pull request is open: it must still be counted and audited, whatever went wrong.
        except Exception as error:  # noqa: BLE001 - becomes the verification's outcome
            return self._verifier.stop(verification, f"it could not start: {error}")
