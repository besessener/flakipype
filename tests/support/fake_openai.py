"""A scripted stand-in for an OpenAI-compatible Chat Completions API, streamed like vLLM."""

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx2

from flakipype.agent.masking import Masker
from flakipype.config.settings import LlmProvider
from flakipype.llm.client import LlmEndpoint, ModelApi, ModelClient, create_model_api

BASE_URL = "https://api.openai-compat.model-serving.eu01.onstackit.cloud/v1"
USAGE = {"prompt_tokens": 1_000, "completion_tokens": 200, "total_tokens": 1_200}


@dataclass(frozen=True)
class Answer:
    """One streamed answer: text, tool calls as (id, name, arguments), and how it ends."""

    text: str = ""
    calls: Sequence[tuple[str, str, str]] = ()
    finish_reason: str = ""
    refusal: str = ""
    usage: dict[str, Any] | None = field(default_factory=lambda: dict(USAGE))


def call(call_id: str, name: str, arguments: dict[str, Any]) -> tuple[str, str, str]:
    return call_id, name, json.dumps(arguments)


@dataclass(frozen=True)
class Dropped:
    """An answer that starts streaming, then breaks with this transport error."""

    error: httpx2.TransportError


@dataclass(frozen=True)
class Raw:
    """An answer that is not what the API sends, such as a sign-in page."""

    body: str
    content_type: str = "text/html"


@dataclass
class ScriptedChat:
    """Each turn is an Answer, an int HTTP status to fail that request with, Dropped, or Raw."""

    script: Sequence[Answer | int | Dropped | Raw]
    requests: list[dict[str, Any]] = field(default_factory=list)
    headers: list[dict[str, str]] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.turns = list(self.script)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.urls.append(str(request.url))
        self.requests.append(json.loads(request.content))
        self.headers.append(dict(request.headers))
        problem = invalid_history(self.requests[-1]["messages"])
        if problem:
            return _error(400, problem)
        if not self.turns:
            return _error(500, "script ended")
        return _response(self.turns.pop(0), streamed=bool(self.requests[-1].get("stream")))

    def api(self) -> ModelApi:
        endpoint = LlmEndpoint(BASE_URL, "test-key", "qwen-1", LlmProvider.OPENAI)
        transport = httpx2.MockTransport(self._handle)
        return create_model_api(
            endpoint, http_client=httpx2.Client(transport=transport), max_retries=0
        )

    def client(self, *secrets: str) -> ModelClient:
        """A client that masks like the real one, plus the given known secrets."""
        return ModelClient(self.api(), Masker.with_secrets(secrets).mask)


class _FailingStream(httpx2.SyncByteStream):
    def __init__(self, start: bytes, error: httpx2.TransportError) -> None:
        self._start = start
        self._error = error

    def __iter__(self) -> Iterator[bytes]:
        yield self._start
        raise self._error


def _response(turn: Answer | int | Dropped | Raw, *, streamed: bool) -> httpx2.Response:
    if isinstance(turn, int):
        return _error(turn, f"status {turn}")
    if isinstance(turn, Raw):
        return httpx2.Response(200, headers={"content-type": turn.content_type}, text=turn.body)
    headers = {"content-type": "text/event-stream"}
    if isinstance(turn, Dropped):
        start = _sse(_chunk({"role": "assistant", "content": "I"}))
        return httpx2.Response(200, headers=headers, stream=_FailingStream(start, turn.error))
    if not streamed:
        return httpx2.Response(200, json=_completion(turn))
    return httpx2.Response(200, headers=headers, content=_events(turn))


def _error(status: int, message: str) -> httpx2.Response:
    body = {"error": {"message": message, "type": "BadRequestError", "code": status}}
    return httpx2.Response(status, json=body)


def _chunk(delta: dict[str, Any], finish_reason: str | None = None) -> dict[str, Any]:
    # vLLM sends nulls for the fields it does not use.
    choice = {"index": 0, "delta": delta, "logprobs": None, "finish_reason": finish_reason}
    return {**_head("chat.completion.chunk"), "choices": [choice], "usage": None}


def _head(kind: str) -> dict[str, Any]:
    return {"id": "chatcmpl-1", "object": kind, "created": 1_760_000_000, "model": "qwen-1"}


def _events(turn: Answer) -> bytes:
    """The answer as vLLM streams it: role, text, tool calls in parts, the end, the usage."""
    chunks = [_chunk({"role": "assistant", "content": "", "reasoning_content": None})]
    if turn.text:
        chunks += [_chunk({"content": part}) for part in _halves(turn.text)]
    if turn.refusal:
        chunks.append(_chunk({"refusal": turn.refusal}))
    for index, (call_id, name, arguments) in enumerate(turn.calls):
        first, rest = _halves(arguments)
        parts = [
            {"index": index, "id": call_id, "type": "function"},
            {"index": index, "function": {"name": name, "arguments": first}},
            {"index": index, "function": {"arguments": rest}},
        ]
        chunks += [_chunk({"tool_calls": [part]}) for part in parts]
    finish = turn.finish_reason or ("tool_calls" if turn.calls else "stop")
    chunks.append(_chunk({}, finish))
    if turn.usage is not None:
        chunks.append({**_head("chat.completion.chunk"), "choices": [], "usage": turn.usage})
    return b"".join(_sse(chunk) for chunk in chunks) + b"data: [DONE]\n\n"


def _completion(turn: Answer) -> dict[str, Any]:
    message = {"role": "assistant", "content": turn.text or None, "tool_calls": []}
    choice = {"index": 0, "message": message, "finish_reason": turn.finish_reason or "stop"}
    return {**_head("chat.completion"), "choices": [choice], "usage": turn.usage}


def _halves(value: str) -> tuple[str, str]:
    middle = len(value) // 2
    return value[:middle], value[middle:]


def _sse(chunk: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(chunk)}\n\n".encode()


def invalid_history(messages: list[dict[str, Any]]) -> str:
    """Why the real API would reject these messages with a 400, or "" when it accepts them."""
    for index, entry in enumerate(messages):
        if entry["role"] != "assistant":
            continue
        called = [call["id"] for call in entry.get("tool_calls", [])]
        following = messages[index + 1 : index + 1 + len(called)]
        answered = [str(message.get("tool_call_id")) for message in following]
        if sorted(called) != sorted(answered):
            return f"messages.{index}: tool calls without tool messages right after: {called}"
    return ""
