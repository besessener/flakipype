# Architecture

flakipype is a single Python package (`src/flakipype/`) split into
sub-packages by responsibility. import-linter (`uv run poe arch`) enforces the
layers; a higher layer may import a lower one, never the reverse, and packages
on the same layer do not import each other.

```text
cli                       Typer entry point, composition root (cli/wiring.py)
 └─ tui                   Textual: setup wizard, later the chat
     ├─ agent             agent loop, tools, policy gate, budgets, sessions
     └─ setup             setup and health checks (wizard, headless, doctor)
         ├─ llm           Anthropic Messages API client
         ├─ github        gh CLI wrapper; downloads and verifies gh
         └─ store         SQLite: runs, scores, sessions, audit log
             ├─ flaky     pure flakiness detection and scoring
             └─ config    settings and secret storage
```

## Packages

- **`flaky`** is pure. It receives runs, jobs and log excerpts as values and
  returns scores and signatures. No network, filesystem, `gh`, database or
  clock — the current time is a parameter. That keeps the core logic
  deterministic and easy to test exhaustively.
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
  uses.
- **`llm`** wraps the official `anthropic` SDK with a configurable base URL,
  so the same code talks to api.anthropic.com and Azure AI Foundry (chosen by
  the host name). Connection problems are categorised
  (`ConnectionProblem`), each with a next step for the user.
- **`setup`** is the application service behind the wizard, headless setup
  and `doctor`: it validates input, stores settings and the key, finds or
  installs `gh` and checks the login. Its collaborators (secret store, `gh`
  provider, model check) are passed in, so tests swap them for fakes.
- **`store`** owns the SQLite database under `$XDG_DATA_HOME/flakipype`.
- **`agent`** runs the tool loop. Every tool declares a risk level and is
  executed only through the policy gate; see the
  [safety model](safety-model.md).
- **`tui`** renders the setup wizard and later the chat with Textual. It
  talks to `setup` and `agent` and never runs `gh` or the model itself;
  slow work runs in worker threads so the UI stays responsive.
- **`cli`** wires everything together: `cli/wiring.py` is the only place that
  reads the environment and builds real collaborators. Headless commands
  bypass `tui` but not `setup` or `agent`.

## Data flow

1. **Scan**: `github` lists repositories, workflow runs and attempts in the
   configured window (default 30 days), incrementally; `store` caches them.
2. **Score**: `flaky` computes flake signals — same commit both failed and
   passed, pass/fail flips without relevant changes, recurring error
   signatures — and a flake rate per repository, workflow, job and step.
3. **Explain**: `agent` sends masked log excerpts, marked as data, to the
   model and asks for a diagnosis.
4. **Fix**: in a local clone, the agent edits workflow YAML or test code,
   pushes a branch, opens a PR and reruns the fix branch to compare its flake
   rate with the default branch.
