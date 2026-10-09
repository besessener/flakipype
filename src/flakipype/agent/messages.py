"""Building blocks of Messages API conversations shared by the agent's tool loops."""

from typing import Any

from anthropic.types import Message


def content_blocks(response: Message) -> list[dict[str, Any]]:
    """The response's content as it goes back into the conversation."""
    return [block.model_dump(exclude_none=True) for block in response.content]


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
