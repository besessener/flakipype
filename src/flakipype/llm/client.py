from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

import httpx2
from anthropic import Anthropic, AnthropicFoundry
from anthropic.types import Message
from anthropic.types.beta import BetaMessage

_FOUNDRY_HOST_SUFFIX = ".services.ai.azure.com"


class ClientSetupError(Exception):
    """The SDK client cannot be built for this endpoint in this environment."""


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


def create_client(
    endpoint: LlmEndpoint,
    *,
    http_client: httpx2.Client | None = None,
    max_retries: int = 2,
) -> Anthropic:
    if endpoint_kind(endpoint.base_url) is EndpointKind.FOUNDRY:
        try:
            return AnthropicFoundry(
                base_url=endpoint.base_url,
                api_key=endpoint.api_key,
                http_client=http_client,
                max_retries=max_retries,
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
    )


def create_message(client: Anthropic, request: Mapping[str, Any]) -> Message:
    """One model turn, streamed: the SDK refuses non-streaming calls with a large max_tokens."""
    with client.messages.stream(**request) as stream:
        return stream.get_final_message()


def create_beta_message(client: Anthropic, request: Mapping[str, Any]) -> BetaMessage:
    """create_message for requests that use beta features; the request names them in betas."""
    with client.beta.messages.stream(**request) as stream:
        return stream.get_final_message()
