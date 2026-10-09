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

Switch in the chat with `/mode ask|auto` (planned with M5; the chat always
starts in `ask`), or on the command line with `--mode` (M6; until then only
`investigate`, which only reads, runs headless). Every flakipype pull
request is a draft, in both modes.

In `auto` mode, a fix whose diff touches `.github/`, adds something that
could hide a failure or reaches out to the network or secrets is not pushed:
a pushed branch runs its own workflow files with the repository's secrets
before anyone reviews it ([fixes](fix.md#modes)).

## Risk levels, enforced in code

Each agent tool declares a fixed risk level; the model cannot choose or
change it. The policy gate in `agent` decides before a tool runs:

| Level | Examples | `ask` | `auto` |
| --- | --- | --- | --- |
| `read` | list runs, read logs, read files, edit the fixer's in-memory copy | runs | runs |
| `write` | rerun a job, dispatch a workflow, cancel a run | confirm | runs within budget |
| `critical` | push a fix branch and open a draft pull request | confirm, with the diff | runs within budget, unless the diff has a warning |

Edits are `read` because they change only memory: nothing is cloned or
written to disk, and nothing leaves the machine until the push, which you
confirm once with the full diff.

The gate lives in code, not in prompts or the UI, so a prompt injection or a
UI bug cannot skip it.

## Confirmations show facts from code

A confirmation shows an action request that code builds from the validated
arguments and GitHub's data: repository, workflow, run, ref, commit, and how
much of the budget is used. It never shows text the model wrote, so a
manipulated model cannot dress up an action. Write tools only accept targets
the scan found or flakipype started itself. Every request is written to an
append-only audit log, together with your answer. Details for reruns and
dispatches: [actions](actions.md).

## Logs are data

Job logs, workflow files, source code and issue or PR text can contain text
written by anyone. They are always passed to the model marked as data, never
as instructions. Actions come only from your request or the configured mode.

## Secrets stay local

Everything sent to the model passes secret masking first
(`agent/masking.py`): the configured API key itself, GitHub, Anthropic, AWS
and Slack tokens, JWTs, private key blocks, credentials in URLs, bearer
tokens and `password=`/`token:`-style assignments become `[masked: …]`.
GitHub's own `***` stays as it is. The API key is stored in the system
keyring, or a `0600` file where no keyring exists; the GitHub token stays in
`gh`'s own login.

## Budgets

Each run has hard, configurable limits with safe defaults: reruns and
dispatches (10 per chat session, `actions.max_per_session`), runs watched at
once, pull requests (3 per chat session, `fix.max_prs_per_session`, M5),
files and lines per fix, tokens and wall-clock time, plus loop detection. Reaching a limit
ends the run with a summary of what was done and what is left — never a
half-finished state without explanation. No limit is unlimited by default.

## Verified downloads

The `gh` binary that flakipype downloads is verified against the SHA-256 in
the release's checksum file before first use; a mismatch aborts.
