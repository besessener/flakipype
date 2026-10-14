from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from http import HTTPStatus
from typing import Any
from urllib.parse import urlsplit

import httpx2
from anthropic import DEFAULT_TIMEOUT, Anthropic, AnthropicFoundry, APIError, APIStatusError
from anthropic.types import Message
from anthropic.types.beta import BetaMessage

from flakipype.llm.connection import ConnectionProblem, problem_for_error

_FOUNDRY_HOST_SUFFIX = ".services.ai.azure.com"
_MAX_RETRIES = 2


class ClientSetupError(Exception):
    """The SDK client cannot be built for this endpoint in this environment."""


class ModelError(Exception):
    """A model call failed; the problem names the kind of failure and the user's next step."""

    def __init__(self, problem: ConnectionProblem, detail: str) -> None:
        super().__init__(f"{detail.rstrip('.')}. {problem.next_step}")
        self.problem = problem
        self.detail = detail


class EndpointKind(StrEnum):
    ANTHROPIC = "Anthropic API"
    FOUNDRY = "Azure AI Foundry"


@dataclass(frozen=True)
class LlmEndpoint:
    base_url: str
    api_key: str = field(repr=False)
    model: str


def endpoint_kind(base_url: str) -> EndpointKind:
    host = urlsplit(base_url).hostname or ""
    if host.endswith(_FOUNDRY_HOST_SUFFIX):
        return EndpointKind.FOUNDRY
    return EndpointKind.ANTHROPIC


def request_timeout(max_seconds: float) -> float:
    """Seconds a request may wait for data, so that it and the SDK's retries fit in max_seconds."""
    return max_seconds / (_MAX_RETRIES + 1)


def create_client(
    endpoint: LlmEndpoint,
    *,
    http_client: httpx2.Client | None = None,
    max_retries: int = _MAX_RETRIES,
    timeout: float | httpx2.Timeout = DEFAULT_TIMEOUT,
) -> Anthropic:
    if endpoint_kind(endpoint.base_url) is EndpointKind.FOUNDRY:
        try:
            return AnthropicFoundry(
                base_url=endpoint.base_url,
                api_key=endpoint.api_key,
                http_client=http_client,
                max_retries=max_retries,
                timeout=timeout,
            )
        # The SDK also reads ANTHROPIC_FOUNDRY_RESOURCE and refuses it next to a base URL.
        except ValueError as error:
            message = (
                "ANTHROPIC_FOUNDRY_RESOURCE is set in the environment and conflicts with "
                f"llm.base_url ({error}); unset it"
            )
            raise ClientSetupError(message) from error
    return Anthropic(
        base_url=endpoint.base_url,
        api_key=endpoint.api_key,
        http_client=http_client,
        max_retries=max_retries,
        timeout=timeout,
    )


@dataclass(frozen=True)
class ModelClient:
    """The only way to the model: every message is masked here, right before it is sent."""

    sdk: Anthropic
    # Replaces secrets in a text; the composition root binds it to the configured masker.
    mask: Callable[[str], str]

    def message(self, request: Mapping[str, Any]) -> Message:
        """One model turn, streamed: the SDK refuses non-streaming calls with a large max_tokens.

        Raises ModelError when the call fails.
        """
        masked = self._masked(request)

        def once() -> Message:
            with self.sdk.messages.stream(**masked) as stream:
                return stream.get_final_message()

        return _answer(once)

    def beta_message(self, request: Mapping[str, Any]) -> BetaMessage:
        """message for requests that use beta features; the request names them in betas."""
        masked = self._masked(request)

        def once() -> BetaMessage:
            with self.sdk.beta.messages.stream(**masked) as stream:
                return stream.get_final_message()

        return _answer(once)

    def _masked(self, request: Mapping[str, Any]) -> dict[str, Any]:
        messages = [
            {**message, "content": self._content(message["content"])}
            for message in request["messages"]
        ]
        return {**request, "messages": messages}

    def _content(self, content: str | list[dict[str, Any]]) -> str | list[dict[str, Any]]:
        if isinstance(content, str):
            return self.mask(content)
        return [self._block(block) for block in content]

    def _block(self, block: dict[str, Any]) -> dict[str, Any]:
        # Thinking blocks are signed and tool calls are the model's own; both go back unchanged.
        if block["type"] == "text":
            return {**block, "text": self.mask(block["text"])}
        if block["type"] == "tool_result":
            return {**block, "content": self._content(block["content"])}
        return block


def _answer[Answer](once: Callable[[], Answer]) -> Answer:
    try:
        return _retried_on_overload(once)
    except APIError as error:
        raise ModelError(problem_for_error(error), error.message) from error
    # The SDK wraps errors of the request, but not those of a stream it already returned.
    except httpx2.TimeoutException as error:
        raise ModelError(ConnectionProblem.TIMEOUT, f"The answer stopped: {error!r}") from error
    except httpx2.TransportError as error:
        raise ModelError(ConnectionProblem.UNREACHABLE, f"The answer broke: {error!r}") from error


def _retried_on_overload[Answer](once: Callable[[], Answer]) -> Answer:
    try:
        return once()
    except APIStatusError as error:
        # The SDK retries an overloaded answer, but not an overload that ends an open stream.
        if error.type != "overloaded_error" or error.status_code != HTTPStatus.OK:
            raise
    return once()
