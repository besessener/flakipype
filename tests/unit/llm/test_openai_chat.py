import json
from typing import Any

import httpx2
import pytest
from anthropic.types import TextBlock, ToolUseBlock

from flakipype.llm.connection import ConnectionFailed, ConnectionOk, ConnectionProblem, ModelError

from support.fake_openai import BASE_URL, Answer, Dropped, Raw, ScriptedChat, call

SECRET = "super-secret-value"  # noqa: S105 - a fake secret the client must mask
MASKED = "[masked: configured secret]"
TOOL = {"name": "scan", "description": "Scans.", "input_schema": {"type": "object"}}


def request(*messages: dict[str, Any], **extra: Any) -> dict[str, Any]:
    conversation = list(messages) or [{"role": "user", "content": "Hi"}]
    return {"model": "qwen-1", "max_tokens": 100, "messages": conversation, **extra}


def function(name: str, arguments: str) -> dict[str, str]:
    return {"name": name, "arguments": arguments}


def test_a_turn_is_sent_to_chat_completions_with_the_key_and_streamed() -> None:
    model = ScriptedChat([Answer(text="Hello.")])

    model.client().message(request())

    assert model.urls == [f"{BASE_URL}/chat/completions"]
    assert model.headers[0]["authorization"] == "Bearer test-key"
    sent = model.requests[0]
    assert sent["model"] == "qwen-1"
    assert sent["max_completion_tokens"] == 100
    assert sent["stream"] is True
    assert sent["stream_options"] == {"include_usage": True}


def test_the_answer_comes_back_as_a_messages_api_turn() -> None:
    usage = {"prompt_tokens": 900, "completion_tokens": 40, "total_tokens": 940}
    turn = Answer(
        text="Reading it.", calls=[call("chatcmpl-tool-1", "scan", {"days": 3})], usage=usage
    )
    model = ScriptedChat([turn])

    answer = model.client().message(request(tools=[TOOL]))

    assert answer.content == [
        TextBlock(type="text", text="Reading it."),
        ToolUseBlock(type="tool_use", id="chatcmpl-tool-1", name="scan", input={"days": 3}),
    ]
    assert answer.stop_reason == "tool_use"
    assert (answer.usage.input_tokens, answer.usage.output_tokens) == (900, 40)
    assert answer.model == "qwen-1"


def test_cached_prompt_tokens_are_counted_once() -> None:
    details = {"cached_tokens": 600, "cache_write_tokens": 100}
    usage = {"prompt_tokens": 1_000, "completion_tokens": 5, "prompt_tokens_details": details}
    model = ScriptedChat([Answer(text="Ok.", usage=usage)])

    answer = model.client().message(request())

    assert answer.usage.input_tokens == 300
    assert answer.usage.cache_read_input_tokens == 600
    assert answer.usage.cache_creation_input_tokens == 100


def test_the_whole_conversation_is_translated_and_masked() -> None:
    model = ScriptedChat([Answer(text="Done.")])
    conversation = request(
        {"role": "user", "content": f"Why? {SECRET}"},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "hmm", "signature": "sig"},
                {"type": "text", "text": f"Look at {SECRET}"},
                {"type": "tool_use", "id": "t1", "name": "scan", "input": {"days": 3}},
                {"type": "tool_use", "id": "t2", "name": "scan", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": f"log {SECRET}"},
                {
                    "type": "tool_result",
                    "tool_use_id": "t2",
                    "content": [{"type": "text", "text": "no such run"}],
                    "is_error": True,
                },
                {"type": "text", "text": "Go on.", "cache_control": {"type": "ephemeral"}},
            ],
        },
        system=[
            {"type": "text", "text": "You investigate.", "cache_control": {"type": "ephemeral"}}
        ],
        tools=[{**TOOL, "cache_control": {"type": "ephemeral"}}],
        thinking={"type": "adaptive"},
    )

    model.client(SECRET).message(conversation)

    sent = model.requests[0]
    assert sent["messages"] == [
        {"role": "system", "content": "You investigate."},
        {"role": "user", "content": f"Why? {MASKED}"},
        {
            "role": "assistant",
            "content": f"Look at {MASKED}",
            "tool_calls": [
                {"id": "t1", "type": "function", "function": function("scan", '{"days": 3}')},
                {"id": "t2", "type": "function", "function": function("scan", "{}")},
            ],
        },
        {"role": "tool", "tool_call_id": "t1", "content": f"log {MASKED}"},
        {"role": "tool", "tool_call_id": "t2", "content": "Error: no such run"},
        {"role": "user", "content": "Go on."},
    ]  # fmt: skip
    scan = {"name": "scan", "description": "Scans.", "parameters": {"type": "object"}}
    assert sent["tools"] == [{"type": "function", "function": scan}]
    assert "thinking" not in sent
    assert SECRET not in json.dumps(sent)


def test_plain_text_turns_stay_plain_text() -> None:
    model = ScriptedChat([Answer(text="Done.")])
    earlier = {"role": "assistant", "content": [{"type": "text", "text": "Scanning."}]}

    model.client().message(
        request(
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello."},
            {"role": "user", "content": "Scan."},
            earlier,
            {"role": "user", "content": "And?"},
        )
    )

    assert model.requests[0]["messages"][1:4] == [
        {"role": "assistant", "content": "Hello."},
        {"role": "user", "content": "Scan."},
        {"role": "assistant", "content": "Scanning."},
    ]


def test_a_turn_of_only_thinking_and_an_empty_tool_list_are_left_out() -> None:
    model = ScriptedChat([Answer(text="Done.")])
    thought = {
        "role": "assistant",
        "content": [{"type": "thinking", "thinking": "hmm", "signature": "s"}],
    }

    model.client().message(request({"role": "user", "content": "Hi"}, thought, tools=[]))

    assert model.requests[0]["messages"] == [{"role": "user", "content": "Hi"}]
    assert "tools" not in model.requests[0]


def test_a_beta_request_loses_its_beta_features() -> None:
    model = ScriptedChat([Answer(text="Hello.")])
    beta = request(betas=["context-management-2025-06-27"], context_management={"edits": []})

    answer = model.client().beta_message(beta)

    assert [block.text for block in answer.content if block.type == "text"] == ["Hello."]
    assert "betas" not in model.requests[0]
    assert "context_management" not in model.requests[0]


@pytest.mark.parametrize(
    ("turn", "stop_reason"),
    [
        (Answer(text="Done."), "end_turn"),
        (Answer(text="Done", finish_reason="length"), "max_tokens"),
        (Answer(finish_reason="content_filter"), "refusal"),
        (Answer(refusal="I will not."), "refusal"),
        (Answer(calls=[call("c1", "scan", {})], finish_reason="stop"), "tool_use"),
    ],
    ids=["stop", "length", "content filter", "refusal", "tool calls ended as stop"],
)
def test_how_an_answer_ends_becomes_its_stop_reason(turn: Answer, stop_reason: str) -> None:
    model = ScriptedChat([turn])

    assert model.client().message(request()).stop_reason == stop_reason


@pytest.mark.parametrize(
    ("turn", "detail"),
    [
        (Answer(text="Hello.", usage=None), "no token usage"),
        (Answer(calls=[("c1", "scan", '{"days": ')]), "not valid JSON"),
        (Answer(calls=[("c1", "scan", "[1, 2]")]), "not a JSON object"),
        (Raw("<html>Sign in</html>"), "is not a Chat Completions stream"),
        (Raw('data: {"status": "ok"}\n\n', "text/event-stream"), "does not read as"),
    ],
    ids=["no usage", "broken arguments", "arguments not an object", "sign-in page", "other API"],
)
def test_an_answer_that_cannot_be_read_is_unexpected(turn: Answer | Raw, detail: str) -> None:
    model = ScriptedChat([turn])

    with pytest.raises(ModelError) as raised:
        model.client().message(request())

    assert raised.value.problem is ConnectionProblem.UNEXPECTED_ANSWER
    assert detail in raised.value.detail


@pytest.mark.parametrize(
    ("turn", "problem"),
    [
        (401, ConnectionProblem.AUTHENTICATION),
        (404, ConnectionProblem.NOT_FOUND),
        (429, ConnectionProblem.RATE_LIMITED),
        (503, ConnectionProblem.SERVER_ERROR),
        (Dropped(httpx2.ReadTimeout("read timed out")), ConnectionProblem.TIMEOUT),
        (Dropped(httpx2.RemoteProtocolError("peer closed")), ConnectionProblem.UNREACHABLE),
    ],
    ids=["key", "model", "rate limit", "server", "stalled stream", "dropped stream"],
)
def test_failures_become_model_errors_with_a_next_step(
    turn: int | Dropped, problem: ConnectionProblem
) -> None:
    model = ScriptedChat([turn])

    with pytest.raises(ModelError) as raised:
        model.client().message(request())

    assert raised.value.problem is problem
    assert str(raised.value).endswith(f". {problem.next_step}")


def test_the_connection_check_names_the_model_and_asks_for_tool_calling() -> None:
    model = ScriptedChat([Answer(text="p")])

    result = model.api().check("qwen-1")

    assert result == ConnectionOk(model="qwen-1")
    sent = model.requests[0]
    assert sent["max_completion_tokens"] == 1
    assert [tool["function"]["name"] for tool in sent["tools"]] == ["ping"]
    assert "stream" not in sent


@pytest.mark.parametrize(
    ("turn", "problem"),
    [
        (400, ConnectionProblem.BAD_REQUEST),
        (401, ConnectionProblem.AUTHENTICATION),
        (Raw("<html>Sign in</html>"), ConnectionProblem.UNEXPECTED_ANSWER),
    ],
    ids=["no tool calling", "key", "sign-in page"],
)
def test_a_failed_connection_check_names_the_problem(
    turn: int | Raw, problem: ConnectionProblem
) -> None:
    result = ScriptedChat([turn]).api().check("qwen-1")

    assert isinstance(result, ConnectionFailed)
    assert result.problem is problem
