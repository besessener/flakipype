"""What a chat session keeps of its fixes: proposals not pushed yet and opened pull requests."""

from dataclasses import asdict, dataclass
from typing import Any

from flakipype.agent.verdict import ReviewState
from flakipype.agent.workcopy import FileChange
from flakipype.fix.checks import executable_paths
from flakipype.fix.verify import Stage, Verification


@dataclass(frozen=True)
class OpenedPull:
    finding: int
    title: str
    url: str
    branch: str
    verification: Verification
    # Which fix of the pull request this is: 1 for the first commit, 2 after one retry.
    attempt: int = 1
    # The finding's identity; empty for pull requests saved before retries existed.
    identity: str = ""

    @property
    def verified(self) -> bool:
        return self.verification.stage is Stage.DONE

    def may_retry(self, max_attempts: int) -> bool:
        """The verification showed the finding's error again, and attempts are left."""
        held_not = self.verified and bool(self.verification.same_error_jobs)
        return held_not and self.attempt < max_attempts

    def same_pull(self, other: "OpenedPull") -> bool:
        mine, theirs = self.verification, other.verification
        return (mine.repository.lower(), mine.pull_number) == (
            theirs.repository.lower(),
            theirs.pull_number,
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "verification": self.verification.to_dict()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpenedPull":
        fields: dict[str, Any] = {
            **data,
            "verification": Verification.from_dict(data["verification"]),
        }
        return cls(**fields)


@dataclass(frozen=True)
class Proposal:
    """A fix that was not pushed yet; /fix shows it again instead of running the fixer."""

    finding: int
    identity: str
    base: str
    # The commit the working copy started from: the default branch's, or the fix branch's head.
    commit: str
    title: str
    explanation: str
    body: str
    changes: tuple[FileChange, ...]
    warnings: tuple[str, ...]
    accepted: bool
    review_state: ReviewState
    # For display only; decisions use accepted and review_state.
    review: str
    # Filled in when the pull request exists.
    verification: Verification
    # The pull request whose fix did not hold; this proposal becomes one more commit on it.
    retry_of: OpenedPull | None = None

    @property
    def repository(self) -> str:
        return self.verification.repository

    @property
    def needs_person(self) -> str:
        """Why only a person may push it, even in auto mode; empty when auto may."""
        if self.warnings:
            return f"the diff has warnings: {'; '.join(self.warnings)}"
        code = executable_paths(list(self.changes))
        if code:
            return f"it changes files that can run as code: {', '.join(code)}"
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "changes": [asdict(change) for change in self.changes],
            "verification": self.verification.to_dict(),
            "retry_of": self.retry_of.to_dict() if self.retry_of else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Proposal":
        retry_of = data.get("retry_of")
        fields: dict[str, Any] = {
            **data,
            "changes": tuple(FileChange(**change) for change in data["changes"]),
            "warnings": tuple(data["warnings"]),
            # Saved before the state was kept: retried like a review that could not run.
            "review_state": ReviewState(data.get("review_state", ReviewState.UNAVAILABLE)),
            "verification": Verification.from_dict(data["verification"]),
            "retry_of": OpenedPull.from_dict(retry_of) if retry_of else None,
        }
        return cls(**fields)
