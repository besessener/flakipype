"""A scripted stand-in for the Anthropic Messages API: answers turn by turn, records requests."""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx2
from anthropic import Anthropic

from flakipype.llm.client import LlmEndpoint, create_client

USAGE = {"input_tokens": 1_000, "output_tokens": 200}


def message(*content: dict[str, Any], usage: dict[str, int] | None = None) -> dict[str, Any]:
    has_tool = any(block["type"] == "tool_use" for block in content)
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "m-1",
        "content": list(content),
        "stop_reason": "tool_use" if has_tool else "end_turn",
        "stop_sequence": None,
        "usage": usage or USAGE,
    }


def call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": arguments}


def text(content: str) -> dict[str, Any]:
    return {"type": "text", "text": content}


def thinking(content: str) -> dict[str, Any]:
    return {"type": "thinking", "thinking": content, "signature": "sig"}


@dataclass
class ScriptedModel:
    """Each turn is a message dict, or an int HTTP status to fail that request with."""

    turns: list[dict[str, Any] | int]
    requests: list[dict[str, Any]] = field(default_factory=list)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        if not self.turns:
            return httpx2.Response(
                500,
                json={"type": "error", "error": {"type": "api_error", "message": "script ended"}},
            )
        turn = self.turns.pop(0)
        if isinstance(turn, int):
            body = {"type": "error", "error": {"type": "api_error", "message": f"status {turn}"}}
            return httpx2.Response(turn, json=body)
        if self.requests[-1].get("stream"):
            return httpx2.Response(
                200, headers={"content-type": "text/event-stream"}, content=_events(turn)
            )
        return httpx2.Response(200, json=turn)

    def client(self) -> Anthropic:
        endpoint = LlmEndpoint("https://api.anthropic.com", "test-key", "m-1")
        transport = httpx2.MockTransport(self._handle)
        return create_client(
            endpoint, http_client=httpx2.Client(transport=transport), max_retries=0
        )

    def tool_results(self, request_index: int) -> dict[str, dict[str, Any]]:
        """tool_result blocks of the last user message of one request, by tool_use_id."""
        last = self.requests[request_index]["messages"][-1]["content"]
        return {
            block["tool_use_id"]: {
                key: value for key, value in block.items() if key != "cache_control"
            }
            for block in last
            if block.get("type") == "tool_result"
        }

    def message_text(self, request_index: int, message_index: int) -> str:
        """The text of one message of one request, whether sent as a string or as blocks."""
        content = self.requests[request_index]["messages"][message_index]["content"]
        if isinstance(content, str):
            return content
        return "".join(block.get("text", "") for block in content)

    def breakpoints(self, request_index: int) -> list[str]:
        """Where one request set cache breakpoints: "tools", "system" or "message <index>"."""
        request = self.requests[request_index]
        found = [
            name
            for name in ("tools", "system")
            for block in request.get(name, [])
            if "cache_control" in block
        ]
        for index, entry in enumerate(request["messages"]):
            content = entry["content"]
            blocks = [] if isinstance(content, str) else content
            found += [f"message {index}" for block in blocks if "cache_control" in block]
        return found


def _events(turn: dict[str, Any]) -> bytes:
    """The message as the server-sent events of a streamed answer."""
    events: list[dict[str, Any]] = [
        {"type": "message_start", "message": {**turn, "content": [], "stop_reason": None}}
    ]
    for index, block in enumerate(turn["content"]):
        start, deltas = _streamed(block)
        events.append({"type": "content_block_start", "index": index, "content_block": start})
        events += [{"type": "content_block_delta", "index": index, "delta": d} for d in deltas]
        events.append({"type": "content_block_stop", "index": index})
    delta = {"stop_reason": turn["stop_reason"], "stop_sequence": None}
    events.append({"type": "message_delta", "delta": delta, "usage": turn["usage"]})
    events.append({"type": "message_stop"})
    lines = [f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events]
    return "".join(lines).encode()


def _streamed(block: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A content block's start event and the deltas that complete it, as the API sends them."""
    if block["type"] == "text":
        return {**block, "text": ""}, [{"type": "text_delta", "text": block["text"]}]
    if block["type"] == "tool_use":
        partial = {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
        return {**block, "input": {}}, [partial]
    if block["type"] == "thinking":
        return {**block, "thinking": "", "signature": ""}, [
            {"type": "thinking_delta", "thinking": block["thinking"]},
            {"type": "signature_delta", "signature": block["signature"]},
        ]
    return block, []


def verdict_input(
    quote: str, tool_call_id: str, *, classification: str = "flaky_test", confidence: str = "high"
) -> dict[str, Any]:
    return {
        "classification": classification,
        "confidence": confidence,
        "summary": "The E2E test waits on a fixed timeout.",
        "cause": "A race between rendering and the assertion.",
        "evidence": [
            {
                "kind": "log",
                "tool_call_id": tool_call_id,
                "location": "job 11",
                "quote": quote,
                "why_it_matters": "the wait timed out",
            }
        ],
        "suggested_fix": "Wait for the row count instead of a fixed time.",
    }


def review_input(decision: str, **extra: Any) -> dict[str, Any]:
    return {"decision": decision, "reason": "checked", **extra}
