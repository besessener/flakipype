"""Building blocks of Messages API conversations shared by the agent's tool loops."""

from dataclasses import dataclass
from typing import Any

from anthropic.types import Message
from anthropic.types.beta import BetaMessage

_THINKING = frozenset({"thinking", "redacted_thinking"})


@dataclass(frozen=True)
class ModelSettings:
    model: str
    max_tokens: int = 16_000
    # "adaptive", "enabled" (with thinking_budget) or "off".
    thinking: str = "adaptive"
    thinking_budget: int = 8_000

    def thinking_parameter(self) -> dict[str, Any]:
        if self.thinking == "adaptive":
            return {"thinking": {"type": "adaptive"}}
        if self.thinking == "enabled":
            return {"thinking": {"type": "enabled", "budget_tokens": self.thinking_budget}}
        return {}

    def request(
        self,
        *,
        system: str | list[dict[str, Any]],
        tools: list[dict[str, Any]],
        messages: list[Any],
    ) -> dict[str, Any]:
        """A Messages API request with this model, its token cap and its thinking."""
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "tools": tools,
            "messages": messages,
            **self.thinking_parameter(),
        }


def content_blocks(response: Message | BetaMessage) -> list[dict[str, Any]]:
    """The response's content as it goes back into the conversation."""
    return [block.model_dump(exclude_none=True) for block in response.content]


DECLINED = "The model declined to answer or gave an empty answer."


def declined(response: Message | BetaMessage) -> bool:
    """A refusal or an empty answer; kept in a conversation, it makes every later request fail."""
    return response.stop_reason == "refusal" or not response.content


def without_thinking(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The conversation without any thinking block; the API allows removing all, not some."""
    return [
        {**message, "content": [b for b in message["content"] if b.get("type") not in _THINKING]}
        if isinstance(message["content"], list)
        else message
        for message in messages
    ]


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
