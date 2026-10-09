# Architecture

flakipype is a single Python package (`src/flakipype/`) split into
sub-packages by responsibility. import-linter (`uv run poe arch`) enforces the
layers; a higher layer may import a lower one, never the reverse, and packages
on the same layer do not import each other.

```text
cli                           Typer entry point, composition root (cli/wiring.py)
 └─ tui                       Textual: setup wizard, chat window, confirmation dialog
     └─ investigate           scan and investigate findings; verdict cache; the chat's workspace and commands
         └─ actions           reruns, dispatches, cancels: targets, budget, audit, watched runs
             ├─ agent         investigator, reviewer, chat orchestrator, tools, policy gate, budgets, masking
             ├─ setup         setup and health checks (wizard, headless, doctor)
             └─ scan          scan an owner: fetch, cache, detect, rank
                 ├─ llm       Anthropic Messages API client
                 ├─ github    gh CLI wrapper; Actions, runs, commits, files; downloads gh
                 └─ store     SQLite cache, chat sessions and the action audit log
                     ├─ flaky   pure detection, scoring, findings, log excerpts
                     └─ config  settings and secret storage
```

## Packages

- **`flaky`** is pure. It receives runs, jobs and log text as values and
  returns flaky failures, rankings and error signatures. No network,
  filesystem, `gh`, database or clock — the current time is a parameter. That
  keeps the core logic deterministic and easy to test exhaustively. How it
  decides: [flake detection](flake-detection.md).
- **`config`** reads and writes settings under `$XDG_CONFIG_HOME/flakipype`
  and keeps secrets in the system keyring, falling back to a `0600` file on
  headless machines.
- **`github`** is the only place that runs `gh`. If no suitable `gh` is on
  `PATH`, it downloads the release tarball for the machine's architecture,
  verifies its SHA-256 against the release checksums and installs it under
  `$XDG_DATA_HOME/flakipype/bin`. Supports github.com and GitHub Enterprise
  Server (`GH_HOST`). flakipype shares the user's `gh` login rather than
  keeping its own token. Release and version logic (`release.py`) is pure;
  the download goes through `httpx2`, the same HTTP stack the `anthropic` SDK
  uses. `actions.py` reads repositories, runs, jobs and logs with `gh api`,
  validates the answers with pydantic models (`payloads.py`) and turns `gh`
  errors into typed exceptions (rate limit, authentication, others).
  `runs.py` (`RunControl`) reruns, dispatches and cancels runs and reads
  their state.
- **`llm`** wraps the official `anthropic` SDK with a configurable base URL,
  so the same code talks to api.anthropic.com and Azure AI Foundry (chosen by
  the host name). Connection problems are categorised
  (`ConnectionProblem`), each with a next step for the user.
- **`setup`** is the application service behind the wizard, headless setup
  and `doctor`: it validates input, stores settings and the key, finds or
  installs `gh` and checks the login. Its collaborators (secret store, `gh`
  provider, model check) are passed in, so tests swap them for fakes.
- **`scan`** is the application service behind `flakipype scan` (and later
  the agent's scan tools): it lists runs, fetches jobs for attempts that can
  be flaky and for the last attempt of failed runs, reads a limited number of
  logs, and returns the verdicts (flaky, seen once, fixed) plus recurring
  errors without proof. A rate
  limit stops it early with a report of what was found; other errors skip the
  item and are listed. Progress is reported as events, so the CLI and the TUI
  can show it their own way.
- **`store`** owns the SQLite cache under `$XDG_DATA_HOME/flakipype`: jobs of
  finished attempts and log results, which never change. Schema migrations
  are append-only (`PRAGMA user_version`); cached signatures carry the
  signature algorithm's version and are recomputed when it changes. Run lists
  are not cached: listing them is cheap and they change constantly. Chat
  sessions are stored there too, as one JSON document per session, and so is
  the append-only audit log of action requests (`audit.py`).
- **`agent`** investigates one finding: an investigator tool loop over the
  Messages API, a deterministic citation check, a reviewer pass and at most one
  revision ([the agent](agent.md)). Every tool declares a risk level and runs
  only through the policy gate ([safety model](safety-model.md)); everything
  sent to the model is masked first. It knows nothing of the scan service:
  it gets a `Finding` and the scan's `Evidence` as values. The chat
  orchestrator (`orchestrator.py`) is a tool loop too; its tools call a
  `Workspace` protocol that `investigate` implements.
- **`actions`** prepares the chat's reruns, dispatches and cancels for the
  policy gate: it checks the targets against the current scan's findings,
  reads the workflow file to check `workflow_dispatch`, enforces the session
  budget, records every request in the audit log, and watches started runs
  (polling, finish notes, session state). Its GitHub collaborators are
  protocols that `github` implements ([actions](actions.md)).
- **`investigate`** runs a scan, numbers the findings, picks the requested
  ones, runs investigations in parallel under one run budget and stores
  completed verdicts in the cache until a finding has a newer failure. For
  the chat it holds the current scan and its verdicts (`workspace.py`) and
  handles slash commands and sessions (`chat.py`), independent of Textual.
- **`tui`** renders the setup wizard and the chat with Textual. It talks to
  `setup` and `investigate` and never runs `gh` or the model itself; slow
  work runs in worker threads so the UI stays responsive. The chat window
  answers the gate's confirmation requests with a dialog and polls started
  runs in the background.
- **`cli`** wires everything together: `cli/wiring.py` is the only place that
  reads the environment and builds real collaborators. Headless commands
  bypass `tui` but not `setup` or `agent`.

## Data flow

1. **Scan**: `github` lists repositories and workflow runs in the configured
   window (default 30 days); `flaky` picks the attempts worth a look, whose
   jobs and logs `github` then fetches and `store` caches.
2. **Facts**: `flaky` keeps failures with proof (passed on rerun, same commit
   passed), decides flaky / seen once / fixed, lists recurring errors without
   proof, and extracts error signatures. Deterministic and free of model cost.
3. **Judgement**: the agent investigates findings with tools (prepared log
   excerpts, run history, commit diffs, files), marked as data, and returns
   verdicts with cited evidence that a reviewer pass checks (M3).
4. **Fix**: in a local clone, the agent edits workflow YAML or test code,
   pushes a branch, opens a PR and reruns the fix branch to compare its flake
   rate with the default branch.
