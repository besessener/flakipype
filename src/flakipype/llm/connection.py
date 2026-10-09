from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus

from anthropic import Anthropic, APIConnectionError, APIStatusError, APITimeoutError


class ConnectionProblem(StrEnum):
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    BAD_REQUEST = "bad_request"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    UNREACHABLE = "unreachable"

    @property
    def next_step(self) -> str:
        return _NEXT_STEPS[self]


_NEXT_STEPS = {
    ConnectionProblem.AUTHENTICATION: "The API key was rejected. "
    "Check that it belongs to this endpoint.",
    ConnectionProblem.PERMISSION: "The key is valid but may not use this model. "
    "Check its permissions.",
    ConnectionProblem.NOT_FOUND: "Model or URL not found. Check the model name (on Foundry: the "
    "deployment name) and the base URL.",
    ConnectionProblem.BAD_REQUEST: "The endpoint rejected the request. Check the model name.",
    ConnectionProblem.RATE_LIMITED: "Rate limit or quota reached. Wait a moment and test again.",
    ConnectionProblem.SERVER_ERROR: "The endpoint has a problem. Try again later.",
    ConnectionProblem.TIMEOUT: "No answer in time. Check the URL, proxy and network.",
    ConnectionProblem.UNREACHABLE: "Cannot reach the endpoint. Check the URL, proxy and network.",
}

_PROBLEM_BY_STATUS: dict[int, ConnectionProblem] = {
    HTTPStatus.UNAUTHORIZED: ConnectionProblem.AUTHENTICATION,
    HTTPStatus.FORBIDDEN: ConnectionProblem.PERMISSION,
    HTTPStatus.NOT_FOUND: ConnectionProblem.NOT_FOUND,
    HTTPStatus.BAD_REQUEST: ConnectionProblem.BAD_REQUEST,
    HTTPStatus.UNPROCESSABLE_ENTITY: ConnectionProblem.BAD_REQUEST,
    HTTPStatus.TOO_MANY_REQUESTS: ConnectionProblem.RATE_LIMITED,
}


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


def check_connection(client: Anthropic, model: str) -> ConnectionResult:
    """Send the smallest possible request to prove URL, key and model work together."""
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
    except APITimeoutError as error:
        return ConnectionFailed(ConnectionProblem.TIMEOUT, str(error))
    except APIConnectionError as error:
        return ConnectionFailed(ConnectionProblem.UNREACHABLE, str(error))
    except APIStatusError as error:
        return ConnectionFailed(problem_for_status(error.status_code), error.message)
    return ConnectionOk(model=response.model)
