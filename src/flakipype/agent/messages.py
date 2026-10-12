"""Building blocks of Messages API conversations shared by the agent's tool loops."""

from typing import Any

from anthropic.types import Message


def content_blocks(response: Message) -> list[dict[str, Any]]:
    """The response's content as it goes back into the conversation."""
    return [block.model_dump(exclude_none=True) for block in response.content]


DECLINED = "The model declined to answer or gave an empty answer."


def declined(response: Message) -> bool:
    """A refusal or an empty answer; kept in a conversation, it makes every later request fail."""
    return response.stop_reason == "refusal" or not response.content


def tool_result(tool_use_id: str, text: str, *, failed: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "tool_result", "tool_use_id": tool_use_id, "content": text}
    if failed:
        result["is_error"] = True
    return result


def cached_tools(definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tool definitions with a cache breakpoint after the last one; they rarely change."""
    return [*definitions[:-1], {**definitions[-1], "cache_control": {"type": "ephemeral"}}]


def cached_system(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def cached_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The conversation with one cache breakpoint on the newest message's last block.

    The stored history stays unmarked, so the breakpoint moves each turn instead of piling up;
    the API allows four, and the system prompt and tools take two.
    """
    *earlier, newest = messages
    content = newest["content"]
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
    marked = [*blocks[:-1], {**blocks[-1], "cache_control": {"type": "ephemeral"}}]
    return [*earlier, {**newest, "content": marked}]
