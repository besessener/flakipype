# Use the chat

Run `flakipype` without a command to open the chat: a conversation on the
left, the findings of the current scan on the right. Ask questions in plain
language or use slash commands. Everything in the chat only reads; nothing in
your repositories changes.

It needs a terminal and a model (see [connect a model](connect-a-model.md)).
Without a terminal, `flakipype` prints its help instead.

## A typical session

```text
/scan                  scan with the configured window; findings appear on the right
why does the E2E test of Archivist fail?
/why 2                 the verdict for finding 2, with its evidence
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
| `/budget` | Tokens used in this session |
| `/sessions` | The ten most recent sessions |
| `/resume N` | Continue session N; the next action scans again |
| `/new` | Start a new session |
| `/help` | The list of commands |
| `/quit`, `/exit`, Ctrl+Q | Leave |

## Sessions

Every message is saved: the conversation, the model's history, the scan
options and the findings list. Sessions live in the cache database next to
the scan cache (see [configuration](../reference/configuration.md)).

## Limits

Each question to the chat model has the per-investigation limits (12 rounds,
200,000 tokens, 5 minutes of model time); every investigation it starts has
its own. When a limit is reached, the chat says so and you can ask again.
Limits are in the `[agent]` section of the configuration. How it works:
[the agent](../explanation/agent.md).
