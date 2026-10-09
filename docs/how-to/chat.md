# Use the chat

Run `flakipype` without a command to open the chat: a conversation on the
left, the findings of the current scan on the right. Ask questions in plain
language or use slash commands. Scans and investigations only read. Reruns
and dispatches start CI runs, and only after you confirm each one; no code,
branch or pull request changes.

It needs a terminal and a model (see [connect a model](connect-a-model.md)).
Without a terminal, `flakipype` prints its help instead.

## A typical session

```text
/scan                  scan with the configured window; findings appear on the right
why does the E2E test of Archivist fail?
/why 2                 the verdict for finding 2, with its evidence
/rerun 2               rerun its failed jobs; confirm in the dialog, watch it under Runs
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
| `/rerun N [--all]` | Rerun the failed jobs of finding N's newest failing run; `--all` reruns all jobs of its newest run |
| `/dispatch N [ref] [xK]` | Start finding N's workflow on the default branch or `ref`, K times (1–10) |
| `/runs` | The runs started in this session and their state |
| `/cancel R` | Cancel run R (`R1`, `R2`, …) started in this session |
| `/actions` | The reruns, dispatches and cancels requested in this session |
| `/budget` | Tokens used in this session |
| `/sessions` | The ten most recent sessions |
| `/resume N` | Continue session N; the next action scans again |
| `/new` | Start a new session |
| `/help` | The list of commands |
| `/quit`, `/exit`, Ctrl+Q | Leave |

## Sessions

Every message is saved: the conversation, the model's history, the scan
options, the findings list, the started runs and the action budget. Sessions live in the cache database next to
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
