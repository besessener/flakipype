# Connect a model

flakipype speaks the Anthropic Messages API only. It needs three values: a
base URL, an API key and a model. Which client it uses follows from the URL.

## Anthropic API

| Field | Value |
| --- | --- |
| Base URL | `https://api.anthropic.com` (default) |
| API key | a key from the Anthropic Console |
| Model | a model name, e.g. `claude-sonnet-4-5` |

## Azure AI Foundry

| Field | Value |
| --- | --- |
| Base URL | `https://<resource>.services.ai.azure.com/anthropic` |
| API key | the key of your Foundry resource |
| Model | the **deployment name** of your Claude deployment |

A host ending in `.services.ai.azure.com` switches flakipype to the SDK's
Foundry client automatically.

## A proxy or gateway

Any HTTPS URL that forwards the Anthropic Messages API works. Plain `http://`
is only accepted for `localhost`, `127.0.0.1` and `::1`, for a local gateway.

## Test it

In the wizard press **Test connection**, or run `flakipype doctor`. The test
sends one request with a single output token. Typical results:

| Result | Meaning |
| --- | --- |
| authentication | The key is wrong or belongs to another endpoint. |
| permission | The key may not use this model. |
| not found | Wrong model or deployment name, or wrong base URL path. |
| bad request | The endpoint rejected the request, usually the model name. |
| rate limited | Quota or rate limit reached; try again later. |
| unreachable / timeout | URL, proxy, DNS or firewall. |
