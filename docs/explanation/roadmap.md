# Roadmap

## Scope

- Linux command line tool, rich terminal UI (Textual).
- Connects to one GitHub user or organisation, on github.com or GitHub
  Enterprise Server, via `gh` (logged in with `gh auth login` or a
  fine-grained PAT).
- Detects flaky GitHub Actions workflows, explains them with an Anthropic
  model (api.anthropic.com or Azure AI Foundry) and fixes workflow YAML and
  test code through pull requests.
- Chat with resumable sessions, plus headless commands and a systemd timer.
- Installed with `uv tool install git+https://github.com/besessener/flakipype`
  or an install script. Not published to PyPI.

## Milestones

Each milestone is one branch and one pull request.

| | Milestone | Delivers |
| --- | --- | --- |
| M0 | Foundation | Project skeleton, quality gates, CI, act, CLAUDE.md, docs |
| M1 | Setup | First-run wizard: LLM URL, key and model with a connection test; `gh` download with checksum check; GitHub login and scope check; secret storage |
| M2 | Scan | GitHub read layer with fake `gh`, flake engine in `flaky`, SQLite cache, dashboard; `flakipype scan --json` |
| M3 | Agent | Anthropic client with streaming and tool use, agent loop, policy gate, budgets, masking, chat with slash commands, resumable sessions |
| M4 | Actions | Rerun and dispatch with confirmation, live run view |
| M5 | Fix | Local clone, edit tools, diff review, branch plus PR, verification by rerunning the fix branch |
| M6 | Unattended and release | `flakipype run --auto`, `flakipype daemon install` (systemd user timer), install script, multi-distro smoke tests |

## Planned chat commands

`/setup` `/connect` `/scan` `/flaky` `/inspect` `/rerun` `/watch` `/fix`
`/mode` `/model` `/cost` `/sessions` `/clear` `/help` `/quit`
