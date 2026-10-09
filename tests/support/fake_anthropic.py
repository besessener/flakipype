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
        return {block["tool_use_id"]: block for block in last if block.get("type") == "tool_result"}


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
