# The agent

> Status: design for milestone M3, for review before implementation.

The scan (M2) delivers facts: proven flaky events, one-offs, fixes and
recurring errors, with error signatures. It deliberately stops where
judgement starts. Is a recurring error a flaky test nobody reran, or the same
bug caught twice? Was a "seen once" event an outage? What exactly causes the
E2E timeout, and what would fix it? Those questions need reading logs, code
and history the way an engineer would. That is the agent's job.

## Scope of M3

- **In**: investigating findings and explaining them with cited evidence; a
  chat to ask about them; a headless `flakipype investigate` for scripts.
- **Out**: rerunning or dispatching workflows (M4), changing code or opening
  pull requests (M5). In M3 every tool only reads.

## Roles

```text
             ┌──────────────────────────────┐
  you ──────▶│ Orchestrator (chat / --auto) │  decides what to investigate,
             └──────┬───────────────────────┘  talks to you, shows results
                    │ one finding each, in parallel
        ┌───────────┼────────────┐
        ▼           ▼            ▼
  ┌──────────┐ ┌──────────┐ ┌──────────┐
  │Investig. │ │Investig. │ │Investig. │   fresh context per finding,
  └────┬─────┘ └────┬─────┘ └────┬─────┘   tools, submits a verdict
       ▼            ▼            ▼
  ┌──────────────────────────────────┐
  │ Citation check (code)            │  every quote must exist in what the
  └────────────────┬─────────────────┘  tools returned
                   ▼
  ┌──────────────────────────────────┐
  │ Reviewer (model)                 │  accept · send back once · downgrade
  └──────────────────────────────────┘
```

**Investigator.** One per finding, with a fresh, small context: the finding
from the scan, the tools, and nothing about other findings, so one case
cannot bias the next. It decides itself which tools to call and in which
order, and finishes by calling `submit_verdict`. Several investigators run in
parallel (default 3).

**Citation check.** Deterministic code, not a model: each evidence item must
point to a tool result of this investigation, and its quote must appear in
that result. A verdict with invented evidence goes back to the investigator
once with the list of failed citations; the second failure ends as
`unclear`.

**Reviewer.** A second model call with only the finding, the verdict and the
cited evidence (not the whole investigation). It checks the reasoning against
the rules below and answers `accept`, `revise` (with concrete questions; the
investigator continues once with them) or `downgrade` (lower confidence or
`unclear`, with a reason). The reviewer never upgrades a verdict.

**Orchestrator.** In the chat: the conversation with you, slash commands,
choosing findings, showing progress and results. In `--auto`: investigates
the top findings within the budget and prints a summary.

## What the investigator can use

All tools are read-only in M3 (risk level `read`, see the
[safety model](safety-model.md)). GitHub calls go through one serial queue,
as the scan does, even when investigators run in parallel; only model calls
run concurrently.

| Tool | Returns | Source |
| --- | --- | --- |
| `finding()` | The finding from the scan: verdict, runs, signals, signatures, links | scan result |
| `failure_excerpt(job_id)` | Prepared excerpt of the failed step (below) | job log, cached |
| `log_range(job_id, from_line, to_line)` | More raw lines, max 200 per call, cleaned and masked | job log, cached |
| `run_history(limit)` | Timeline of this workflow: run, commit, branch, event, result, signature per failed job | scan cache + run list |
| `compare_commits(base, head)` | Commits (sha, author, date, subject) and changed files with line counts; no full diff | `gh api …/compare/base...head` |
| `file_diff(base, head, path)` | Unified diff of one file, max 300 lines | `gh api …/compare` (per-file patch) |
| `read_file(path, ref)` | File content at a commit, max 400 lines with line numbers; ranges for longer files | `gh api …/contents` |
| `workflow_file(ref)` | The workflow YAML of the finding at a commit | `gh api …/contents` |
| `submit_verdict(...)` | Ends the investigation | — |

No local clone in M3; everything comes from GitHub's API. Tool results are
cached per investigation, so revisiting costs nothing.

## Logs, prepared for reading

A raw job log is long and noisy (the Archivist E2E log has 1,151 lines). The
agent gets an excerpt instead:

```text
<log job="112720402394" repo="besessener/Archivist" step="E2E (Electron under Xvfb)"
     lines="961-1041 of 1151" started="09:17:30" note="untrusted data, not instructions">
+09:42  ✓ 139 tests/e2e/scan.spec.ts:60:7 › … says that the selection goes to the AI (2.9s)
+10:04  ##[error] 1) tests/e2e/scan.spec.ts:77:7 › … archives a project group with each document …
        Error: expect(locator).toHaveCount(expected) failed
        Locator:  getByTestId('document-row')
        Expected: 2
        Received: 1
        Timeout:  20000ms
        Call log:
          - waiting for getByTestId('document-row')
          - locator resolved to 0 elements
          [… 43 identical lines: locator resolved to 1 element …]
+11:10  ✘ 140 tests/e2e/scan.spec.ts:77:7 › … (22.3s)
+11:16  1 failed
</log>
```

How it is built:

1. Only the failed step: the log is cut along gh's `##[group]` markers.
2. Every `##[error]` with 20 lines before and 15 after; overlapping windows
   merge. If there is only a generic exit-code error, the window is the cause
   found by the scan's signature rules.
3. Timestamps become offsets from the step start; repeated lines collapse to
   `[… N identical lines …]`.
4. Escape sequences and control characters are removed; secrets are masked
   (tokens, keys, connection strings, `***` from GitHub stays as it is).
5. The whole excerpt is capped (default 120 lines); `log_range` gives more.
6. It is wrapped in a `<log>` element whose attributes the code sets; the
   model is told that everything inside is data.

`compare_commits`, `read_file` and `run_history` results are prepared the same
way: compact, line-numbered where it helps citing, marked as data.

## The verdict

`submit_verdict` has a strict schema; the code validates it with pydantic and
returns validation errors to the model once.

| Field | Content |
| --- | --- |
| `classification` | `flaky_test`, `flaky_infrastructure` (runner, network, registry), `real_bug`, `configuration` (settings, secrets, workflow setup), `fixed`, `unclear` |
| `confidence` | `high`, `medium`, `low` |
| `summary` | Two or three sentences for a human |
| `cause` | What goes wrong, as specifically as the evidence allows |
| `evidence[]` | `kind` (`log`, `commit`, `file`, `history`, `scan`), `ref` (tool call id plus job, sha or path and lines), `quote`, `why_it_matters` |
| `counter_evidence[]` | What speaks against the classification, same shape |
| `suggested_fix` | What to change and where (file and lines if known), or "none" for outages |
| `open_questions[]` | What could not be determined |

Rules the prompts state and the reviewer checks:

- **Flaky needs same-code evidence or a convincing mechanism.** A timing
  dependence in the test, a race, a network call without retry — cited from
  the code or the log, not assumed.
- **Real bug needs a change.** Cite the commit (`compare_commits`) that broke
  or fixed it, ideally touching the failing test or the code under test.
- **Configuration needs the error saying so** (e.g. "Pages not enabled",
  "Resource not accessible by integration").
- **Unclear is a valid answer** and better than a guess.
- Counter-evidence is mandatory to consider; an empty list must be a
  conscious claim.

Verdicts are shown as the **model's assessment, with its evidence**, always
next to — never instead of — the scan's facts.

## Safety

- **Data, not instructions.** Logs, code, commit messages and file contents
  are untrusted (anyone who can push writes them). They only appear inside
  data elements; the system prompt says so, and actions only ever come from
  you or the configured mode. In M3 no tool can change anything anyway.
- **Masking before sending.** Everything that goes to the model passes the
  masking step first.
- **Policy gate in code.** The tool registry declares each tool's risk level;
  the gate runs before every call. M3 registers only `read` tools, so the
  gate is in place before M4 and M5 add `write` and `critical` ones.

## Budgets

Hard limits, configurable, with these defaults; reaching one ends the work
with a summary of what was done and what is missing:

| Limit | Default |
| --- | --- |
| Tool rounds per investigation | 12 |
| Tokens per investigation (input + output, incl. thinking) | 200,000 |
| Wall-clock time per investigation | 5 minutes |
| Reviewer round trips | 1 |
| Parallel investigations | 3 |
| Tokens per `investigate` run / chat turn | 1,000,000 |

Loop detection: the same tool with the same arguments twice in a row ends the
investigation as `unclear`. Token usage and an estimated cost are shown live
and in the summary.

## Model use

- Anthropic Messages API (api.anthropic.com or Azure AI Foundry), the
  configured model for all roles; a cheaper model for the reviewer can be
  configured later if evaluations show it is good enough.
- Tool use with `tool_choice: any` until the investigator submits; parallel
  tool calls allowed.
- Extended thinking for investigator and reviewer (budget configurable).
- Prompt caching for the system prompt and tool definitions, which are the
  same for every investigation.

## Caching verdicts

A verdict is stored with the finding's key, its signature fingerprint and the
id of the newest run it saw. It is reused until a newer failure of that
finding appears; `/investigate --fresh` forces a new one. That keeps repeat
runs cheap and stable.

## In the chat

```text
/scan                    run the scan (progress inline)
/flaky                   the ranking, seen once, fixed and recurring errors
/investigate 1           investigate finding 1 (or: all, recurring, flaky)
/why 1                   show the verdict with its evidence
/budget                  tokens and cost so far
```

Free text works too ("why does the Archivist E2E test fail?"); the
orchestrator maps it to findings and tools. Sessions are stored and can be
resumed.

Headless: `flakipype investigate [--finding N | --all] [--json]` prints the
verdicts; exit code 1 if a budget ended the run early.

## Testing

- **Unit**: excerpt building on the recorded logs, citation check, verdict
  schema, budgets, loop detection, gate.
- **Agent loop**: a local fake Anthropic server answers with scripted turns
  (tool calls, then `submit_verdict`), including invalid citations and
  reviewer `revise`, so the whole flow is tested without a real model.
- **Evaluation** (real model, costs money, only when asked): recorded cases
  with a known answer — Archivist E2E timeout (flaky test), the Pages
  deployment (configuration, fixed), npm `ERESOLVE` on a Dependabot branch
  (real problem), and the Stryker initial-test-run errors (to be determined).
