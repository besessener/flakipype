"""Delivery of a confirmed fix: branch, one signed commit, draft pull request, verification."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Protocol

from flakipype.fix.state import OpenedPull, Proposal
from flakipype.fix.texts import commit_body
from flakipype.fix.verify import Stage, Verification, Verifier
from flakipype.github.actions import GitHubApiError
from flakipype.github.pulls import CommitRequest, PullRequest, PullRequestText

_HTTP_FORBIDDEN = 403
_BRANCH_ATTEMPTS = 5
_LEFT = "The branch was left as it is; flakipype never deletes branches."


class DeliveryPulls(Protocol):
    def file_bytes(self, repository: str, path: str, commit: str) -> bytes | None: ...

    def create_branch(self, repository: str, branch: str, commit: str) -> bool: ...

    def commit_files(self, repository: str, commit: CommitRequest) -> str: ...

    def open_draft(self, repository: str, pull: PullRequestText) -> PullRequest: ...


class DeliveryError(Exception):
    """A delivery step failed; the message says what exists on GitHub already."""


def fix_refusal(error: GitHubApiError) -> str:
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
            raise DeliveryError(message) from error
        verification = self._start_verification(
            proposal, replace(proposal.verification, pull_number=pull.number, branch=branch,
                              commit=sha, started=self._now()),
        )  # fmt: skip
        return OpenedPull(proposal.finding, proposal.title, pull.url, branch, verification)

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
        except GitHubApiError as error:
            return replace(
                verification, stage=Stage.DONE, outcome=f"Verification could not start: {error}"
            )
