# Quality gates

## Local gates

| Gate | Tool | Enforces |
| --- | --- | --- |
| Formatting | ruff format | One style, no discussion |
| Lint | ruff (`select = ["ALL"]`) | Bugs, security (bandit rules), complexity ≤ 10 per function, at most 4 parameters (3 positional) |
| Types | mypy `--strict` | Fully typed `src` and `tests`; ignores need an error code |
| Architecture | import-linter | Layer contract, see [architecture](../explanation/architecture.md) |
| Dependencies | deptry | No unused, missing or misplaced dependencies |
| Dead code | vulture | No unused code |
| Tests | pytest, warnings are errors | Behaviour, not implementation |
| Coverage | coverage.py, branch coverage | `fail_under` in `pyproject.toml`, only ever raised |
| Hygiene | prek: gitleaks, zizmor, pre-commit-hooks | No secrets, safe workflows, clean files |

## Test doubles

Tests never reach real GitHub or a real model.

- **GitHub**: `tests/fakes/gh.py` stands in for `gh`. Each test records the
  expected calls with the `fake_gh` fixture (`tests/conftest.py`,
  `tests/support/fake_gh.py`); the fake replays recorded output from
  `tests/fixtures/gh/` and logs every call (arguments, stdin, `GH_HOST`) for
  assertions. It runs as `python tests/fakes/gh.py`, so it works on Windows too.
- **Actions API**: `tests/fixtures/gh/` holds trimmed real responses
  (repository list, a run page, the jobs of a failed attempt);
  `tests/fixtures/logs/` holds trimmed real job logs (Playwright timeout, npm
  build error and Stryker error behind a generic exit code). The scan service
  is tested against an in-memory fake (`tests/support/fake_actions.py`) that
  can raise any GitHub error on demand; `tests/support/builders.py` builds
  runs and jobs for the pure detection tests.
- **Downloads**: the `gh` installer is tested against an `httpx2.MockTransport`
  serving a release, checksum file and tarball built in the test.
- **LLM**: `tests/support/fake_anthropic.py` answers like the Messages API
  through `httpx2.MockTransport`: scripted turns (thinking, tool calls,
  `submit_verdict`, `submit_review`, HTTP errors), and it records every request
  so tests can assert masking, tool results and thinking settings. The real
  `anthropic` client is used, only the transport is fake.
- **Agent**: `tests/support/fake_sources.py` (logs, commits, files) and
  `tests/support/fake_investigation.py` (a scan world with one finding of
  each kind and an agent stand-in).
- **Setup world**: `tests/support/fake_setup.py` builds a `SetupService` with a
  temporary config dir, file secret store, fake `gh` provider and fake model.
- **TUI**: Textual Pilot tests drive the app (`tests/tui/`); each view has an
  SVG snapshot in `tests/tui/__snapshots__/`. After an intended UI change,
  update it with `uv run pytest tests/tui --snapshot-update` and review the SVG
  diff.
- **Platform-specific tests**: three tests need POSIX (`0600` secrets,
  executable `gh`, `:`-separated `PATH`); they are skipped on Windows and run
  in CI.
- **Real data**: before a scan change is merged, `flakipype scan` runs once
  against a real account in WSL or Linux. It only reads; never print or pass
  tokens on a command line while doing so.

Evaluations against a real model live in `tests/eval`, are not part of
`poe check` or CI, and run only when asked.

## CI (`.github/workflows/`)

| Workflow / job | Checks | When |
| --- | --- | --- |
| `ci.yml` → `hygiene` | gitleaks over the full history (checksum-verified binary), all prek hooks | PR, push to `main` |
| `ci.yml` → `test` | `uv sync --locked` and `poe check` on Python 3.12 and 3.14; coverage table in the job summary | PR, push to `main` |
| `codeql.yml` | CodeQL `security-extended` for Python and Actions | PR, push to `main`, weekly |
| `dependabot.yml` | Updates for Actions, uv dependencies and hook revisions, 7-day cooldown | weekly |

**Workflow hardening**: every action is pinned to a commit SHA (the comment
names the tag), workflows default to no token permissions (`permissions: {}`)
and check out with `persist-credentials: false`. zizmor enforces this.
