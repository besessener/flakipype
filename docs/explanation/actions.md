# Actions: reruns, dispatches and the live run view

> Status: implemented in M4.

Scans and investigations only read. Some questions can only be answered by
running CI again: does the failed E2E job pass on a rerun of the same
commit? How often does the workflow fail if it runs five times in a row?
The chat can start runs to answer them. You confirm each one, and the chat
shows them live while they run.

## Scope

- **In**: in the chat, rerunning the failed jobs of a run, rerunning a whole
  run, dispatching a workflow (`workflow_dispatch`) on an existing branch or
  tag, and cancelling runs flakipype started. A live list shows them, an
  audit log records them, and a budget limits them.
- **Out**: headless actions (`flakipype run --auto`, M6); changing code,
  branches or pull requests, and `/mode auto` in the chat (M5, see
  [fixes](fix.md)).

None of these actions writes to a branch: reruns and dispatches run the code
that is already there. They cost CI minutes, not model tokens. In
repositories with deployments, a dispatch can do whatever the workflow does,
which is why each one needs your confirmation.

## The actions

| Action | Tool / command | GitHub API (through `gh api`) | Risk |
| --- | --- | --- | --- |
| Rerun the failed jobs of a run | `rerun_failed` · `/rerun N` | `POST …/actions/runs/{id}/rerun-failed-jobs` | `write` |
| Rerun a whole run | `rerun_run` · `/rerun N --all` | `POST …/actions/runs/{id}/rerun` | `write` |
| Dispatch a workflow on a ref | `dispatch` · `/dispatch N [ref] [xK]` | `POST …/actions/workflows/{file}/dispatches` | `write` |
| Cancel a run flakipype started | `cancel` · `/cancel R` | `POST …/actions/runs/{id}/cancel` | `write` |
| Show the started runs | `watched_runs` · `/runs` | none; the state comes from polling | `read` |
| List this session's action requests | `/actions` | none; read from the audit log | – |

`N` is a finding number, as everywhere in the chat:

- `/rerun N` reruns the finding's newest run that is still failing.
- `/rerun N --all` reruns the finding's newest run, whatever its result.
- `/dispatch N` dispatches the finding's workflow on the repository's
  default branch, or on `ref` if you give one. `xK` repeats it K times
  (1–10), and each repeat counts against the budget.

`R` is the short number a started run gets in the Runs list (`R1`, `R2`, …).
The model's tools can also name a specific run id, but only one of the
finding's runs.

The model gets the same tools. The checks run in code (`actions` package),
so the model cannot point the tools anywhere it likes:

- **Only what the scan found.** Reruns accept only runs of the finding in the
  current scan. Dispatches accept only the finding's workflow, and only if
  its workflow file at that ref declares `workflow_dispatch` without required
  inputs that have no default. The file is read with a YAML parser.
  flakipype never sends inputs.
- **Only finished runs.** GitHub reruns only completed runs. A rerun of
  failed jobs needs a run whose newest attempt failed.
- **Only existing refs.** The ref must be an existing branch or tag of the
  repository. flakipype creates nothing.
- **Only its own runs are cancelled.** Cancel accepts only runs started in
  this session that have not finished. It never cancels runs someone else
  started.
- **Only the configured owner and host.**

## Confirmation

The chat stays in `ask` mode, so every `write` action waits for you. Each
action tool returns a *prepared action*: an action request plus the code that
runs it. The gate passes the request to the confirmation function and runs
the action only on "yes". Code builds the request from the validated
arguments and GitHub's answers, never from text the model wrote:

```text
╭──────────────────────────────────────────────────────────────────────────╮
│ Rerun failed jobs?                                                       │
│                                                                          │
│ octo-org/app · CI · run 6 (attempt 1 → 2)                                │
│ commit 3f2a9c1 on main · failed jobs: lint                               │
│ Actions this session: 1 of 10                                            │
│                                                                          │
│                          Run           Don't run                         │
╰──────────────────────────────────────────────────────────────────────────╯
```

**Don't run** has the focus, and Escape also declines. The agent waits until
you answer. A declined request goes back to the model as declined by the
user. For the rest of that turn the model gets an error for any other
`write` tool, so it cannot ask again in the same question. A `/rerun` or
`/dispatch` you type yourself also shows the dialog: the gate does not know
who asked, and that is intended.

In code, a tool's risk level is fixed. A `write` or `critical` tool that
returns plain text instead of a prepared action is a programming error
(`TypeError`), so a tool cannot skip the gate. Without a window to ask in
(headless commands), the confirmation function declines everything.

## Budget

| Limit | Default | Setting |
| --- | --- | --- |
| Reruns and dispatches per chat session | 10 | `actions.max_per_session` (1–100) |
| Runs watched at the same time | 10 | `actions.max_watched` (1–50) |
| How long a run is watched | 6 hours | `actions.watch_hours` (1–24) |

Every started rerun and every started repeat of a dispatch counts once;
cancelling does not. The count is part of the session, so `/resume` does not
reset it, but `/new` does. A request that does not fit the budget or the
watch limit fails with a message before any dialog is shown, for example
"Action budget used up: 10 of 10 reruns and dispatches in this session".

## The live run view

The sidebar shows a second list, **Runs**, under the findings, as soon as a
run was started. Each run shows its repository, workflow, label and state:
`queued`, `in progress` with failed (`✗`) and running (`⟳`) jobs,
`✓ passed`, `✗ failed`, `cancelled`, or `no longer watched`.

```text
Runs
R1 app · CI #6/2
  ✓ passed
R2 app · E2E dispatch 1/3
  in progress · e2e ⟳
R3 app · E2E dispatch 2/3
  queued
```

- Unfinished runs are polled every 10 seconds in the background, through the
  same serial `gh` queue as everything else. A run is polled until it
  finishes or its watch time is over.
- **Finding the run.** A rerun keeps its run id and waits for the next
  attempt number. A dispatch gets the new run's id from GitHub. On GitHub
  Enterprise Server versions that do not return it, flakipype looks for
  `workflow_dispatch` runs on that ref by the logged-in user since the
  dispatch, and takes the oldest one no other started run has claimed.
- **When a run finishes**, a note in the conversation says so, for example
  "R1: E2E passed on attempt 2 (failed on attempt 1): a proven flaky event".
  `watched_runs` gives the model the same facts. The next scan picks the run
  up like any other, so a passing rerun becomes evidence of flakiness
  without new detection rules.
- When all runs of a repeated dispatch have finished, a note sums them up:
  "E2E on 3f2a9c1: 2 of 3 passed".
- A rate limit pauses the round: the runs show "waiting for GitHub's rate
  limit", and the next poll tries again. Other errors show next to the run
  and do not stop the others.

Started runs, their state and the budget count are saved in the session. A
resumed session polls the runs that have not finished.

## Audit log

Every action request is stored in the cache database (table `action_log`),
whether it ran or not. Each entry holds the time, session, tool, who asked
(`model` or `command`), the request text, your answer (`confirmed` or
`declined`), the outcome (GitHub's answer or the error) and the run id.
`/actions` lists this session's entries. The log is append-only: nothing in
flakipype updates or deletes it, apart from deleting the cache file.

## Permissions and errors

Rerunning, dispatching and cancelling need write access to Actions. A classic
token or a `gh auth login` needs the `repo` scope, which is the default. A
fine-grained token needs **Actions: read and write**. `doctor` reports
missing scopes where GitHub shows them (classic tokens). Otherwise a `403`
explains which permission is missing, and nothing is retried.

Other GitHub errors become tool errors with GitHub's message, so the model
and you see what went wrong.

## Safety, summarised

- No branch, tag, file or pull request is created or changed. The
  default-branch rule is untouched.
- Every action is confirmed in a dialog. The gate enforces this in code, and
  the dialog text comes from code.
- Targets are limited to what the scan found and what flakipype started.
- A per-session budget, a watch limit, an audit log, and loop detection as
  for every tool.
- Logs of rerun jobs are data, like all logs.

## Testing

- The gate: requests per risk level, confirm and decline, no second request
  after a decline, and writing tools that return text.
- The `actions` package against an in-memory GitHub: targets outside the
  scan, refs, dispatchable workflows, the budget and the watch limit, audit
  entries, polling with a fake clock (state changes, dispatched runs without
  an id, watch time, rate limits), and session state.
- `RunControl` against the `gh` stub with recorded responses: reruns,
  dispatch (with a run id, and without one plus the search), cancel, `403`.
- The chat commands and the model's tool use with the scripted fake model,
  including a declined request.
- The confirmation dialog and the Runs list: Pilot tests and snapshots.
