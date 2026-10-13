# Ein Modell verbinden

flakipype spricht nur die Anthropic Messages API. Es braucht drei Werte: eine
Base URL, einen API-Key und ein Modell. Welchen Client es nutzt, ergibt sich
aus der URL.

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

## Testen

Drück im Assistenten **Test connection** oder führe `flakipype doctor` aus.
Der Test sendet eine Anfrage mit einem einzigen Ausgabe-Token. Typische
Ergebnisse:

| Ergebnis | Bedeutung |
| --- | --- |
| authentication | Der Key ist falsch oder gehört zu einem anderen Endpunkt. |
| permission | Der Key darf dieses Modell nicht nutzen. |
| not found | Falscher Modell- oder Deployment-Name oder falscher Pfad in der Base URL. |
| bad request | Der Endpunkt hat die Anfrage abgelehnt, meist wegen des Modellnamens. |
| rate limited | Kontingent oder Rate Limit erreicht; versuch es später erneut. |
| unreachable / timeout | URL, Proxy, DNS oder Firewall. |
| unexpected answer | Etwas hat geantwortet, aber nicht wie die Messages API: oft eine Anmeldeseite oder ein falscher Pfad in der Base URL. |
| environment | `ANTHROPIC_FOUNDRY_RESOURCE` ist gesetzt und widerspricht der Base URL; entferne die Variable. |
