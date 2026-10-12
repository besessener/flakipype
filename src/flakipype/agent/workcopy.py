"""The fixer's working copy: edits kept in memory over one pinned commit, never on disk."""

import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol

from flakipype.agent.masking import MASK_MARKER
from flakipype.agent.tools import ToolError
from flakipype.github.actions import GitHubApiError
from flakipype.github.pulls import FileTree

_CRLF = "\r\n"
_NO_FINAL_NEWLINE = "\\ No newline at end of file"
# C0 and C1 control characters; a path holding one could rewrite the confirmation dialog.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


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
        """Lines compare with their endings, so a changed final newline or CRLF is a change too."""
        lines: list[str] = []
        for line in difflib.unified_diff(
            _lines_with_endings(self.before or ""),
            _lines_with_endings(self.after),
            fromfile="/dev/null" if self.before is None else f"a/{self.path}",
            tofile=f"b/{self.path}",
        ):
            lines.append(line.removesuffix("\n").removesuffix("\r"))
            if not line.endswith("\n"):
                lines.append(_NO_FINAL_NEWLINE)
        return lines

    @property
    def added(self) -> list[str]:
        return [line[1:] for line in self.diff_lines()[2:] if line.startswith("+")]

    @property
    def removed(self) -> list[str]:
        return [line[1:] for line in self.diff_lines()[2:] if line.startswith("-")]


def _lines_with_endings(text: str) -> list[str]:
    parts = text.split("\n")
    lines = [f"{part}\n" for part in parts[:-1]]
    return [*lines, parts[-1]] if parts[-1] else lines


def unified_diff(changes: list[FileChange]) -> str:
    return "\n".join(line for change in changes for line in change.diff_lines())


def normal_path(path: str) -> str:
    """A repository-relative path; refuses absolute paths, `..`, `.git` and control characters."""
    cleaned = path.strip().replace("\\", "/")
    parts = [part for part in cleaned.split("/") if part not in {"", "."}]
    invalid = not parts or cleaned.startswith("/") or ".." in parts or parts[0] == ".git"
    if invalid or _CONTROL.search(cleaned):
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
        paths = tuple(sorted({*self._tree.paths, *new}))
        return FileTree(paths, self._tree.truncated, self._tree.links)

    def read(self, path: str) -> str | None:
        name = normal_path(path)
        if name in self._edited:
            return self._edited[name]
        return self._original(name)

    def write(self, path: str, content: str) -> None:
        name = normal_path(path)
        original = self._original(name)
        _refuse_mask_markers(name, original, content)
        # read_file shows numbered lines, so the model cannot see a final newline to keep.
        if original and original.endswith("\n") and content and not content.endswith("\n"):
            content += "\n"
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
        _refuse_mask_markers(name, self._original(name), replaced)
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
            if name in self.tree().links:
                message = (
                    f"{name} is a symbolic link or a submodule and cannot be edited; "
                    "edit the file it points to instead"
                )
                raise ToolError(message)
            raw = _github(lambda: self._files.file_bytes(self.repository, name, self.commit))
            self._originals[name] = None if raw is None else _text(name, raw)
        return self._originals[name]


def _refuse_mask_markers(name: str, original: str | None, text: str) -> None:
    """The model sees secrets masked; writing a placeholder back would replace real code."""
    if text.count(MASK_MARKER) > (original or "").count(MASK_MARKER):
        message = (
            f"The new text of {name} contains `{MASK_MARKER}...]`, which hides real content "
            "that you cannot see. Leave masked lines unchanged: edit only the other lines "
            "with replace_in_file."
        )
        raise ToolError(message)


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
