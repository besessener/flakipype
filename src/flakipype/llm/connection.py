from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus

import anthropic
import openai
from anthropic import Anthropic


class ConnectionProblem(StrEnum):
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    BAD_REQUEST = "bad_request"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    UNREACHABLE = "unreachable"
    UNEXPECTED_ANSWER = "unexpected_answer"
    ENVIRONMENT = "environment"

    @property
    def next_step(self) -> str:
        return _NEXT_STEPS[self]


_NEXT_STEPS = {
    ConnectionProblem.AUTHENTICATION: "The API key was rejected. "
    "Check that it belongs to this endpoint.",
    ConnectionProblem.PERMISSION: "The key is valid but may not use this model. "
    "Check its permissions.",
    ConnectionProblem.NOT_FOUND: "Model or URL not found. Check the model name (on Foundry: the "
    "deployment name), the base URL and the provider.",
    ConnectionProblem.BAD_REQUEST: "The endpoint rejected the request. Check the model name "
    "and that the model supports tool calling.",
    ConnectionProblem.RATE_LIMITED: "Rate limit or quota reached. Wait a moment and test again.",
    ConnectionProblem.SERVER_ERROR: "The endpoint has a problem. Try again later.",
    ConnectionProblem.TIMEOUT: "No answer in time. Check the URL, proxy and network.",
    ConnectionProblem.UNREACHABLE: "Cannot reach the endpoint. Check the URL, proxy and network.",
    ConnectionProblem.UNEXPECTED_ANSWER: "The endpoint did not answer like the API of the "
    "configured provider. Check the base URL and the provider.",
    ConnectionProblem.ENVIRONMENT: "An environment variable conflicts with the configured "
    "endpoint. Unset it and test again.",
}

_PROBLEM_BY_STATUS: dict[int, ConnectionProblem] = {
    HTTPStatus.UNAUTHORIZED: ConnectionProblem.AUTHENTICATION,
    HTTPStatus.FORBIDDEN: ConnectionProblem.PERMISSION,
    HTTPStatus.NOT_FOUND: ConnectionProblem.NOT_FOUND,
    HTTPStatus.BAD_REQUEST: ConnectionProblem.BAD_REQUEST,
    HTTPStatus.UNPROCESSABLE_ENTITY: ConnectionProblem.BAD_REQUEST,
    HTTPStatus.TOO_MANY_REQUESTS: ConnectionProblem.RATE_LIMITED,
}


_TIMEOUT_ERRORS = (anthropic.APITimeoutError, openai.APITimeoutError)
_CONNECTION_ERRORS = (anthropic.APIConnectionError, openai.APIConnectionError)
_STATUS_ERRORS = (anthropic.APIStatusError, openai.APIStatusError)
REQUEST_ERRORS = (*_CONNECTION_ERRORS, *_STATUS_ERRORS)
type ApiError = anthropic.APIError | openai.APIError


class ModelError(Exception):
    """A model call failed; the problem names the kind of failure and the user's next step."""

    def __init__(self, problem: ConnectionProblem, detail: str) -> None:
        super().__init__(f"{detail.rstrip('.')}. {problem.next_step}")
        self.problem = problem
        self.detail = detail


@dataclass(frozen=True)
class ConnectionOk:
    model: str


@dataclass(frozen=True)
class ConnectionFailed:
    problem: ConnectionProblem
    detail: str


type ConnectionResult = ConnectionOk | ConnectionFailed


def problem_for_status(status_code: int) -> ConnectionProblem:
    return _PROBLEM_BY_STATUS.get(status_code, ConnectionProblem.SERVER_ERROR)


def problem_for_error(error: ApiError) -> ConnectionProblem:
    if isinstance(error, _TIMEOUT_ERRORS):
        return ConnectionProblem.TIMEOUT
    if isinstance(error, _CONNECTION_ERRORS):
        return ConnectionProblem.UNREACHABLE
    if isinstance(error, _STATUS_ERRORS):
        # An error event in an open stream comes with the stream's status, 200.
        return problem_for_status(error.status_code)
    return ConnectionProblem.UNEXPECTED_ANSWER


def check_connection(client: Anthropic, model: str) -> ConnectionResult:
    """Send the smallest possible request to prove URL, key and model work together."""
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
    except REQUEST_ERRORS as error:
        return ConnectionFailed(problem_for_error(error), error.message)
    return answered_model(response)


def answered_model(response: object) -> ConnectionResult:
    """The model a ping answer names; it proves the endpoint speaks the expected API."""
    # Without strict validation, any 200 answer passes: a sign-in page or another JSON API.
    answered = getattr(response, "model", None)
    if not isinstance(answered, str) or not answered:
        return ConnectionFailed(ConnectionProblem.UNEXPECTED_ANSWER, f"Answer: {response!r:.200}")
    return ConnectionOk(model=answered)
