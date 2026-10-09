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

> **Status:** pre-alpha. The foundation is in place; features land milestone
> by milestone, see the [roadmap](docs/explanation/roadmap.md).

## Installation

Planned: `uv tool install git+https://github.com/besessener/flakipype` plus an
install script. Requires Linux; the `gh` CLI is downloaded and verified
automatically if it is missing.

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
