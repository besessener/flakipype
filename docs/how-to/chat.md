# Use the chat

Run `flakipype` without a command to open the chat: a conversation on the
left, the findings of the current scan on the right. Ask questions in plain
language or use slash commands. Scans and investigations only read. Reruns,
dispatches and fixes run only after you confirm each one (or within the
budgets in `/mode auto`); a fix becomes a new branch and a draft pull
request, never a change to the default branch.

It needs a terminal and a model (see [connect a model](connect-a-model.md)).
Without a terminal, `flakipype` prints its help instead.

## A typical session

```text
/scan                  scan with the configured window; findings appear on the right
why does the E2E test of Archivist fail?
/why 2                 the verdict for finding 2, with its evidence
/rerun 2               rerun its failed jobs; confirm in the dialog, watch it under Runs
/fix 2                 a fix as a draft pull request; review the diff in the dialog
```

The chat model scans, lists findings and starts investigations itself when a
question needs them. The line above the input shows what it is doing.
Selecting a finding in the sidebar (arrow keys and Enter, or a click) puts
`/investigate N` into the input, or `/why N` once it has a verdict; nothing
starts until you press Enter, because investigations cost tokens.

## Commands

| Command | Does |
| --- | --- |
| `/scan [days]` | Scan the workflow runs and number the findings |
| `/findings`, `/flaky` | List the findings of the current scan |
| `/investigate N [N …]` | Investigate findings by number; `all` for the flaky jobs and recurring errors; `--fresh` ignores stored verdicts |
| `/why N` | Show the verdict for finding N (investigates it first if needed) |
| `/fix N [--fresh]` | Write a fix for finding N and, once you confirm, push it as a draft pull request; `--fresh` drops a fix that was shown but not pushed |
| `/rerun N [--all]` | Rerun the failed jobs of finding N's newest failing run; `--all` reruns all jobs of its newest run |
| `/dispatch N [ref] [xK]` | Start finding N's workflow on the default branch or `ref`, K times (1–10) |
| `/runs` | The runs started in this session and their state |
| `/cancel R` | Cancel run R (`R1`, `R2`, …) started in this session |
| `/actions` | The actions (reruns, dispatches, cancels, fixes) requested in this session |
| `/mode ask\|auto` | Confirm every action (`ask`, the default), or let them run within the budgets (`auto`); `/mode` shows the mode |
| `/budget` | Tokens used in this session |
| `/sessions` | The ten most recent sessions |
| `/resume N` | Continue session N; the next action scans again |
| `/new` | Start a new session |
| `/help` | The list of commands |
| `/quit`, `/exit`, Ctrl+Q | Leave |

## Sessions

Every message is saved: the conversation, the model's history, the scan
options, the findings list, the started runs, the action budget, fixes
that were shown but not pushed, and opened pull requests with their
verification. The mode is not saved. Sessions live in the cache database next to
the scan cache (see [configuration](../reference/configuration.md)).

## Limits

Each question to the chat model has the per-investigation limits (12 rounds,
200,000 tokens, 5 minutes of model time); every investigation it starts has
its own. When a limit is reached, the chat says so and you can ask again.
Limits are in the `[agent]` section of the configuration. How it works:
[the agent](../explanation/agent.md).

## Reruns and dispatches

`/rerun`, `/dispatch` and `/cancel`, and the same requests from the chat
model, open a dialog that says exactly what will run. **Run** starts it;
**Don't run** (the default, also Escape) does nothing, and the model does not
ask again in that turn. Started runs appear under **Runs** in the sidebar
and are polled every 10 seconds. When one finishes, a note says how it
ended, for example "R1: E2E passed on attempt 2 (failed on attempt 1): a
proven flaky event".

A session allows 10 reruns and dispatches by default; `/new` starts a new
count. Limits are in the `[actions]` section of the
[configuration](../reference/configuration.md). The rules behind it:
[actions](../explanation/actions.md).

## Fixes

`/fix N`, or asking the chat to fix a finding, works for findings whose
reviewed verdict is a flaky test, flaky infrastructure or a configuration
problem; without a verdict it investigates first. A fixer agent edits an
in-memory copy of the default branch, code checks the diff and a reviewer
reads it. Then a dialog shows the facts, the model's explanation and the
whole diff: **Push** creates a branch `flakipype/fix-…`, one signed commit
and a draft pull request, and reruns the workflow on the fix branch;
**Don't push** (the default, also Escape) keeps the fix in the session.
Ask the chat for changes ("keep the assertion") and it revises that fix;
`/fix N --fresh` starts over. The verification result arrives as a note and
as a comment on the pull request. Merging is always up to you.

The status line shows the mode. In `/mode auto`, actions run without a
dialog within the budgets, and a fix with warnings (it hides failures,
reaches out, or changes `.github/`) is not pushed. A session allows 3 pull
requests by default (`[fix]` in the
[configuration](../reference/configuration.md)). How it works:
[fixes](../explanation/fix.md).
