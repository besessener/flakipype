from dataclasses import replace

import pytest

from flakipype.agent.workcopy import FileChange
from flakipype.fix.delivery import DeliveryError
from flakipype.fix.state import Proposal
from flakipype.fix.verify import Stage
from flakipype.github.actions import GitHubApiError
from flakipype.store.database import ScanCache

from support.fake_fix import (
    BRANCH,
    CHANGE,
    COMMIT,
    EXPLANATION,
    FIX_COMMIT,
    TITLE,
    FixWorld,
    verification,
)
from support.fake_runs import E2E

FORBIDDEN = GitHubApiError("Resource not accessible by integration (HTTP 403)", 403)
SERVER_ERROR = GitHubApiError("Server Error (HTTP 500)", 500)
LEFT = "The branch was left as it is; flakipype never deletes branches."


def proposal(*changes: FileChange) -> Proposal:
    return Proposal(
        finding=2, identity="flaky|octo-org/app|e2e", base="main", commit=COMMIT, title=TITLE,
        explanation=EXPLANATION, body="body", changes=changes or (CHANGE,), warnings=(),
        accepted=True, review="accepted: ok",
        verification=replace(verification(), pull_number=0, commit=COMMIT),
    )  # fmt: skip


def test_a_fix_becomes_a_branch_a_signed_commit_and_a_draft(cache: ScanCache) -> None:
    world = FixWorld(cache)
    world.github.files[E2E] = b"on: pull_request\njobs: {}\n"

    opened = world.delivery.deliver(proposal())

    assert world.github.calls == [
        f"create_branch octo-org/app {BRANCH} 3f2a9c1",
        f"commit_files octo-org/app {BRANCH}",
        f"open_draft octo-org/app {BRANCH}",
        f"file_bytes octo-org/app {E2E} c0ffee1",
    ]
    (commit,) = world.github.commits
    assert commit.expected_head == COMMIT
    assert (commit.headline, commit.body) == (TITLE, f"{EXPLANATION}\n\nGenerated-by: flakipype")
    assert commit.files == {CHANGE.path: b"await rows.waitFor()\n"}
    (draft,) = world.github.drafts
    assert (draft.title, draft.body, draft.head, draft.base) == (TITLE, "body", BRANCH, "main")
    assert (opened.finding, opened.title, opened.branch) == (2, TITLE, BRANCH)
    assert opened.url == "https://github.com/octo-org/app/pull/12"
    assert opened.verification.stage is Stage.WAITING
    assert (opened.verification.pull_number, opened.verification.commit) == (12, FIX_COMMIT)


def test_an_existing_branch_name_gets_a_suffix(cache: ScanCache) -> None:
    world = FixWorld(cache)
    world.github.taken_branches = {BRANCH, f"{BRANCH}-2"}

    opened = world.delivery.deliver(proposal())

    assert opened.branch == f"{BRANCH}-3"
    assert world.github.drafts[0].head == f"{BRANCH}-3"


def test_too_many_existing_branch_names_stop_before_anything_is_written(
    cache: ScanCache,
) -> None:
    world = FixWorld(cache)
    world.github.taken_branches = {BRANCH, *(f"{BRANCH}-{index}" for index in range(2, 6))}

    with pytest.raises(DeliveryError, match=f"GitHub: branches {BRANCH} to {BRANCH}-5 exist"):
        world.delivery.deliver(proposal())
    assert world.github.commits == []


def test_a_refused_branch_says_which_permission_is_missing(cache: ScanCache) -> None:
    world = FixWorld(cache)
    world.github.errors["create_branch"] = FORBIDDEN

    with pytest.raises(DeliveryError) as raised:
        world.delivery.deliver(proposal())

    assert str(raised.value).startswith("GitHub refused: Resource not accessible")
    assert "'Contents', 'Pull requests' and 'Workflows: read and write'" in str(raised.value)


def test_a_failed_commit_says_the_branch_exists(cache: ScanCache) -> None:
    world = FixWorld(cache)
    world.github.errors["commit_files"] = SERVER_ERROR

    with pytest.raises(DeliveryError) as raised:
        world.delivery.deliver(proposal())

    assert str(raised.value) == (
        f"Branch {BRANCH} created; the commit failed: GitHub: Server Error (HTTP 500) {LEFT}"
    )
    assert world.github.drafts == []


def test_a_failed_pull_request_says_branch_and_commit_exist(cache: ScanCache) -> None:
    world = FixWorld(cache)
    world.github.errors["open_draft"] = SERVER_ERROR

    with pytest.raises(DeliveryError) as raised:
        world.delivery.deliver(proposal())

    assert str(raised.value) == (
        f"Branch {BRANCH} with commit c0ffee1 created; opening the pull request failed: "
        f"GitHub: Server Error (HTTP 500) {LEFT}"
    )


def test_a_changed_workflow_is_verified_from_the_diff(cache: ScanCache) -> None:
    world = FixWorld(cache)
    workflow = FileChange(E2E, "on: push\njobs: {}\n", "on: schedule\njobs: {}\n")

    opened = world.delivery.deliver(proposal(CHANGE, workflow))

    assert not [call for call in world.github.calls if call.startswith("file_bytes")]
    assert opened.verification.stage is Stage.DONE
    assert "cannot verify automatically: the workflow runs neither" in (opened.verification.outcome)


def test_a_missing_workflow_file_cannot_be_verified(cache: ScanCache) -> None:
    world = FixWorld(cache)

    opened = world.delivery.deliver(proposal())

    assert "cannot verify automatically" in opened.verification.outcome


def test_verification_that_cannot_start_leaves_the_pull_request(cache: ScanCache) -> None:
    world = FixWorld(cache)
    world.github.errors["file_bytes"] = SERVER_ERROR

    opened = world.delivery.deliver(proposal())

    assert opened.url.endswith("/pull/12")
    assert opened.verification.stage is Stage.DONE
    assert opened.verification.outcome == ("Verification could not start: Server Error (HTTP 500)")
