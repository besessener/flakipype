"""GitHub errors of actions, turned into tool errors that say which permission is missing."""

from collections.abc import Iterator
from contextlib import contextmanager

from flakipype.agent.tools import ToolError
from flakipype.github.actions import GitHubApiError

_HTTP_FORBIDDEN = 403


def refusal(error: GitHubApiError) -> str:
    if error.status == _HTTP_FORBIDDEN:
        return (
            f"GitHub refused: {error}. flakipype needs write access to Actions: the repo scope "
            "for a classic token or gh auth login, or 'Actions: read and write' for a "
            "fine-grained token."
        )
    return f"GitHub: {error}"


@contextmanager
def from_github() -> Iterator[None]:
    try:
        yield
    except GitHubApiError as error:
        raise ToolError(refusal(error)) from error
