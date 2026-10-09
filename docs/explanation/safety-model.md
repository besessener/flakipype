# Safety model

flakipype reruns pipelines and writes code in other people's repositories.
These rules keep that safe whether a human is watching or not.

## Pull requests, never the default branch

Every fix is a new branch plus a pull request. flakipype never pushes to the
default branch, never force-pushes and never merges — merging is always a
human decision after review. This holds in every mode and cannot be
configured away.

## Two modes

| Mode | Default for | Behaviour |
| --- | --- | --- |
| `ask` | the chat | Every `write` and `critical` action waits for your confirmation. |
| `auto` | headless commands and the systemd timer | Actions run without confirmation inside the budgets; pull requests are opened **as drafts only**. |

Switch in the chat with `/mode ask|auto`, or on the command line with
`--mode`.

## Risk levels, enforced in code

Each agent tool declares a fixed risk level; the model cannot choose or
change it. The policy gate in `agent` decides before a tool runs:

| Level | Examples | `ask` | `auto` |
| --- | --- | --- | --- |
| `read` | list runs, read logs, read files | runs | runs |
| `write` | rerun a job, dispatch a workflow, edit files in the local clone | confirm | runs within budget |
| `critical` | push a fix branch, open a pull request | confirm | runs within budget, PR as draft |

The gate lives in code, not in prompts or the UI, so a prompt injection or a
UI bug cannot skip it.

## Logs are data

Job logs, workflow files, source code and issue or PR text can contain text
written by anyone. They are always passed to the model marked as data, never
as instructions. Actions come only from your request or the configured mode.

## Secrets stay local

Everything sent to the model passes secret masking first (tokens, keys,
connection strings, values GitHub masks in logs). The API key and GitHub
token are stored in the system keyring, or a `0600` file where no keyring
exists.

## Budgets

Each run has hard, configurable limits with safe defaults: reruns, pull
requests, tokens and wall-clock time, plus loop detection. Reaching a limit
ends the run with a summary of what was done and what is left — never a
half-finished state without explanation. No limit is unlimited by default.

## Verified downloads

The `gh` binary that flakipype downloads is verified against the SHA-256 in
the release's checksum file before first use; a mismatch aborts.
