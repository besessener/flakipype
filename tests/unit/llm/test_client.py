import json
from typing import Any

from support.fake_anthropic import ScriptedModel, call, message, text, thinking

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
