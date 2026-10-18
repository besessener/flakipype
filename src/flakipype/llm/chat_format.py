"""Translation between Messages API requests and answers and the Chat Completions API.

The agent speaks the Messages API; for an OpenAI-compatible endpoint its requests are
translated here, and the answers come back as Messages API messages. Thinking, prompt
caching and beta features have no Chat Completions counterpart and are left out.
"""

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionChunk

_STOP_REASONS = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}


class UnreadableAnswerError(Exception):
    """The answer cannot be read as a model turn."""


def chat_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """The Chat Completions request for a Messages API request."""
    messages = [*_system(request.get("system")), *_conversation(request["messages"])]
    chat: dict[str, Any] = {
        "model": request["model"],
        "max_completion_tokens": request["max_tokens"],
        "messages": messages,
    }
    # Some endpoints reject an empty tool list.
    if request.get("tools"):
        chat["tools"] = [_tool(definition) for definition in request["tools"]]
    return chat


def _system(system: str | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not system:
        return []
    return [{"role": "system", "content": _text(system)}]


def _text(content: str | list[dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content
    return "\n\n".join(block["text"] for block in content if block.get("type") == "text")


def _tool(definition: Mapping[str, Any]) -> dict[str, Any]:
    function = {
        "name": definition["name"],
        "description": definition.get("description", ""),
        "parameters": definition["input_schema"],
    }
    return {"type": "function", "function": function}


def _conversation(messages: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for message in messages:
        if message["role"] == "assistant":
            yield from _assistant(message["content"])
        else:
            yield from _user(message["content"])


def _user(content: str | list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    if isinstance(content, str):
        yield {"role": "user", "content": content}
        return
    # Tool answers must directly follow the assistant turn that called the tools.
    for block in content:
        if block["type"] == "tool_result":
            yield _tool_answer(block)
    text = _text(content)
    if text:
        yield {"role": "user", "content": text}


def _tool_answer(block: Mapping[str, Any]) -> dict[str, Any]:
    text = _text(block.get("content", ""))
    # Chat Completions has no error flag on a tool answer.
    if block.get("is_error"):
        text = f"Error: {text}"
    return {"role": "tool", "tool_call_id": block["tool_use_id"], "content": text}


def _assistant(content: str | list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    if isinstance(content, str):
        yield {"role": "assistant", "content": content}
        return
    calls = [_call(block) for block in content if block["type"] == "tool_use"]
    text = _text(content)
    # A turn of only thinking has nothing to say in Chat Completions.
    if not calls and not text:
        return
    message: dict[str, Any] = {"role": "assistant", "content": text or None}
    if calls:
        message["tool_calls"] = calls
    yield message


def _call(block: Mapping[str, Any]) -> dict[str, Any]:
    function = {"name": block["name"], "arguments": json.dumps(block["input"])}
    return {"id": block["id"], "type": "function", "function": function}


@dataclass
class _Call:
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class _Answer:
    id: str = ""
    model: str = ""
    text: str = ""
    refusal: str = ""
    finish_reason: str = ""
    calls: dict[int, _Call] = field(default_factory=dict)
    usage: CompletionUsage | None = None


def message_fields(chunks: Iterable[ChatCompletionChunk]) -> dict[str, Any]:
    """The Messages API message for a streamed Chat Completions answer, as fields to validate.

    Raises UnreadableAnswerError for an answer without token usage or with tool arguments
    that are not a JSON object.
    """
    answer = _accumulated(chunks)
    content: list[dict[str, Any]] = []
    if answer.text:
        content.append({"type": "text", "text": answer.text})
    content.extend(_tool_use(call) for _, call in sorted(answer.calls.items()))
    return {
        "id": answer.id,
        "type": "message",
        "role": "assistant",
        "model": answer.model,
        "content": content,
        "stop_reason": _stop_reason(answer),
        "usage": _usage(answer.usage),
    }


def _accumulated(chunks: Iterable[ChatCompletionChunk]) -> _Answer:
    answer = _Answer()
    streamed = False
    for chunk in chunks:
        streamed = True
        answer.id = answer.id or chunk.id
        answer.model = answer.model or chunk.model
        answer.usage = chunk.usage or answer.usage
        for choice in chunk.choices[:1]:
            answer.finish_reason = choice.finish_reason or answer.finish_reason
            answer.text += choice.delta.content or ""
            answer.refusal += choice.delta.refusal or ""
            for delta in choice.delta.tool_calls or []:
                call = answer.calls.setdefault(delta.index, _Call())
                call.id = call.id or delta.id or ""
                if delta.function:
                    call.name += delta.function.name or ""
                    call.arguments += delta.function.arguments or ""
    if not streamed:
        message = "The answer is not a Chat Completions stream"
        raise UnreadableAnswerError(message)
    return answer


def _tool_use(call: _Call) -> dict[str, Any]:
    try:
        arguments = json.loads(call.arguments or "{}")
    except json.JSONDecodeError as error:
        message = f"The arguments of tool call {call.name!r} are not valid JSON"
        raise UnreadableAnswerError(message) from error
    if not isinstance(arguments, dict):
        message = f"The arguments of tool call {call.name!r} are not a JSON object"
        raise UnreadableAnswerError(message)
    return {"type": "tool_use", "id": call.id, "name": call.name, "input": arguments}


def _stop_reason(answer: _Answer) -> str:
    if answer.refusal:
        return "refusal"
    # Some servers end a turn with tool calls as "stop".
    if answer.calls:
        return "tool_use"
    return _STOP_REASONS.get(answer.finish_reason, "end_turn")


def _usage(usage: CompletionUsage | None) -> dict[str, int]:
    # Without it the token budget could not count the turn.
    if usage is None:
        message = "The answer reports no token usage"
        raise UnreadableAnswerError(message)
    details = usage.prompt_tokens_details
    cached = (details.cached_tokens if details else None) or 0
    written = (details.cache_write_tokens if details else None) or 0
    # Chat Completions counts cache hits and writes in the prompt tokens; the Messages API does not.
    return {
        "input_tokens": max(0, usage.prompt_tokens - cached - written),
        "output_tokens": usage.completion_tokens,
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": written,
    }
