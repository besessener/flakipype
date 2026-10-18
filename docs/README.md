# flakipype-Dokumentation

Die Dokumentation folgt [Diátaxis](https://diataxis.fr/): Sie ist nach dem
geordnet, was du gerade brauchst.

|  | Zum Lernen | Für die Arbeit |
| --- | --- | --- |
| **Praxis** | [Tutorials](#tutorials) – Schritt für Schritt zum ersten Erfolg | [Anleitungen](#anleitungen) – ein konkretes Ziel erreichen |
| **Wissen** | [Hintergrund](#hintergrund) – verstehen, warum es so ist | [Referenz](#referenz) – nachschlagen, wie es genau ist |

## Tutorials

- [Erste Schritte](tutorials/erste-schritte.md) – installieren, einrichten, prüfen.
- [Demo an der Sandbox](tutorials/demo-sandbox.md) – scannen, untersuchen und einen Draft-PR öffnen, ohne ein echtes Projekt anzufassen.
- [Entwicklungsumgebung aufsetzen](tutorials/entwicklungsumgebung.md) – vom Klonen, bis alle Qualitätsprüfungen grün sind.

## Anleitungen

**flakipype benutzen**

- [Instabile Pipelines finden](how-to/instabile-pipelines-finden.md) – `flakipype scan`, Optionen, Skripte.
- [Befunde untersuchen](how-to/befunde-untersuchen.md) – sie vom Agenten mit Belegen erklären lassen.
- [Den Chat nutzen](how-to/chat-nutzen.md) – Fragen stellen, interaktiv scannen und untersuchen, Sitzungen.
- [Ein Modell verbinden](how-to/modell-verbinden.md) – Anthropic API, Azure AI Foundry, ein Proxy oder eine OpenAI-kompatible API wie STACKIT AI Model Serving.
- [Einen Rechner headless einrichten](how-to/headless-einrichten.md) – Server, Container, SSH.
- [Zeitgesteuert ausführen](how-to/zeitgesteuert-ausfuehren.md) – `flakipype run` und der systemd-Benutzer-Timer.

**flakipype entwickeln**

- [Mitmachen](../CONTRIBUTING.md) – einrichten, arbeiten, Pull Request öffnen, veröffentlichen.
- [CI lokal mit act ausführen](how-to/ci-lokal-ausfuehren.md) – die Linux-Prüfung unter Windows.
- [Webseite pflegen](how-to/webseite-pflegen.md) – `site/`, Screenshots und der Pages-Workflow.

## Referenz

- [Befehle](reference/befehle.md) – `poe`-Tasks und die `flakipype`-CLI.
- [Konfiguration](reference/konfiguration.md) – Dateien, Einstellungen, Secrets und `gh`.
- [Scan-JSON](reference/scan-json.md) – das Format von `flakipype scan --json`.
- [Qualitätsprüfungen](reference/qualitaetssicherung.md) – Tests, Linter, CI-Jobs und was jeder davon durchsetzt.

## Hintergrund

- [Architektur](explanation/architektur.md) – Pakete, Schichten und Datenfluss.
- [Wie Instabilität erkannt wird](explanation/flake-erkennung.md) – Signale, Raten und Fehlersignaturen.
- [Der Agent](explanation/agent.md) – Investigators, Reviewer, Werkzeuge, Urteile, Budgets und der Chat.
- [Aktionen](explanation/aktionen.md) – Reruns, Dispatches, Bestätigung und die Live-Ansicht der Läufe.
- [Korrekturen](explanation/korrekturen.md) – Fixer-Agent, Diff-Prüfungen, Draft-PRs und Verifikation.
- [Unbeaufsichtigte Läufe und Release](explanation/unbeaufsichtigte-laeufe.md) – `flakipype run`, der systemd-Timer, das Installationsskript und die Smoke-Tests.
- [Sicherheitsmodell](explanation/sicherheitsmodell.md) – Modi, Risikostufen, Pull Requests und Budgets.

Verwandte Projekte mit derselben Idee und demselben Aufbau der Dokumentation:
[PlayMonkey](https://github.com/besessener/PlayMonkey/blob/main/docs/README.md) und
[Archivist](https://github.com/besessener/Archivist/blob/main/docs/README.md).
