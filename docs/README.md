# flakipype documentation

Organised by [Diátaxis](https://diataxis.fr/).

## Tutorials

- [Getting started](tutorials/getting-started.md) – install, set up, check.
- [Development setup](tutorials/development-setup.md) – from clone to all gates green.

## How-to guides

- [Find flaky pipelines](how-to/find-flaky-pipelines.md) – `flakipype scan`, options, scripts.
- [Investigate findings](how-to/investigate-findings.md) – let the agent explain them with evidence.
- [Use the chat](how-to/chat.md) – ask questions, scan and investigate interactively, sessions.
- [Connect a model](how-to/connect-a-model.md) – Anthropic API, Azure AI Foundry or a proxy.
- [Set up a headless machine](how-to/set-up-headless.md) – servers, containers, SSH.
- [Run CI locally with act](how-to/run-ci-locally.md) – the Linux gate on Windows.

## Reference

- [Commands](reference/commands.md) – `poe` tasks and the `flakipype` CLI.
- [Configuration](reference/configuration.md) – files, settings, secrets and `gh`.
- [Scan JSON](reference/scan-json.md) – the `flakipype scan --json` format.
- [Quality gates](reference/quality.md) – tests, linters, CI jobs and what each one enforces.

## Explanation

- [Architecture](explanation/architecture.md) – packages, layers and data flow.
- [How flakiness is detected](explanation/flake-detection.md) – signals, rates and error signatures.
- [The agent](explanation/agent.md) – investigators, reviewer, tools, verdicts, budgets and the chat.
- [Actions](explanation/actions.md) – reruns, dispatches, confirmation and the live run view (M4 design).
- [Safety model](explanation/safety-model.md) – modes, risk levels, pull requests and budgets.
- [Roadmap](explanation/roadmap.md) – scope and milestones.
