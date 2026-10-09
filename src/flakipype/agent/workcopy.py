"""The fixer's working copy: edits kept in memory over one pinned commit, never on disk."""

import difflib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol

from flakipype.agent.tools import ToolError
from flakipype.github.actions import GitHubApiError
from flakipype.github.pulls import FileTree

_CRLF = "\r\n"


class RepositoryFiles(Protocol):
    def file_tree(self, repository: str, commit: str) -> FileTree: ...

    def file_bytes(self, repository: str, path: str, commit: str) -> bytes | None: ...


@dataclass(frozen=True)
class FileChange:
    path: str
    # None for a new file.
    before: str | None
    after: str

    def diff_lines(self) -> list[str]:
        return list(
            difflib.unified_diff(
                (self.before or "").splitlines(),
                self.after.splitlines(),
                fromfile="/dev/null" if self.before is None else f"a/{self.path}",
                tofile=f"b/{self.path}",
                lineterm="",
            )
        )

    @property
    def added(self) -> list[str]:
        return [line[1:] for line in self.diff_lines()[2:] if line.startswith("+")]

    @property
    def removed(self) -> list[str]:
        return [line[1:] for line in self.diff_lines()[2:] if line.startswith("-")]


def unified_diff(changes: list[FileChange]) -> str:
    return "\n".join(line for change in changes for line in change.diff_lines())


def normal_path(path: str) -> str:
    """A repository-relative path; refuses absolute paths, `..` and the `.git` directory."""
    cleaned = path.strip().replace("\\", "/")
    parts = [part for part in cleaned.split("/") if part not in {"", "."}]
    if not parts or cleaned.startswith("/") or ".." in parts or parts[0] == ".git":
        message = f"{path!r} is not a file path inside the repository"
        raise ToolError(message)
    return str(PurePosixPath(*parts))


def _with_line_endings_of(original: str, text: str) -> str:
    """New text uses the file's line endings, so an edit never changes every line."""
    unified = text.replace(_CRLF, "\n")
    return unified.replace("\n", _CRLF) if _CRLF in original else unified


class WorkingCopy:
    def __init__(self, files: RepositoryFiles, repository: str, commit: str) -> None:
        self._files = files
        self.repository = repository
        self.commit = commit
        self._originals: dict[str, str | None] = {}
        self._edited: dict[str, str] = {}
        self._tree: FileTree | None = None

    def tree(self) -> FileTree:
        if self._tree is None:
            self._tree = _github(lambda: self._files.file_tree(self.repository, self.commit))
        new = tuple(path for path in self._edited if path not in self._tree.paths)
        return FileTree(tuple(sorted({*self._tree.paths, *new})), self._tree.truncated)

    def read(self, path: str) -> str | None:
        name = normal_path(path)
        if name in self._edited:
            return self._edited[name]
        return self._original(name)

    def write(self, path: str, content: str) -> None:
        name = normal_path(path)
        original = self._original(name)
        self._edited[name] = _with_line_endings_of(original or "", content)

    def replace(self, path: str, old: str, new: str) -> None:
        name = normal_path(path)
        current = self.read(name)
        if current is None:
            message = f"{name} does not exist; write_file creates new files"
            raise ToolError(message)
        text, wanted = current.replace(_CRLF, "\n"), old.replace(_CRLF, "\n")
        count = text.count(wanted)
        if count != 1:
            found = "not found" if count == 0 else f"found {count} times"
            message = f"The text to replace is {found} in {name}; give exactly one occurrence"
            raise ToolError(message)
        replaced = text.replace(wanted, new.replace(_CRLF, "\n"))
        self._edited[name] = _with_line_endings_of(current, replaced)

    def apply(self, changes: list[FileChange]) -> None:
        """Start from an earlier proposal's changes."""
        for change in changes:
            self._originals[change.path] = change.before
            self._edited[change.path] = change.after

    def changes(self) -> list[FileChange]:
        return [
            FileChange(path, self._originals[path], after)
            for path, after in sorted(self._edited.items())
            if after != self._originals[path]
        ]

    def _original(self, name: str) -> str | None:
        if name not in self._originals:
            raw = _github(lambda: self._files.file_bytes(self.repository, name, self.commit))
            self._originals[name] = None if raw is None else _text(name, raw)
        return self._originals[name]


def _text(name: str, raw: bytes) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        message = f"{name} is not a UTF-8 text file and cannot be edited"
        raise ToolError(message) from error
    if "\x00" in text:
        message = f"{name} is a binary file and cannot be edited"
        raise ToolError(message)
    return text


def _github[Result](call: Callable[[], Result]) -> Result:
    try:
        return call()
    except GitHubApiError as error:
        message = f"GitHub refused: {error}"
        raise ToolError(message) from error
