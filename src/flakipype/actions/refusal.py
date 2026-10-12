"""GitHub errors of actions, turned into tool errors: a missing permission or the rate limit."""

from collections.abc import Generator
from contextlib import contextmanager

from flakipype.agent.tools import ToolError
from flakipype.github.actions import ApiRateLimitError, GitHubApiError

_HTTP_FORBIDDEN = 403


def refusal(error: GitHubApiError) -> str:
    if isinstance(error, ApiRateLimitError):
        return error.next_step()
    if error.status == _HTTP_FORBIDDEN:
        return (
            f"GitHub refused: {error}. flakipype needs write access to Actions: the repo scope "
            "for a classic token or gh auth login, or 'Actions: read and write' for a "
            "fine-grained token."
        )
    return f"GitHub: {error}"


@contextmanager
def from_github() -> Generator[None]:
    try:
        yield
    except GitHubApiError as error:
        raise ToolError(refusal(error)) from error
