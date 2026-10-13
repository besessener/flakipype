# Contributing

Thanks for helping. flakipype is a Linux command line tool in Python with a
Textual chat; the [documentation](docs/README.md) explains how it works.

## Set up

[uv](https://docs.astral.sh/uv/) and [prek](https://prek.j178.dev/):

```bash
uv sync          # .venv with Python 3.12 and all dev tools
prek install     # git hooks
```

Details, also for Windows with Docker and act: [development setup](docs/tutorials/development-setup.md).

## Work

| Task | Command |
| --- | --- |
| Run all tests | `uv run poe test` |
| One test file | `uv run pytest tests/unit/flaky/test_scoring.py` |
| Format | `uv run poe format` |
| Lint, types, architecture | `uv run poe lint`, `uv run poe typecheck`, `uv run poe arch` |
| Every local quality gate | `uv run poe check` |
| Update TUI snapshots | `uv run pytest tests/tui --snapshot-update` |
| Try the CLI | `uv run flakipype --version` |

Tests never call real GitHub or a real model: GitHub is a `gh` stub replaying
recorded JSON, the model a local fake Anthropic server
([test doubles](docs/reference/quality.md#test-doubles)). A TUI change gets a
Textual Pilot test, a new view a snapshot.

## Before you open a pull request

```bash
uv run poe format
uv run poe check                 # format, lint, types, architecture, deps, dead code, tests + coverage
prek run --all-files             # gitleaks, zizmor, file hygiene
act pull_request -j test         # the Linux CI job, when you work on Windows or macOS
```

- Keep changes focused; one topic per pull request.
- Update the docs with the code: behaviour, setup, configuration or a design
  decision changes the matching file under [docs/](docs/README.md).
- Keep the [safety model](docs/explanation/safety-model.md) intact: the
  default branch is never written, every agent tool runs through the policy
  gate, and nothing reaches the model unmasked.

CI runs every [quality gate](docs/reference/quality.md) (`ci.yml`,
`codeql.yml`), including the install smoke tests on Ubuntu, Debian, Fedora
and Arch.

## Releasing

Changes are listed in the [GitHub Releases](https://github.com/besessener/flakipype/releases).

1. Set the new version in `pyproject.toml` and as `FLAKIPYPE_VERSION` in
   `install.sh` (a unit test checks that both agree), and update the
   install commands in the [README](README.md), the
   [getting started](docs/tutorials/getting-started.md) tutorial,
   [unattended runs and release](docs/explanation/unattended.md) and
   `site/index.html`. Merge that through a pull request.
2. Tag the merge commit on `main`, push the tag and create a GitHub release
   from it with generated notes:
   `git tag vX.Y.Z && git push origin vX.Y.Z`.

There is no release workflow and no PyPI package; how installing works:
[unattended runs and release](docs/explanation/unattended.md#release).

## Extending

- A new agent tool: [what the investigator can use](docs/explanation/agent.md#what-the-investigator-can-use)
  and its [risk level](docs/explanation/safety-model.md#risk-levels-enforced-in-code).
- A new flakiness signal: [how flakiness is detected](docs/explanation/flake-detection.md).
