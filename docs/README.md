# flakipype documentation

Organised by [Diátaxis](https://diataxis.fr/): by what you need right now.

|  | For learning | For working |
| --- | --- | --- |
| **Practice** | [Tutorials](#tutorials) – step by step to a first success | [How-to guides](#how-to-guides) – reach one concrete goal |
| **Knowledge** | [Explanation](#explanation) – understand why it is so | [Reference](#reference) – look up exactly how it is |

## Tutorials

- [Getting started](tutorials/erste-schritte.md) – install, set up, check.
- [Development setup](tutorials/entwicklungsumgebung.md) – from clone to all gates green.

## How-to guides

**Using flakipype**

- [Find flaky pipelines](how-to/instabile-pipelines-finden.md) – `flakipype scan`, options, scripts.
- [Investigate findings](how-to/befunde-untersuchen.md) – let the agent explain them with evidence.
- [Use the chat](how-to/chat-nutzen.md) – ask questions, scan and investigate interactively, sessions.
- [Connect a model](how-to/modell-verbinden.md) – Anthropic API, Azure AI Foundry or a proxy.
- [Set up a headless machine](how-to/headless-einrichten.md) – servers, containers, SSH.
- [Run on a schedule](how-to/zeitgesteuert-ausfuehren.md) – `flakipype run` and the systemd user timer.

**Developing flakipype**

- [Contributing](../CONTRIBUTING.md) – set up, work, open a pull request, release.
- [Run CI locally with act](how-to/ci-lokal-ausfuehren.md) – the Linux gate on Windows.
- [Maintain the website](how-to/webseite-pflegen.md) – `site/`, screenshots and the Pages workflow.

## Reference

- [Commands](reference/befehle.md) – `poe` tasks and the `flakipype` CLI.
- [Configuration](reference/konfiguration.md) – files, settings, secrets and `gh`.
- [Scan JSON](reference/scan-json.md) – the `flakipype scan --json` format.
- [Quality gates](reference/qualitaetssicherung.md) – tests, linters, CI jobs and what each one enforces.

## Explanation

- [Architecture](explanation/architektur.md) – packages, layers and data flow.
- [How flakiness is detected](explanation/flake-erkennung.md) – signals, rates and error signatures.
- [The agent](explanation/agent.md) – investigators, reviewer, tools, verdicts, budgets and the chat.
- [Actions](explanation/aktionen.md) – reruns, dispatches, confirmation and the live run view.
- [Fixes](explanation/korrekturen.md) – fixer agent, diff checks, draft pull requests and verification.
- [Unattended runs and release](explanation/unbeaufsichtigte-laeufe.md) – `flakipype run`, the systemd timer, the install script and smoke tests.
- [Safety model](explanation/sicherheitsmodell.md) – modes, risk levels, pull requests and budgets.

Related projects with the same idea and the same documentation layout:
[PlayMonkey](https://github.com/besessener/PlayMonkey/blob/main/docs/README.md) and
[Archivist](https://github.com/besessener/Archivist/blob/main/docs/README.md) (in German).
