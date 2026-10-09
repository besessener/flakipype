from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlsplit

import httpx2
from anthropic import Anthropic, AnthropicFoundry

_FOUNDRY_HOST_SUFFIX = ".services.ai.azure.com"


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
        return AnthropicFoundry(
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
            http_client=http_client,
            max_retries=max_retries,
        )
    return Anthropic(
        base_url=endpoint.base_url,
        api_key=endpoint.api_key,
        http_client=http_client,
        max_retries=max_retries,
    )
