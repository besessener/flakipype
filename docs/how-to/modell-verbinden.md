# Ein Modell verbinden

flakipype spricht die Anthropic Messages API oder eine OpenAI-kompatible
Chat Completions API. Es braucht vier Werte: die API (`llm.provider`, im
Assistenten das Feld **API**), eine Base URL, einen API-Key und ein Modell.
Mit der Anthropic API ergibt sich der Client aus der URL.

## Anthropic API

| Feld | Wert |
| --- | --- |
| Base URL | `https://api.anthropic.com` (Standard) |
| API key | ein Key aus der Anthropic Console |
| Model | ein Modellname, z. B. `claude-sonnet-4-5` |

## Azure AI Foundry

| Feld | Wert |
| --- | --- |
| Base URL | `https://<resource>.services.ai.azure.com/anthropic` |
| API key | der Key deiner Foundry-Ressource |
| Model | der **Deployment-Name** deines Claude-Deployments |

Ein Host, der auf `.services.ai.azure.com` endet, schaltet flakipype
automatisch auf den Foundry-Client des SDK um.

## Ein Proxy oder Gateway

Jede HTTPS-URL, die die Anthropic Messages API weiterleitet, funktioniert.
Einfaches `http://` wird nur für `localhost`, `127.0.0.1` und `::1`
akzeptiert, für ein lokales Gateway.

## Eine OpenAI-kompatible API

Wähl im Assistenten als **API** „OpenAI-compatible Chat Completions API“
oder gib headless `--provider openai` an. Die Base URL ist die vollständige
Basis bis einschließlich `/v1`; flakipype hängt `/chat/completions` selbst an.

| Feld | Wert |
| --- | --- |
| API | `openai` |
| Base URL | die OpenAI-kompatible Basis-URL, z. B. `https://api.openai.com/v1` |
| API key | der Key oder das Token des Endpunkts; er geht als `Authorization: Bearer` mit |
| Model | der Modellname, den der Endpunkt erwartet |

Das Modell muss **Tool Calling** können: Der Agent arbeitet nur mit
Werkzeugen. Der Test schickt deshalb ein Werkzeug mit, und ein Endpunkt, der
keine Werkzeuge annimmt, fällt schon dort mit `bad request` durch. Außerdem
muss der Endpunkt im Stream den Verbrauch melden (`stream_options.include_usage`),
sonst kann das Token-Budget nicht zählen und flakipype bricht die Anfrage mit
`unexpected answer` ab.

Was die Chat Completions API nicht kennt, fällt weg: Thinking (`agent.thinking`
und `agent.thinking_budget` gelten nur für die Anthropic API), Cache-Marken und
das serverseitige Leeren alter Werkzeugergebnisse im Chat. Lange Chats wachsen
deshalb, bis das Token-Budget pro Frage (`agent.max_tokens_per_investigation`)
oder das Kontextfenster des Modells sie beendet; fang dann mit `/new` neu an.
Manche Server (etwa vLLM) lehnen eine Anfrage ab, wenn Prompt und
`agent.max_output_tokens` zusammen nicht ins Kontextfenster passen; senk den
Wert dann.

### STACKIT AI Model Serving

| Feld | Wert |
| --- | --- |
| API | `openai` |
| Base URL | `https://api.openai-compat.model-serving.eu01.onstackit.cloud/v1` |
| API key | ein AI-Model-Serving-Auth-Token aus dem STACKIT Portal |
| Model | der Modellname aus der Liste der [Shared Models](https://docs.stackit.cloud/products/data-and-ai/ai-model-serving/basics/available-shared-models/) |

Nimm ein Modell, bei dem STACKIT „Tool calling“ als unterstützt angibt.
Headless sieht das so aus:

```bash
printf '%s' "$STACKIT_AI_TOKEN" | flakipype setup --non-interactive \
  --provider openai \
  --base-url https://api.openai-compat.model-serving.eu01.onstackit.cloud/v1 \
  --model <modellname> --owner octo-org --api-key-stdin
```

## Testen

Drück im Assistenten **Test connection** oder führe `flakipype doctor` aus.
Der Test sendet eine Anfrage mit einem einzigen Ausgabe-Token, bei einer
OpenAI-kompatiblen API zusammen mit einem Werkzeug. Typische Ergebnisse:

| Ergebnis | Bedeutung |
| --- | --- |
| authentication | Der Key ist falsch oder gehört zu einem anderen Endpunkt. |
| permission | Der Key darf dieses Modell nicht nutzen. |
| not found | Falscher Modell- oder Deployment-Name, falscher Pfad in der Base URL oder die falsche API. |
| bad request | Der Endpunkt hat die Anfrage abgelehnt, meist wegen des Modellnamens; bei einer OpenAI-kompatiblen API auch, weil das Modell kein Tool Calling kann. |
| rate limited | Kontingent oder Rate Limit erreicht; versuch es später erneut. |
| unreachable / timeout | URL, Proxy, DNS oder Firewall. |
| unexpected answer | Etwas hat geantwortet, aber nicht wie die gewählte API: oft eine Anmeldeseite, ein falscher Pfad in der Base URL oder die falsche API. |
| environment | `ANTHROPIC_FOUNDRY_RESOURCE` ist gesetzt und widerspricht der Base URL; entferne die Variable. |
