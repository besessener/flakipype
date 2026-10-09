"""Branches, signed commits and pull requests for fixes, through `gh api` (no clone, no git)."""

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote

from flakipype.github.actions import GitHubApiError, api_error, parse_answer
from flakipype.github.gh import GhCli
from flakipype.github.payloads import (
    BranchPayload,
    CommitMutationPayload,
    FileContentPayload,
    PullPayload,
    RepositoryAccessPayload,
    TreePayload,
)

_HTTP_NOT_FOUND = 404
_HTTP_UNPROCESSABLE = 422
_OPEN_PULLS_LISTED = 100
_COMMIT_MUTATION = """\
mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { oid } }
}"""


class FileTooLargeError(GitHubApiError):
    """GitHub sends no content for files above its size limit for the contents API."""


@dataclass(frozen=True)
class RepositoryAccess:
    default_branch: str
    can_push: bool


@dataclass(frozen=True)
class FileTree:
    paths: tuple[str, ...]
    # GitHub cuts very large trees short; the listing is then incomplete.
    truncated: bool


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    branch: str
    body: str


@dataclass(frozen=True)
class PullRequestText:
    title: str
    body: str
    head: str
    base: str


@dataclass(frozen=True)
class CommitRequest:
    branch: str
    # The commit the branch points to now; GitHub refuses the commit if it moved.
    expected_head: str
    headline: str
    body: str
    files: Mapping[str, bytes]


class PullRequests:
    def __init__(self, gh: GhCli) -> None:
        self._gh = gh

    def access(self, repository: str) -> RepositoryAccess:
        payload = parse_answer(
            RepositoryAccessPayload.model_validate_json, self._get(f"repos/{repository}")
        )
        return RepositoryAccess(payload.default_branch, payload.permissions.push)

    def branch_head(self, repository: str, branch: str) -> str:
        output = self._get(f"repos/{repository}/branches/{quote(branch, safe='')}")
        return parse_answer(BranchPayload.model_validate_json, output).commit.sha

    def file_tree(self, repository: str, commit: str) -> FileTree:
        output = self._get(f"repos/{repository}/git/trees/{commit}?recursive=1")
        payload = parse_answer(TreePayload.model_validate_json, output)
        paths = tuple(entry.path for entry in payload.tree if entry.type == "blob")
        return FileTree(paths, payload.truncated)

    def file_bytes(self, repository: str, path: str, commit: str) -> bytes | None:
        """The file exactly as stored (line endings included); None if it does not exist."""
        api_path = f"repos/{repository}/contents/{quote(path)}?ref={commit}"
        result = self._gh.run(["api", api_path])
        if not result.succeeded:
            error = api_error(result)
            if error.status == _HTTP_NOT_FOUND:
                return None
            raise error
        answer = parse_answer(json.loads, result.stdout)
        # A directory comes back as a list of its entries.
        if not isinstance(answer, dict):
            return None
        payload = parse_answer(FileContentPayload.model_validate_json, result.stdout)
        if payload.type != "file":
            return None
        if payload.encoding != "base64":
            message = f"{path} is too large for GitHub's contents API"
            raise FileTooLargeError(message)
        try:
            # GitHub wraps the base64 text in lines of 60 characters.
            return base64.b64decode(payload.content.replace("\n", ""), validate=True)
        except binascii.Error as error:
            message = f"Unexpected answer from GitHub for {path}: {error}"
            raise GitHubApiError(message) from error

    def create_branch(self, repository: str, branch: str, commit: str) -> bool:
        """False if a branch or tag of that name exists already; never moves an existing ref."""
        fields = ["-f", f"ref=refs/heads/{branch}", "-f", f"sha={commit}"]
        result = self._gh.run(["api", "-X", "POST", f"repos/{repository}/git/refs", *fields])
        if result.succeeded:
            return True
        error = api_error(result)
        if error.status == _HTTP_UNPROCESSABLE and "already exists" in str(error):
            return False
        raise error

    def commit_files(self, repository: str, commit: CommitRequest) -> str:
        """One commit on the branch, signed by GitHub; returns its sha."""
        mutation_input = {
            "branch": {"repositoryNameWithOwner": repository, "branchName": commit.branch},
            "expectedHeadOid": commit.expected_head,
            "message": {"headline": commit.headline, "body": commit.body},
            "fileChanges": {
                "additions": [
                    {"path": path, "contents": base64.b64encode(content).decode("ascii")}
                    for path, content in sorted(commit.files.items())
                ]
            },
        }
        body = {"query": _COMMIT_MUTATION, "variables": {"input": mutation_input}}
        output = self._send(["api", "graphql", "--input", "-"], body)
        return parse_answer(
            CommitMutationPayload.model_validate_json, output
        ).data.created.commit.oid

    def open_draft(self, repository: str, pull: PullRequestText) -> PullRequest:
        """Always a draft: flakipype never opens a pull request ready for merging."""
        request = {
            "title": pull.title,
            "body": pull.body,
            "head": pull.head,
            "base": pull.base,
            "draft": True,
        }
        output = self._send(
            ["api", "-X", "POST", f"repos/{repository}/pulls", "--input", "-"], request
        )
        payload = parse_answer(PullPayload.model_validate_json, output)
        return PullRequest(payload.number, payload.html_url, payload.head.ref, payload.body or "")

    def open_pulls(self, repository: str) -> list[PullRequest]:
        path = f"repos/{repository}/pulls?state=open&per_page={_OPEN_PULLS_LISTED}"
        payloads = parse_answer(_pull_list, self._get(path))
        return [
            PullRequest(item.number, item.html_url, item.head.ref, item.body or "")
            for item in payloads
        ]

    def comment(self, repository: str, number: int, body: str) -> None:
        path = f"repos/{repository}/issues/{number}/comments"
        self._send(["api", "-X", "POST", path, "--input", "-"], {"body": body})

    def _get(self, path: str) -> str:
        result = self._gh.run(["api", path])
        if not result.succeeded:
            raise api_error(result)
        return result.stdout

    def _send(self, arguments: list[str], body: object) -> str:
        result = self._gh.run(arguments, stdin_text=json.dumps(body))
        if not result.succeeded:
            raise api_error(result)
        return result.stdout


def _pull_list(text: str) -> list[PullPayload]:
    return [PullPayload.model_validate(item) for item in json.loads(text)]
