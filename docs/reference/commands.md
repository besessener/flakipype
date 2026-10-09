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

| Command | Purpose |
| --- | --- |
| `flakipype --version` | Print the installed version |
| `flakipype` (no args) | Show help; becomes the chat in M3 |
| `flakipype setup` | Full-screen setup wizard (needs a terminal) |
| `flakipype setup --non-interactive [options]` | Headless setup, see below |
| `flakipype doctor` | Check configuration, model connection, `gh` and the GitHub login |
| `flakipype scan [options]` | Find and rank flaky jobs, see below |

### `flakipype scan`

| Option | Meaning |
| --- | --- |
| `--days N` | Days to look back, 1–400 (default `scan.window_days`) |
| `--repo NAME` | Only this repository (`repo` or `owner/repo`); repeat for more |
| `--owner NAME` | Another user or organisation (default `github.owner`) |
| `--max-logs N` | Most job logs to read this time, 0–1000 (default `scan.max_log_downloads`) |
| `--min-runs N` | Runs needed to call a job flaky, 1–100 (default `scan.min_flaky_runs`) |
| `--json` | Print the [JSON result](scan-json.md) on stdout instead of the table |

Exit codes: 0 finished, 1 stopped early or GitHub unreadable, 2 not set up.
Guide: [find flaky pipelines](../how-to/find-flaky-pipelines.md).

### `flakipype setup --non-interactive`

| Option | Meaning |
| --- | --- |
| `--base-url URL` | Anthropic Messages API base URL |
| `--model NAME` | Model, or deployment name on Foundry |
| `--host HOST` | GitHub host |
| `--owner NAME` | GitHub user or organisation to scan |
| `--api-key-stdin` | Read the API key from standard input |

Omitted options keep their saved value. Setup downloads `gh` if needed and
ends with the `doctor` checks.

### Exit codes

| Code | `setup` | `doctor` |
| --- | --- | --- |
| 0 | Saved and all checks passed (warnings allowed) | All checks passed (warnings allowed) |
| 1 | Saved, but a check failed; or the wizard was cancelled | A check failed |
| 2 | Invalid input, or no terminal for the wizard | — |

The commands planned per milestone are listed in the [roadmap](../explanation/roadmap.md).
