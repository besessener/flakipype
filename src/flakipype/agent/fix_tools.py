"""The fixer's tools on its working copy; edits change only memory, so they are risk `read`."""

from dataclasses import dataclass

from pydantic import BaseModel, Field

from flakipype.agent.prompts import data_block
from flakipype.agent.tools import RiskLevel, Tool, ToolError
from flakipype.agent.workcopy import WorkingCopy, normal_path, unified_diff

_MAX_LISTED = 300
_MAX_READ_LINES = 400


class ListFilesInput(BaseModel):
    path: str = Field(default="", description="directory; empty for the repository root")


class ReadInput(BaseModel):
    path: str
    from_line: int = Field(default=1, ge=1)
    to_line: int | None = Field(default=None, ge=1, description="default: 400 lines")


class ReplaceInput(BaseModel):
    path: str
    old: str = Field(min_length=1, description="exact text that occurs once in the file")
    new: str


class WriteInput(BaseModel):
    path: str
    content: str


class NoInput(BaseModel):
    pass


@dataclass
class FixTools:
    copy: WorkingCopy

    def tools(self) -> list[Tool]:
        read = RiskLevel.READ
        return [
            Tool("list_files", "Files and directories under a path of the working copy.",
                 read, ListFilesInput, self._list_files),
            Tool("read_file", "A file of the working copy (with your edits), numbered.",
                 read, ReadInput, self._read_file),
            Tool("replace_in_file", "Replace one exact, unique occurrence of text in a file.",
                 read, ReplaceInput, self._replace),
            Tool("write_file", "Create a file, or replace a whole file.",
                 read, WriteInput, self._write),
            Tool("show_diff", "The unified diff of all edits so far.",
                 read, NoInput, lambda _: self._show_diff()),
        ]  # fmt: skip

    def _list_files(self, given: ListFilesInput) -> str:
        prefix = normal_path(given.path) + "/" if given.path.strip(" ./") else ""
        tree = self.copy.tree()
        entries = sorted(
            {
                rest.split("/", 1)[0] + ("/" if "/" in rest else "")
                for path in tree.paths
                if path.startswith(prefix)
                for rest in [path[len(prefix) :]]
            }
        )
        if not entries:
            message = f"{given.path} is not a directory of the working copy"
            raise ToolError(message)
        shown = entries[:_MAX_LISTED]
        notes = [f"[… {len(entries) - len(shown)} more …]"] if len(entries) > len(shown) else []
        if tree.truncated:
            notes.append("[GitHub listed only part of this large repository]")
        return data_block("files", "\n".join([*shown, *notes]), path=prefix or "/")

    def _read_file(self, given: ReadInput) -> str:
        content = self.copy.read(given.path)
        if content is None:
            message = f"{given.path} does not exist in the working copy"
            raise ToolError(message)
        lines = content.splitlines()
        last = min(given.to_line or len(lines), given.from_line + _MAX_READ_LINES - 1, len(lines))
        shown = lines[given.from_line - 1 : last]
        numbered = "\n".join(
            f"{number:>5} {text}" for number, text in enumerate(shown, start=given.from_line)
        )
        return data_block(
            "file", numbered, path=normal_path(given.path), ref="working copy",
            lines=f"{given.from_line}-{given.from_line + len(shown) - 1} of {len(lines)}",
        )  # fmt: skip

    def _replace(self, given: ReplaceInput) -> str:
        self.copy.replace(given.path, given.old, given.new)
        return f"Replaced the text in {normal_path(given.path)}. {self._size()}"

    def _write(self, given: WriteInput) -> str:
        self.copy.write(given.path, given.content)
        return f"Wrote {normal_path(given.path)}. {self._size()}"

    def _show_diff(self) -> str:
        return data_block("diff", unified_diff(self.copy.changes()) or "no changes yet")

    def _size(self) -> str:
        changes = self.copy.changes()
        lines = sum(len(change.added) + len(change.removed) for change in changes)
        return f"The working copy now changes {len(changes)} files, {lines} lines."
