from datetime import UTC, datetime

import pytest

from flakipype.github.actions import GitHubApiError
from flakipype.github.contents import ContentsClient

from support.fake_gh import FakeGh, gh_fixture

REPO = "besessener/flakipype"
RAW = ["-H", "Accept: application/vnd.github.raw"]


def test_recorded_comparison_is_parsed(fake_gh: FakeGh) -> None:
    fake_gh.record(
        ["api", f"repos/{REPO}/compare/6785f78...4c10fff"], stdout=gh_fixture("compare.json")
    )

    comparison = ContentsClient(fake_gh.cli()).compare(REPO, "6785f78", "4c10fff")

    (commit,) = comparison.commits
    assert comparison.total_commits == 1
    assert commit.subject == "Set up project foundation (M0)"
    assert (commit.author, commit.date) == (
        "Matthias Eggert",
        datetime(2026, 10, 9, 8, 44, 23, tzinfo=UTC),
    )
    assert [(f.path, f.status, f.additions) for f in comparison.files] == [
        (".actrc", "added", 2),
        (".python-version", "added", 1),
    ]
    assert comparison.files[1].patch == "@@ -0,0 +1 @@\n+3.12"


def test_refs_are_quoted(fake_gh: FakeGh) -> None:
    fake_gh.record(
        ["api", f"repos/{REPO}/compare/main...feature%2Fx"],
        stdout='{"total_commits": 0, "commits": []}',
    )

    comparison = ContentsClient(fake_gh.cli()).compare(REPO, "main", "feature/x")

    assert (comparison.commits, comparison.files) == ([], [])


def test_compare_errors_raise(fake_gh: FakeGh) -> None:
    fake_gh.record(
        ["api", f"repos/{REPO}/compare/a...b"], stderr="gh: Not Found (HTTP 404)", exit_code=1
    )

    with pytest.raises(GitHubApiError):
        ContentsClient(fake_gh.cli()).compare(REPO, "a", "b")


def test_file_content(fake_gh: FakeGh) -> None:
    fake_gh.record(
        ["api", f"repos/{REPO}/contents/docs/a%20b.md?ref=abc", *RAW], stdout="# Title\n"
    )

    assert ContentsClient(fake_gh.cli()).file_content(REPO, "docs/a b.md", "abc") == "# Title\n"


def test_missing_file_is_none_other_errors_raise(fake_gh: FakeGh) -> None:
    fake_gh.record(
        ["api", f"repos/{REPO}/contents/nope?ref=abc", *RAW],
        stderr="gh: Not Found (HTTP 404)",
        exit_code=1,
    )
    fake_gh.record(
        ["api", f"repos/{REPO}/contents/boom?ref=abc", *RAW],
        stderr="gh: Error (HTTP 500)",
        exit_code=1,
    )
    client = ContentsClient(fake_gh.cli())

    assert client.file_content(REPO, "nope", "abc") is None
    with pytest.raises(GitHubApiError):
        client.file_content(REPO, "boom", "abc")
