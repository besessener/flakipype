# flakipype documentation

Organised by [Diátaxis](https://diataxis.fr/): by what you need right now.

|  | For learning | For working |
| --- | --- | --- |
| **Practice** | [Tutorials](#tutorials) – step by step to a first success | [How-to guides](#how-to-guides) – reach one concrete goal |
| **Knowledge** | [Explanation](#explanation) – understand why it is so | [Reference](#reference) – look up exactly how it is |

## Tutorials

- [Getting started](tutorials/getting-started.md) – install, set up, check.
- [Development setup](tutorials/development-setup.md) – from clone to all gates green.

## How-to guides

**Using flakipype**

- [Find flaky pipelines](how-to/find-flaky-pipelines.md) – `flakipype scan`, options, scripts.
- [Investigate findings](how-to/investigate-findings.md) – let the agent explain them with evidence.
- [Use the chat](how-to/chat.md) – ask questions, scan and investigate interactively, sessions.
- [Connect a model](how-to/connect-a-model.md) – Anthropic API, Azure AI Foundry or a proxy.
- [Set up a headless machine](how-to/set-up-headless.md) – servers, containers, SSH.
- [Run on a schedule](how-to/run-on-a-schedule.md) – `flakipype run` and the systemd user timer.

**Developing flakipype**

- [Run CI locally with act](how-to/run-ci-locally.md) – the Linux gate on Windows.
- [Maintain the website](how-to/maintain-the-website.md) – `site/`, screenshots and the Pages workflow.

## Reference

- [Commands](reference/commands.md) – `poe` tasks and the `flakipype` CLI.
- [Configuration](reference/configuration.md) – files, settings, secrets and `gh`.
- [Scan JSON](reference/scan-json.md) – the `flakipype scan --json` format.
- [Quality gates](reference/quality.md) – tests, linters, CI jobs and what each one enforces.

## Explanation

- [Architecture](explanation/architecture.md) – packages, layers and data flow.
- [How flakiness is detected](explanation/flake-detection.md) – signals, rates and error signatures.
- [The agent](explanation/agent.md) – investigators, reviewer, tools, verdicts, budgets and the chat.
- [Actions](explanation/actions.md) – reruns, dispatches, confirmation and the live run view.
- [Fixes](explanation/fix.md) – fixer agent, diff checks, draft pull requests and verification.
- [Unattended runs and release](explanation/unattended.md) – `flakipype run`, the systemd timer, the install script and smoke tests.
- [Safety model](explanation/safety-model.md) – modes, risk levels, pull requests and budgets.
- [Roadmap](explanation/roadmap.md) – scope and milestones.

Related projects with the same idea and the same documentation layout:
[PlayMonkey](https://github.com/besessener/PlayMonkey/blob/main/docs/README.md) and
[Archivist](https://github.com/besessener/Archivist/blob/main/docs/README.md) (in German).
