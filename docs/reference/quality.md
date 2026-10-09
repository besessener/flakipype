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

- **GitHub**: a fake `gh` executable on `PATH` replays recorded JSON
  (from M2).
- **LLM**: a local fake server speaking the Anthropic Messages API, including
  streaming and tool use, with scripted turns per test (from M3).
- **TUI**: Textual Pilot tests drive the app; new views get an SVG snapshot
  (from M1).

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
