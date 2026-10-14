"""What a chat session keeps of its fixes: proposals not pushed yet and opened pull requests."""

from dataclasses import asdict, dataclass
from typing import Any

from flakipype.agent.workcopy import FileChange
from flakipype.fix.checks import executable_paths
from flakipype.fix.verify import Stage, Verification


@dataclass(frozen=True)
class Proposal:
    """A fix that was not pushed yet; /fix shows it again instead of running the fixer."""

    finding: int
    identity: str
    base: str
    commit: str
    title: str
    explanation: str
    body: str
    changes: tuple[FileChange, ...]
    warnings: tuple[str, ...]
    accepted: bool
    review: str
    # Filled in when the pull request exists.
    verification: Verification

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
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Proposal":
        fields: dict[str, Any] = {
            **data,
            "changes": tuple(FileChange(**change) for change in data["changes"]),
            "warnings": tuple(data["warnings"]),
            "verification": Verification.from_dict(data["verification"]),
        }
        return cls(**fields)


@dataclass(frozen=True)
class OpenedPull:
    finding: int
    title: str
    url: str
    branch: str
    verification: Verification

    @property
    def verified(self) -> bool:
        return self.verification.stage is Stage.DONE

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "verification": self.verification.to_dict()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpenedPull":
        fields: dict[str, Any] = {
            **data,
            "verification": Verification.from_dict(data["verification"]),
        }
        return cls(**fields)
