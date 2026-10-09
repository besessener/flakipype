# Investigate findings

`flakipype investigate` scans, then lets the agent look into findings and
explain each one with evidence: what causes it, whether it is a flaky test,
flaky infrastructure, a real bug, a configuration problem or already fixed,
and what to change. It only reads; nothing in your repositories changes.

It needs a model (see [connect a model](connect-a-model.md)) and costs model
tokens: with the default limits at most 200,000 per finding and 1,000,000 per
run.

## Run it

```bash
flakipype scan                     # note the numbers of the findings
flakipype investigate              # the flaky jobs and the recurring errors
flakipype investigate --finding 3  # one finding; repeat --finding for more
flakipype investigate --all        # also "seen once" and "fixed"
```

Each result shows the classification and confidence, a short summary, the
cause, a suggested fix, the evidence with quotes (log lines, commits, files)
and counter-evidence, open questions, and how the review went:

```text
╭─ #1 octo-org/app › CI › test ──────────────────────────────────────────────╮
│ flaky test · confidence high                                               │
│                                                                            │
│ The E2E test asserts the row count before the second row is rendered.      │
│                                                                            │
│ Cause: …                                                                   │
│ Suggested fix: …                                                           │
│                                                                            │
│ Evidence                                                                   │
│  • log job 112720402394 lines 1010-1016: “Expected: 2 Received: 1 …”       │
│    …                                                                       │
╰─ flaky · review: accepted: … · 41,230 tokens, 6 rounds ────────────────────╯
```

These are the model's assessments. Every quote was checked against what the
tools returned, and a second model pass reviewed the reasoning, but they are
judgements, not the scan's proven facts.

## Repeated runs reuse verdicts

A completed verdict is stored and reused until the finding has a newer
failure. `--fresh` investigates again. Failed investigations (a limit was
reached, no verdict) are never stored.

## Options and output

| Option | Meaning |
| --- | --- |
| `--finding N` | Investigate finding N (numbers from `flakipype scan`); repeatable |
| `--all` | Every finding instead of flaky jobs and recurring errors |
| `--fresh` | Ignore stored verdicts |
| `--days`, `--repo`, `--owner` | As for `flakipype scan` |
| `--json` | Results as JSON on stdout, with the full scan under `scan` |

Exit codes: 0 all investigations completed, 1 one ended without a verdict or
the scan stopped early, 2 not set up.

To ask follow-up questions instead, use [the chat](chat.md). Limits are in
the `[agent]` section of the
[configuration](../reference/configuration.md). How it works:
[the agent](../explanation/agent.md).
