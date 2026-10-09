# Architecture

flakipype is a single Python package (`src/flakipype/`) split into
sub-packages by responsibility. import-linter (`uv run poe arch`) enforces the
layers; a higher layer may import a lower one, never the reverse, and packages
on the same layer do not import each other.

```text
cli                       Typer entry point: chat and headless commands
 └─ tui                   Textual chat: screens, widgets, slash commands
     └─ agent             agent loop, tools, policy gate, budgets, sessions
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
  Server (`GH_HOST`).
- **`llm`** wraps the official `anthropic` SDK with a configurable base URL,
  so the same code talks to api.anthropic.com and Azure AI Foundry.
- **`store`** owns the SQLite database under `$XDG_DATA_HOME/flakipype`.
- **`agent`** runs the tool loop. Every tool declares a risk level and is
  executed only through the policy gate; see the
  [safety model](safety-model.md).
- **`tui`** renders the chat with Textual; it talks to `agent` and never runs
  `gh` or the model directly.
- **`cli`** wires everything together. Headless commands bypass `tui` but not
  `agent`.

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
