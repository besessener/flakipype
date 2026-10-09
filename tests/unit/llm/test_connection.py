import json

import httpx2
import pytest
from anthropic import Anthropic

from flakipype.llm.client import EndpointKind, LlmEndpoint, create_client, endpoint_kind
from flakipype.llm.connection import (
    ConnectionFailed,
    ConnectionOk,
    ConnectionProblem,
    check_connection,
)

ANTHROPIC = LlmEndpoint(base_url="https://api.anthropic.com", api_key="test-key", model="m-1")
FOUNDRY = LlmEndpoint(
    base_url="https://acme.services.ai.azure.com/anthropic", api_key="test-key", model="m-1"
)


def message_response(model: str) -> dict[str, object]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "p"}],
        "stop_reason": "max_tokens",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def error_response(status: int, message: str) -> httpx2.Response:
    body = {"type": "error", "error": {"type": "some_error", "message": message}}
    return httpx2.Response(status, json=body)


def client_answering(
    transport: httpx2.MockTransport, endpoint: LlmEndpoint = ANTHROPIC
) -> Anthropic:
    return create_client(endpoint, http_client=httpx2.Client(transport=transport), max_retries=0)


@pytest.mark.parametrize(
    ("base_url", "kind"),
    [
        ("https://api.anthropic.com", EndpointKind.ANTHROPIC),
        ("https://proxy.example.com/anthropic", EndpointKind.ANTHROPIC),
        ("https://acme.services.ai.azure.com/anthropic", EndpointKind.FOUNDRY),
        ("not a url", EndpointKind.ANTHROPIC),
    ],
)
def test_endpoint_kind_is_derived_from_the_host(base_url: str, kind: EndpointKind) -> None:
    assert endpoint_kind(base_url) is kind


def test_endpoint_repr_never_shows_the_key() -> None:
    assert "test-key" not in repr(ANTHROPIC)


@pytest.mark.parametrize("endpoint", [ANTHROPIC, FOUNDRY])
def test_working_endpoint_reports_the_model(endpoint: LlmEndpoint) -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=message_response("m-1-20260101"))

    result = check_connection(client_answering(httpx2.MockTransport(handler), endpoint), "m-1")

    assert result == ConnectionOk(model="m-1-20260101")
    sent = json.loads(requests[0].content)
    assert sent["model"] == "m-1"
    assert sent["max_tokens"] == 1
    assert str(requests[0].url).startswith(endpoint.base_url)
    assert requests[0].headers.get("x-api-key") == "test-key"


@pytest.mark.parametrize(
    ("status", "problem"),
    [
        (401, ConnectionProblem.AUTHENTICATION),
        (403, ConnectionProblem.PERMISSION),
        (404, ConnectionProblem.NOT_FOUND),
        (400, ConnectionProblem.BAD_REQUEST),
        (422, ConnectionProblem.BAD_REQUEST),
        (429, ConnectionProblem.RATE_LIMITED),
        (500, ConnectionProblem.SERVER_ERROR),
        (529, ConnectionProblem.SERVER_ERROR),
    ],
)
def test_http_errors_are_categorised(status: int, problem: ConnectionProblem) -> None:
    transport = httpx2.MockTransport(lambda _: error_response(status, "nope"))

    result = check_connection(client_answering(transport), "m-1")

    assert isinstance(result, ConnectionFailed)
    assert result.problem is problem
    assert "nope" in result.detail
    assert result.problem.next_step


def test_unreachable_endpoint() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    result = check_connection(client_answering(httpx2.MockTransport(handler)), "m-1")

    assert isinstance(result, ConnectionFailed)
    assert result.problem is ConnectionProblem.UNREACHABLE


def test_timeout() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("too slow", request=request)

    result = check_connection(client_answering(httpx2.MockTransport(handler)), "m-1")

    assert isinstance(result, ConnectionFailed)
    assert result.problem is ConnectionProblem.TIMEOUT


def test_every_problem_has_a_next_step() -> None:
    assert all(problem.next_step for problem in ConnectionProblem)
