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
| M3 | Agent | Investigators per finding with read-only tools (prepared log excerpts, run history, commit diffs, files), citation check and reviewer, verdicts with evidence, policy gate, budgets, masking; chat with slash commands, resumable sessions; `flakipype investigate`. Design: [the agent](agent.md) |
| M4 | Actions | In the chat: rerun failed jobs or a whole run, dispatch a workflow, cancel own runs; each confirmed, budgeted and audited; live run view. How it works: [actions](actions.md) |
| M5 | Fix | Fixer agent with edit tools on an in-memory copy (no clone), checks and reviewer on the diff, one confirmation with the diff, branch plus signed commit through the API, draft PR, verification by rerunning the fix branch; `/mode ask\|auto` in the chat. How it works: [fixes](fix.md) |
| M6 | Unattended and release | `flakipype run --auto`, `flakipype daemon install` (systemd user timer), install script, multi-distro smoke tests |

## Chat commands

Since M3: `/scan` `/findings` `/flaky` `/investigate` `/why` `/budget`
`/sessions` `/resume` `/new` `/help` `/quit`; since M4: `/rerun` `/dispatch`
`/cancel` `/runs` `/actions`; since M5: `/fix` `/mode` (see
[use the chat](../how-to/chat.md)).

Planned: `/setup` `/model`.
