import base64
import json

import pytest

from flakipype.github.actions import GitHubApiError
from flakipype.github.pulls import (
    CommitRequest,
    FileTooLargeError,
    PullRequests,
    PullRequestText,
)

from support.fake_gh import FakeGh

REPO = "octo-org/app"
SHA = "3f2a9c1" + "0" * 33


def failing(fake_gh: FakeGh, args: list[str], status: int, text: str = "Error") -> None:
    fake_gh.record(args, stderr=f"gh: {text} (HTTP {status})", exit_code=1)


def content(text: bytes) -> str:
    return json.dumps(
        {"type": "file", "encoding": "base64", "content": base64.b64encode(text).decode()}
    )


def test_access_and_branch_head(fake_gh: FakeGh) -> None:
    answer = {"default_branch": "main", "permissions": {"push": True, "admin": False}}
    fake_gh.record(["api", f"repos/{REPO}"], stdout=json.dumps(answer))
    fake_gh.record(
        ["api", f"repos/{REPO}/branches/main"], stdout=json.dumps({"commit": {"sha": SHA}})
    )
    pulls = PullRequests(fake_gh.cli())

    access = pulls.access(REPO)

    assert (access.default_branch, access.can_push) == ("main", True)
    assert pulls.branch_head(REPO, "main") == SHA


def test_access_without_permissions_means_no_push(fake_gh: FakeGh) -> None:
    fake_gh.record(["api", f"repos/{REPO}"], stdout='{"default_branch": "main"}')

    assert not PullRequests(fake_gh.cli()).access(REPO).can_push


def test_file_tree_lists_files_only(fake_gh: FakeGh) -> None:
    tree = {
        "truncated": True,
        "tree": [{"path": "src", "type": "tree"}, {"path": "src/a.py", "type": "blob"}],
    }
    fake_gh.record(["api", f"repos/{REPO}/git/trees/{SHA}?recursive=1"], stdout=json.dumps(tree))

    found = PullRequests(fake_gh.cli()).file_tree(REPO, SHA)

    assert (found.paths, found.truncated) == (("src/a.py",), True)


def test_file_bytes_keep_line_endings(fake_gh: FakeGh) -> None:
    contents = f"repos/{REPO}/contents"
    fake_gh.record(["api", f"{contents}/a%20b.txt?ref={SHA}"], stdout=content(b"x\r\ny\r\n"))
    fake_gh.record(["api", f"{contents}/src?ref={SHA}"], stdout='[{"type": "file"}]')
    fake_gh.record(["api", f"{contents}/link?ref={SHA}"], stdout='{"type": "symlink"}')
    failing(fake_gh, ["api", f"{contents}/gone?ref={SHA}"], 404, "Not Found")
    pulls = PullRequests(fake_gh.cli())

    assert pulls.file_bytes(REPO, "a b.txt", SHA) == b"x\r\ny\r\n"
    assert pulls.file_bytes(REPO, "src", SHA) is None
    assert pulls.file_bytes(REPO, "link", SHA) is None
    assert pulls.file_bytes(REPO, "gone", SHA) is None


def test_file_bytes_errors(fake_gh: FakeGh) -> None:
    contents = f"repos/{REPO}/contents"
    big = {"type": "file", "encoding": "none", "content": ""}
    fake_gh.record(["api", f"{contents}/big?ref={SHA}"], stdout=json.dumps(big))
    broken = {"type": "file", "encoding": "base64", "content": "@@@"}
    fake_gh.record(["api", f"{contents}/broken?ref={SHA}"], stdout=json.dumps(broken))
    failing(fake_gh, ["api", f"{contents}/denied?ref={SHA}"], 403)
    pulls = PullRequests(fake_gh.cli())

    with pytest.raises(FileTooLargeError, match="too large"):
        pulls.file_bytes(REPO, "big", SHA)
    with pytest.raises(GitHubApiError, match="Unexpected answer"):
        pulls.file_bytes(REPO, "broken", SHA)
    with pytest.raises(GitHubApiError):
        pulls.file_bytes(REPO, "denied", SHA)


def test_create_branch_never_moves_an_existing_one(fake_gh: FakeGh) -> None:
    def args(branch: str) -> list[str]:
        return ["api", "-X", "POST", f"repos/{REPO}/git/refs",
                "-f", f"ref=refs/heads/{branch}", "-f", f"sha={SHA}"]  # fmt: skip

    fake_gh.record(args("flakipype/fix-e2e-1"), stdout="{}")
    failing(fake_gh, args("flakipype/fix-e2e-2"), 422, "Reference already exists")
    failing(fake_gh, args("flakipype/fix-e2e-3"), 403, "Resource not accessible")
    pulls = PullRequests(fake_gh.cli())

    assert pulls.create_branch(REPO, "flakipype/fix-e2e-1", SHA)
    assert not pulls.create_branch(REPO, "flakipype/fix-e2e-2", SHA)
    with pytest.raises(GitHubApiError):
        pulls.create_branch(REPO, "flakipype/fix-e2e-3", SHA)


def test_commit_files_sends_one_signed_commit_on_the_branch(fake_gh: FakeGh) -> None:
    answer = {"data": {"createCommitOnBranch": {"commit": {"oid": "c0ffee"}}}}
    fake_gh.record(["api", "graphql", "--input", "-"], stdout=json.dumps(answer))
    request = CommitRequest(
        branch="flakipype/fix-e2e-1",
        expected_head=SHA,
        headline="Wait for rows",
        body="Because.",
        files={"b.txt": b"b\n", "a.txt": b"a\r\n"},
    )

    oid = PullRequests(fake_gh.cli()).commit_files(REPO, request)

    sent = json.loads(fake_gh.invocations()[0]["stdin"])
    mutation = sent["variables"]["input"]
    assert oid == "c0ffee"
    assert "createCommitOnBranch" in sent["query"]
    assert mutation["branch"] == {"repositoryNameWithOwner": REPO, "branchName": request.branch}
    assert mutation["expectedHeadOid"] == SHA
    assert mutation["message"] == {"headline": "Wait for rows", "body": "Because."}
    additions = mutation["fileChanges"]["additions"]
    assert [item["path"] for item in additions] == ["a.txt", "b.txt"]
    assert base64.b64decode(additions[0]["contents"]) == b"a\r\n"


def test_a_refused_commit_raises(fake_gh: FakeGh) -> None:
    failing(fake_gh, ["api", "graphql", "--input", "-"], 422, "Expected branch to point to x")
    request = CommitRequest("b", SHA, "h", "", {})

    with pytest.raises(GitHubApiError, match="Expected branch"):
        PullRequests(fake_gh.cli()).commit_files(REPO, request)


def test_pull_requests_are_always_drafts(fake_gh: FakeGh) -> None:
    answer = {"number": 12, "html_url": "https://x/12", "body": "b", "head": {"ref": "fix"}}
    fake_gh.record(
        ["api", "-X", "POST", f"repos/{REPO}/pulls", "--input", "-"], stdout=json.dumps(answer)
    )

    pull = PullRequests(fake_gh.cli()).open_draft(
        REPO, PullRequestText(title="T", body="B", head="fix", base="main")
    )

    sent = json.loads(fake_gh.invocations()[0]["stdin"])
    assert sent == {"title": "T", "body": "B", "head": "fix", "base": "main", "draft": True}
    assert (pull.number, pull.url, pull.branch) == (12, "https://x/12", "fix")


def test_open_pulls_and_comments(fake_gh: FakeGh) -> None:
    listed = [
        {"number": 3, "html_url": "u3", "body": None, "head": {"ref": "feature"}},
        {"number": 4, "html_url": "u4", "body": "marker", "head": {"ref": "flakipype/fix"}},
    ]
    fake_gh.record(
        ["api", f"repos/{REPO}/pulls?state=open&per_page=100"], stdout=json.dumps(listed)
    )
    fake_gh.record(["api", "-X", "POST", f"repos/{REPO}/issues/4/comments", "--input", "-"])
    pulls = PullRequests(fake_gh.cli())

    found = pulls.open_pulls(REPO)
    pulls.comment(REPO, 4, "verified")

    assert [(pull.number, pull.body) for pull in found] == [(3, ""), (4, "marker")]
    assert json.loads(fake_gh.invocations()[-1]["stdin"]) == {"body": "verified"}


def test_failed_reads_raise(fake_gh: FakeGh) -> None:
    failing(fake_gh, ["api", f"repos/{REPO}"], 404, "Not Found")
    failing(fake_gh, ["api", "-X", "POST", f"repos/{REPO}/issues/4/comments", "--input", "-"], 403)
    pulls = PullRequests(fake_gh.cli())

    with pytest.raises(GitHubApiError):
        pulls.access(REPO)
    with pytest.raises(GitHubApiError):
        pulls.comment(REPO, 4, "x")
