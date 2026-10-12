# flakipype

![Python](https://img.shields.io/badge/python-%3E%3D3.12-3776AB?logo=python&logoColor=white)
![uv](https://img.shields.io/badge/packaging-uv-DE5FE9?logo=uv&logoColor=white)
![Textual](https://img.shields.io/badge/TUI-Textual-5a4fcf)
![Typer](https://img.shields.io/badge/CLI-Typer-009688)
![Pydantic](https://img.shields.io/badge/validation-Pydantic-E92063?logo=pydantic&logoColor=white)
![Anthropic](https://img.shields.io/badge/LLM-Anthropic%20Messages%20API-191919?logo=anthropic&logoColor=white)
![gh](https://img.shields.io/badge/GitHub-gh%20CLI-181717?logo=github&logoColor=white)
![Ruff](https://img.shields.io/badge/lint-Ruff-D7FF64?logo=ruff&logoColor=black)
![mypy](https://img.shields.io/badge/types-mypy%20strict-2A6DB2)
![import-linter](https://img.shields.io/badge/architecture-import--linter-orange)
![pytest](https://img.shields.io/badge/tested%20with-pytest-0A9EDC?logo=pytest&logoColor=white)
![Gitleaks](https://img.shields.io/badge/secrets-Gitleaks-blue?logo=git&logoColor=white)
![zizmor](https://img.shields.io/badge/workflow%20security-zizmor-blue?logo=githubactions&logoColor=white)
[![CI](https://github.com/besessener/flakipype/actions/workflows/ci.yml/badge.svg)](https://github.com/besessener/flakipype/actions/workflows/ci.yml)
[![CodeQL](https://github.com/besessener/flakipype/actions/workflows/codeql.yml/badge.svg)](https://github.com/besessener/flakipype/actions/workflows/codeql.yml)
[![Last commit](https://img.shields.io/github/last-commit/besessener/flakipype)](https://github.com/besessener/flakipype/commits/main)
[![License: MIT](https://img.shields.io/github/license/besessener/flakipype)](LICENSE)

***Find, explain and fix flaky GitHub Actions pipelines.***

flakipype is an agentic command line tool for Linux. Point it at a GitHub user
or organisation and it scans the workflow runs, scores how flaky each workflow,
job and step is, explains the likely cause with an Anthropic model and fixes it
through a pull request — verified by rerunning the fix branch before you
review it.

- **Chat** in a rich terminal UI with slash commands (`/scan`, `/flaky`, `/fix`, …).
- **Headless** commands and a systemd timer for unattended scans.
- **Safe by design**: never touches the default branch; every fix is a draft PR.

> **Status:** pre-alpha. Setup, scanning, agent investigations, the chat,
> confirmed reruns and dispatches, fixes as draft pull requests and unattended
> runs from a systemd timer work, see the
> [roadmap](docs/explanation/roadmap.md).

## Installation

Requires Linux (x86_64 or aarch64, glibc) with `curl`, `tar` and `git`. The
script installs [uv](https://docs.astral.sh/uv/) if you have none, checked
against its published SHA-256, and then flakipype for your user:

```bash
curl -fsSLO https://raw.githubusercontent.com/besessener/flakipype/v0.1.0/install.sh
sh install.sh
```

With uv already installed: `uv tool install git+https://github.com/besessener/flakipype@v0.1.0`.

```bash
flakipype setup     # model endpoint, gh (downloaded and verified if missing), GitHub login
flakipype doctor    # check everything
flakipype scan          # find and rank flaky jobs (--json for scripts)
flakipype investigate   # let the agent explain them, with evidence
flakipype               # the chat: ask, scan, investigate, rerun and fix interactively
flakipype run           # unattended: scan, investigate, open draft pull requests
flakipype daemon install    # run it daily from a systemd user timer
```

Step by step: [getting started](docs/tutorials/getting-started.md).

## Development

Requirements: [uv](https://docs.astral.sh/uv/); for the Linux gate on Windows
also Docker and [act](https://nektosact.com/).

```bash
uv sync
uv run poe check
```

Details: [development setup](docs/tutorials/development-setup.md) and
[commands](docs/reference/commands.md).

## Documentation

Website: <https://besessener.github.io/flakipype/>. The full documentation is in
[docs/](docs/README.md), organised by [Diátaxis](https://diataxis.fr/):

- **[Tutorials](docs/README.md#tutorials)** – step by step to a first success, e.g. [getting started](docs/tutorials/getting-started.md)
- **[How-to guides](docs/README.md#how-to-guides)** – reach one goal, e.g. [connect a model](docs/how-to/connect-a-model.md) or [run on a schedule](docs/how-to/run-on-a-schedule.md)
- **[Reference](docs/README.md#reference)** – look up exact behaviour, e.g. [commands](docs/reference/commands.md) or [configuration](docs/reference/configuration.md)
- **[Explanation](docs/README.md#explanation)** – understand why, e.g. [architecture](docs/explanation/architecture.md) or [safety model](docs/explanation/safety-model.md)

## License

MIT, see [LICENSE](LICENSE).
