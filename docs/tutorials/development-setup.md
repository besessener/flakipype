# Development setup

This takes you from a fresh clone to every quality gate green. It works on
Linux, macOS and Windows; flakipype itself only targets Linux, so on Windows
the Linux check runs through [act](../how-to/run-ci-locally.md).

## 1. Install the tools

- [uv](https://docs.astral.sh/uv/getting-started/installation/) – installs
  the right Python and all dev tools.
- [prek](https://prek.j178.dev/) (or `pre-commit`) – runs the git hooks.
- Docker and [act](https://nektosact.com/) – only needed for the Linux CI job
  on a non-Linux machine.

## 2. Create the environment

```bash
git clone https://github.com/besessener/flakipype.git
cd flakipype
uv sync
prek install
```

`uv sync` creates `.venv` with Python 3.12 (pinned in `.python-version`) and
installs flakipype in editable mode together with the dev group.

## 3. Run the gates

```bash
uv run poe check          # format, lint, types, architecture, deps, dead code, tests + coverage
prek run --all-files      # gitleaks, zizmor, file hygiene
act pull_request -j test  # Linux CI job in Docker (Windows/macOS)
```

All three green means you are ready to open a pull request. What each gate
checks: [quality gates](../reference/quality.md).

## 4. Try the CLI

```bash
uv run flakipype --version
```
