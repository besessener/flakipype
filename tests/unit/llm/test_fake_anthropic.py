from typing import Any

import pytest
from anthropic import BadRequestError

from support.fake_anthropic import ScriptedModel, call, message, text

ASK = {"role": "user", "content": "Hi"}
CALLED = {"role": "assistant", "content": [text("Looking."), call("t1", "scan", {})]}
RESULT = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": ""}]}


def send(model: ScriptedModel, messages: list[dict[str, Any]]) -> str:
    request = {"model": "m-1", "max_tokens": 10, "messages": messages}
    response = model.client().message(request)
    return "".join(block.text for block in response.content if block.type == "text")


@pytest.mark.parametrize(
    ("messages", "problem"),
    [
        ([ASK, {"role": "assistant", "content": []}, ASK], "non-empty content"),
        ([ASK, {"role": "assistant", "content": ""}, ASK], "non-empty content"),
        ([ASK, CALLED, ASK], "without tool_result blocks immediately after: t1"),
        ([ASK, CALLED, RESULT, CALLED, ASK], "without tool_result blocks"),
    ],
    ids=["empty blocks", "empty text", "unanswered tool call", "later unanswered tool call"],
)
def test_the_fake_rejects_what_the_api_rejects_and_keeps_its_turn(
    messages: list[dict[str, Any]], problem: str
) -> None:
    model = ScriptedModel([message(text("Hello."))])

    with pytest.raises(BadRequestError, match=problem):
        send(model, messages)

    assert send(model, [ASK]) == "Hello."
    assert len(model.requests) == 2


def test_the_fake_accepts_answered_tool_calls_and_a_prefill() -> None:
    model = ScriptedModel([message(text("Done.")), message(text("Sure."))])

    assert send(model, [ASK, CALLED, RESULT]) == "Done."
    assert send(model, [ASK, {"role": "assistant", "content": ""}]) == "Sure."
