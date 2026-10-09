# Commands

## Development tasks (`uv run poe <task>`)

| Task | Runs | Purpose |
| --- | --- | --- |
| `format` | `ruff format` | Format all files |
| `format-check` | `ruff format --check` | Fail on unformatted files |
| `lint` | `ruff check` | Lint with all ruff rules (exceptions in `pyproject.toml`) |
| `typecheck` | `mypy` | Type check `src` and `tests` in strict mode |
| `arch` | `lint-imports` | Architecture boundaries (import-linter) |
| `deps` | `deptry src` | Unused, missing and misplaced dependencies |
| `deadcode` | `vulture` | Dead code |
| `test` | `pytest` | Tests without coverage |
| `test-cov` | `pytest --cov` | Tests with the coverage threshold |
| `check` | all of the above except `format`, `test` | The local definition of done |

Outside poe:

| Command | Purpose |
| --- | --- |
| `prek run --all-files` | gitleaks, zizmor, file hygiene hooks |
| `act pull_request -j test` | Linux CI job in Docker, see [run CI locally](../how-to/run-ci-locally.md) |

## `flakipype` CLI

| Command | Status | Purpose |
| --- | --- | --- |
| `flakipype --version` | available | Print the installed version |
| `flakipype` (no args) | available | Show help; becomes the chat in M3 |

The commands planned per milestone are listed in the [roadmap](../explanation/roadmap.md).
