# flakipype

![Python](https://img.shields.io/badge/python-%3E%3D3.12-3776AB?logo=python&logoColor=white)
![uv](https://img.shields.io/badge/packaging-uv-DE5FE9?logo=uv&logoColor=white)
![Textual](https://img.shields.io/badge/TUI-Textual-5a4fcf)
![Typer](https://img.shields.io/badge/CLI-Typer-009688)
![Pydantic](https://img.shields.io/badge/validation-Pydantic-E92063?logo=pydantic&logoColor=white)
![Anthropic](https://img.shields.io/badge/LLM-Anthropic%20Messages%20API-191919?logo=anthropic&logoColor=white)
![gh](https://img.shields.io/badge/GitHub-gh%20CLI-181717?logo=github&logoColor=white)
![Ruff](https://img.shields.io/badge/lint-Ruff-D7FF64?logo=ruff&logoColor=black)
![ty](https://img.shields.io/badge/types-ty-261230)
![import-linter](https://img.shields.io/badge/architecture-import--linter-orange)
![pytest](https://img.shields.io/badge/tested%20with-pytest-0A9EDC?logo=pytest&logoColor=white)
![Gitleaks](https://img.shields.io/badge/secrets-Gitleaks-blue?logo=git&logoColor=white)
![zizmor](https://img.shields.io/badge/workflow%20security-zizmor-blue?logo=githubactions&logoColor=white)
[![CI](https://github.com/besessener/flakipype/actions/workflows/ci.yml/badge.svg)](https://github.com/besessener/flakipype/actions/workflows/ci.yml)
[![CodeQL](https://github.com/besessener/flakipype/actions/workflows/codeql.yml/badge.svg)](https://github.com/besessener/flakipype/actions/workflows/codeql.yml)
[![Last commit](https://img.shields.io/github/last-commit/besessener/flakipype)](https://github.com/besessener/flakipype/commits/main)
[![License: MIT](https://img.shields.io/github/license/besessener/flakipype)](LICENSE)

***Instabile GitHub-Actions-Pipelines finden, erklären und beheben.***

flakipype ist ein agentisches Kommandozeilenwerkzeug für Linux. Richte es auf
einen GitHub-Benutzer oder eine Organisation, und es durchsucht die
Workflow-Läufe, bewertet, wie instabil jeder Workflow, Job und Schritt ist,
erklärt die wahrscheinliche Ursache mit einem Anthropic-Modell und behebt sie
per Pull Request – überprüft durch erneutes Ausführen des Fix-Branches, bevor
du ihn reviewst.

- **Findet instabile Jobs** – bringt Jobs, die fehlschlugen und dann beim
  Rerun oder auf demselben Commit durchliefen, in eine Rangfolge, mit
  Fehlersignaturen, die gleichartige Fehlschläge gruppieren.
- **Erklärt sie mit Belegen** – ein Agent liest Logs, Commits und Dateien und
  zitiert sie; ein Reviewer prüft das Urteil, bevor du es siehst.
- **Chat oder Timer** – eine reichhaltige Terminal-Oberfläche mit
  Slash-Befehlen (`/scan`, `/flaky`, `/fix`, …) oder headless Befehle und ein
  systemd-Timer für unbeaufsichtigte Läufe.
- **Sicher von Grund auf** – fasst den Standardbranch nie an; jede Korrektur
  ist ein Draft-PR
  ([Sicherheitsmodell](docs/explanation/sicherheitsmodell.md)).

> **Stand:** Version 0.2.0. Einrichtung, Scannen, Untersuchungen durch den
> Agenten, der Chat, bestätigte Reruns und Dispatches, Korrekturen als
> Draft-PRs und unbeaufsichtigte Läufe per systemd-Timer funktionieren.

## Installation

Voraussetzungen: Linux (x86_64 oder aarch64, glibc) mit `curl`, `tar` und
`git`. Das Skript installiert [uv](https://docs.astral.sh/uv/), falls du es
noch nicht hast, geprüft gegen dessen veröffentlichte SHA-256-Prüfsumme, und
danach flakipype für deinen Benutzer:

```bash
curl -fsSLO https://raw.githubusercontent.com/besessener/flakipype/v0.2.0/install.sh
sh install.sh
```

Mit bereits installiertem uv: `uv tool install git+https://github.com/besessener/flakipype@v0.2.0`.
Schritt für Schritt: [Erste Schritte](docs/tutorials/erste-schritte.md).
Releases und Änderungen: [GitHub Releases](https://github.com/besessener/flakipype/releases).

## Benutzung

```bash
flakipype setup     # model endpoint, gh (downloaded and verified if missing), GitHub login
flakipype doctor    # check everything
flakipype scan          # find and rank flaky jobs (--json for scripts)
flakipype investigate   # let the agent explain them, with evidence
flakipype               # the chat: ask, scan, investigate, rerun and fix interactively
flakipype run           # unattended: scan, investigate, open draft pull requests
flakipype daemon install    # run it daily from a systemd user timer
```

Weiter geht es mit [Ein Modell verbinden](docs/how-to/modell-verbinden.md),
[Instabile Pipelines finden](docs/how-to/instabile-pipelines-finden.md),
[Den Chat nutzen](docs/how-to/chat-nutzen.md) und
[Zeitgesteuert ausführen](docs/how-to/zeitgesteuert-ausfuehren.md); jeder
Befehl: [Befehle](docs/reference/befehle.md).

## Entwicklung

Voraussetzungen: [uv](https://docs.astral.sh/uv/); für die Linux-Prüfung unter
Windows außerdem Docker und [act](https://nektosact.com/).

```bash
uv sync
uv run poe check
```

Ausführlich:
[Entwicklungsumgebung aufsetzen](docs/tutorials/entwicklungsumgebung.md),
[Befehle](docs/reference/befehle.md) und [CONTRIBUTING.md](CONTRIBUTING.md).

## Dokumentation

Webseite: <https://besessener.github.io/flakipype/>. Die vollständige
Dokumentation liegt unter [docs/](docs/README.md), gegliedert nach
[Diátaxis](https://diataxis.fr/):

- **[Tutorials](docs/README.md#tutorials)** – Schritt für Schritt zum ersten Erfolg, z. B. [Erste Schritte](docs/tutorials/erste-schritte.md)
- **[Anleitungen](docs/README.md#anleitungen)** – konkrete Aufgaben lösen, z. B. [Ein Modell verbinden](docs/how-to/modell-verbinden.md) oder [Zeitgesteuert ausführen](docs/how-to/zeitgesteuert-ausfuehren.md)
- **[Referenz](docs/README.md#referenz)** – genaues Verhalten nachschlagen, z. B. [Befehle](docs/reference/befehle.md) oder [Konfiguration](docs/reference/konfiguration.md)
- **[Hintergrund](docs/README.md#hintergrund)** – verstehen, warum es so ist, z. B. [Architektur](docs/explanation/architektur.md) oder [Sicherheitsmodell](docs/explanation/sicherheitsmodell.md)

## Verwandte Projekte

flakipype, PlayMonkey und Archivist sind aus derselben agentischen Idee
entstanden und teilen Grundregeln, Qualitätsprüfungen und den Aufbau der
Dokumentation:

- [PlayMonkey](https://github.com/besessener/PlayMonkey) – lässt einen Monkey
  mit festem Seed auf eine Website in einer Testumgebung los und liefert
  reproduzierbare Fehler.
- [Archivist](https://github.com/besessener/Archivist) – ein persönlicher,
  agentischer KI-Archivar für Windows.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
