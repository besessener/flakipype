# flakipype

[![CI](https://github.com/besessener/flakipype/actions/workflows/ci.yml/badge.svg)](https://github.com/besessener/flakipype/actions/workflows/ci.yml)
[![CodeQL](https://github.com/besessener/flakipype/actions/workflows/codeql.yml/badge.svg)](https://github.com/besessener/flakipype/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/github/license/besessener/flakipype)](LICENSE)

***Find, explain and fix flaky GitHub Actions pipelines.***

flakipype is an agentic command line tool for Linux. Point it at a GitHub user
or organisation and it scans the workflow runs, scores how flaky each workflow,
job and step is, explains the likely cause with an Anthropic model and fixes it
through a pull request — verified by rerunning the fix branch before you
review it.

- **Chat** in a rich terminal UI with slash commands (`/scan`, `/flaky`, `/fix`, …).
- **Headless** commands and a systemd timer for unattended scans.
- **Safe by design**: never touches the default branch; unattended runs open draft PRs only.

> **Status:** pre-alpha. Setup, scanning, agent investigations and the chat
> work; reruns and fixes land milestone by milestone, see the
> [roadmap](docs/explanation/roadmap.md).

## Installation

Requires Linux and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install git+https://github.com/besessener/flakipype
flakipype setup     # model endpoint, gh (downloaded and verified if missing), GitHub login
flakipype doctor    # check everything
flakipype scan          # find and rank flaky jobs (--json for scripts)
flakipype investigate   # let the agent explain them, with evidence
flakipype               # the chat: ask, scan and investigate interactively
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

[docs/](docs/README.md), organised by [Diátaxis](https://diataxis.fr/).

## License

MIT, see [LICENSE](LICENSE).
