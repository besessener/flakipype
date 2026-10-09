"""Read commits, diffs and files of a repository through `gh api` (no clone)."""

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

from flakipype.github.actions import api_error, parse_answer
from flakipype.github.gh import GhCli
from flakipype.github.payloads import ComparisonPayload

_HTTP_NOT_FOUND = 404
_RAW = "Accept: application/vnd.github.raw"


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    author: str
    date: datetime | None


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str
    additions: int
    deletions: int
    patch: str


@dataclass(frozen=True)
class Comparison:
    total_commits: int
    commits: list[Commit]
    files: list[ChangedFile]


class ContentsClient:
    def __init__(self, gh: GhCli) -> None:
        self._gh = gh

    def compare(self, repository: str, base: str, head: str) -> Comparison:
        path = f"repos/{repository}/compare/{quote(base, safe='')}...{quote(head, safe='')}"
        result = self._gh.run(["api", path])
        if not result.succeeded:
            raise api_error(result)
        payload = parse_answer(ComparisonPayload.model_validate_json, result.stdout)
        return Comparison(
            total_commits=payload.total_commits,
            commits=[
                Commit(
                    sha=item.sha,
                    subject=item.commit.message.split("\n", 1)[0],
                    author=item.commit.author.name,
                    date=item.commit.author.date,
                )
                for item in payload.commits
            ],
            files=[
                ChangedFile(item.filename, item.status, item.additions, item.deletions, item.patch)
                for item in payload.files
            ],
        )

    def file_content(self, repository: str, path: str, ref: str) -> str | None:
        """The file's text at `ref`, or None if it does not exist there."""
        api_path = f"repos/{repository}/contents/{quote(path)}?ref={quote(ref, safe='')}"
        result = self._gh.run(["api", api_path, "-H", _RAW])
        if result.succeeded:
            return result.stdout
        error = api_error(result)
        if error.status == _HTTP_NOT_FOUND:
            return None
        raise error
