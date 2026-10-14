import json
from typing import Any

import httpx2
import pytest
from anthropic import APIResponseValidationError

from flakipype.llm.client import ModelError, request_timeout
from flakipype.llm.connection import ConnectionProblem, problem_for_error

from support.fake_anthropic import Broken, ScriptedModel, call, message, text, thinking

HI = {"model": "m-1", "max_tokens": 10, "messages": [{"role": "user", "content": "Hi"}]}

SECRET = "super-secret-value"  # noqa: S105 - a fake secret the client must mask
MASKED = "[masked: configured secret]"


def conversation() -> list[dict[str, Any]]:
    """Every shape a message takes in flakipype, each carrying the secret."""
    return [
        {"role": "user", "content": f"Why? {SECRET}"},
        {
            "role": "assistant",
            "content": [
                thinking(f"maybe {SECRET}"),
                text(f"Look at {SECRET}"),
                call("t1", "scan", {"note": SECRET}),
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": f"log {SECRET}"},
                {"type": "tool_result", "tool_use_id": "t2", "content": [text(f"x {SECRET}")]},
                {**text(f"and {SECRET}"), "cache_control": {"type": "ephemeral"}},
            ],
        },
    ]


def test_every_text_and_tool_result_is_masked_before_it_is_sent() -> None:
    model = ScriptedModel([message(text("Done.")), message(text("Done."))])
    request = {"model": "m-1", "max_tokens": 10, "messages": conversation()}

    model.client(SECRET).message(request)
    model.client(SECRET).beta_message(request)

    for sent in model.requests:
        user, assistant, results = sent["messages"]
        assert user["content"] == f"Why? {MASKED}"
        assert assistant["content"][1]["text"] == f"Look at {MASKED}"
        assert [block.get("content") for block in results["content"]] == [
            f"log {MASKED}", [text(f"x {MASKED}")], None
        ]  # fmt: skip
        assert results["content"][2] == {
            **text(f"and {MASKED}"), "cache_control": {"type": "ephemeral"}
        }  # fmt: skip
        # Signed thinking and the model's own tool calls go back exactly as they came.
        assert assistant["content"][0] == thinking(f"maybe {SECRET}")
        assert assistant["content"][2]["input"] == {"note": SECRET}
        assert json.dumps(sent).count(SECRET) == 2
    assert request["messages"] == conversation()


@pytest.mark.parametrize(
    ("turn", "problem"),
    [
        (401, ConnectionProblem.AUTHENTICATION),
        (529, ConnectionProblem.SERVER_ERROR),
        (Broken("invalid_request_error"), ConnectionProblem.SERVER_ERROR),
        (Broken(httpx2.ReadTimeout("read timed out")), ConnectionProblem.TIMEOUT),
        (Broken(httpx2.RemoteProtocolError("peer closed")), ConnectionProblem.UNREACHABLE),
    ],
    ids=["status", "overloaded status", "error event", "stalled stream", "dropped stream"],
)
def test_failures_become_model_errors_with_a_next_step(
    turn: int | Broken, problem: ConnectionProblem
) -> None:
    model = ScriptedModel([turn])

    with pytest.raises(ModelError) as raised:
        model.client().message(HI)

    assert raised.value.problem is problem
    assert str(raised.value).endswith(f". {problem.next_step}")
    assert raised.value.detail in str(raised.value)
    # The SDK already retried an overloaded status; only an overload in an open stream is retried.
    assert len(model.requests) == 1


def test_an_overload_in_an_open_stream_is_tried_once_more() -> None:
    model = ScriptedModel([Broken("overloaded_error"), message(text("Hello."))])

    answer = model.client().beta_message(HI)

    assert [block.text for block in answer.content if block.type == "text"] == ["Hello."]
    assert len(model.requests) == 2


def test_a_second_overload_in_an_open_stream_is_a_server_error() -> None:
    model = ScriptedModel([Broken("overloaded_error"), Broken("overloaded_error")])

    with pytest.raises(ModelError) as raised:
        model.client().message(HI)

    assert raised.value.problem is ConnectionProblem.SERVER_ERROR
    assert len(model.requests) == 2


def test_an_answer_the_sdk_cannot_read_is_unexpected() -> None:
    response = httpx2.Response(200, request=httpx2.Request("POST", "https://api.anthropic.com"))

    error = APIResponseValidationError(response, body=None)

    assert problem_for_error(error) is ConnectionProblem.UNEXPECTED_ANSWER


def test_a_request_and_both_retries_fit_in_the_time_limit() -> None:
    assert request_timeout(300) == 100
