# Commands

## Development tasks (`uv run poe <task>`)

| Task | Runs | Purpose |
| --- | --- | --- |
| `format` | `ruff format` | Format all files |
| `format-check` | `ruff format --check` | Fail on unformatted files |
| `lint` | `ruff check` | Lint with all ruff rules (exceptions in `pyproject.toml`) |
| `typecheck` | `ty check` | Type check `src` and `tests` (rules in `pyproject.toml`) |
| `arch` | `lint-imports` | Architecture boundaries (import-linter) |
| `deps` | `deptry src` | Unused, missing and misplaced dependencies |
| `deadcode` | `vulture` | Dead code |
| `shellcheck` | `shellcheck install.sh tests/smoke/smoke.sh` | Lint the shell scripts |
| `test` | `pytest` | Tests without coverage |
| `test-cov` | `pytest --cov` | Tests with the coverage threshold |
| `check` | all of the above except `format`, `test` | The local definition of done |

Outside poe:

| Command | Purpose |
| --- | --- |
| `prek run --all-files` | gitleaks, zizmor, file hygiene hooks |
| `act pull_request -j test` | Linux CI job in Docker, see [run CI locally](../how-to/run-ci-locally.md) |
| `act pull_request -j smoke` | `install.sh` and a first start on Ubuntu, Debian, Fedora and Arch |

## `flakipype` CLI

| Command | Purpose |
| --- | --- |
| `flakipype --version` | Print the installed version |
| `flakipype` (no args) | The chat in a terminal, see [use the chat](../how-to/chat.md); otherwise the help. Exit codes: 0 left, 1 GitHub unreadable or the chat crashed, 2 not set up |
| `flakipype setup` | Full-screen setup wizard (needs a terminal) |
| `flakipype setup --non-interactive [options]` | Headless setup, see below |
| `flakipype doctor` | Check configuration, model connection, `gh` and the GitHub login |
| `flakipype scan [options]` | Find and rank flaky jobs, see below |
| `flakipype investigate [options]` | Let the agent explain findings with evidence; see [investigate findings](../how-to/investigate-findings.md) |
| `flakipype run [options]` | Scan, investigate and fix without a window, see below |
| `flakipype daemon install\|uninstall\|status` | The systemd user timer that starts `flakipype run`, see below |

### `flakipype run`

| Option | Meaning |
| --- | --- |
| `--mode auto\|ask` | `auto` (default) pushes draft pull requests within the limits; `ask` only reports what it would do |
| `--days N`, `--repo NAME` | As for `scan` |
| `--owner NAME` | Must be the configured `github.owner` (any case): a run fixes only that owner; any other exits with code 2 |
| `--json` | Print the summary as JSON (`schema_version` 1) |

Exit codes: 0 finished (a reached limit is a normal end), 1 something was
incomplete (scan stopped early, GitHub or the model failed, a delivery
failed), 2 not set up or another `--owner`, 3 another `flakipype run` is running. How it works:
[unattended runs](../explanation/unattended.md).

### `flakipype daemon`

| Command | Meaning |
| --- | --- |
| `install [--schedule S] [--mode auto\|ask]` | Run `doctor` in the timer's environment, then write, enable and start `flakipype.timer`; `S` is a systemd calendar expression (default `daily`) |
| `install --print` | Print the unit files, change nothing |
| `uninstall` | Stop the timer and remove the units flakipype wrote |
| `status` | The timer, the last result and the last run's summary |

`install` and `uninstall` exit with 1 when systemd refuses, `install` with 2
when flakipype is not set up. Guide: [run on a schedule](../how-to/run-on-a-schedule.md).

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
| `--secret-store auto\|keyring\|file` | Where the API key is kept (`secrets.store`); with a new store, pass the key again |

Omitted options keep their saved value. Setup downloads `gh` if needed and
ends with the `doctor` checks. The wizard (`flakipype setup` without
`--non-interactive`) takes `--secret-store` too and saves that choice.

### Exit codes

| Code | `setup` | `doctor` |
| --- | --- | --- |
| 0 | Saved and all checks passed (warnings allowed) | All checks passed (warnings allowed) |
| 1 | Saved, but a check failed; or the wizard was cancelled | A check failed |
| 2 | Invalid input, a configuration file setup cannot keep, no terminal for the wizard, or the secret store cannot be read or written | The secret store cannot be read |
