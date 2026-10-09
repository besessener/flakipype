# Actions: reruns, dispatches and the live run view

> Status: design for M4, not implemented yet. Where the implementation will
> differ, this page will be updated to describe the implementation.

Scans and investigations only read. Some questions can only be answered by
running CI again: does the failed E2E job pass on a rerun of the same
commit? How often does the workflow fail if it runs five times in a row?
M4 lets the chat start runs to answer them, with your confirmation for each
one, and shows them live while they run.

## Scope of M4

- **In**: in the chat, rerunning the failed jobs of a run, rerunning a whole
  run, dispatching a workflow (`workflow_dispatch`) on an existing branch or
  tag, and cancelling runs flakipype started. A live panel shows them, an
  audit log records them, and a budget limits them.
- **Out**: headless actions (`flakipype run --auto`, M6); changing code,
  branches or pull requests (M5); `/mode auto` in the chat (with M5, when
  draft pull requests exist).

None of these actions writes to a branch: reruns and dispatches run the code
that is already there. They cost CI minutes, not model tokens, and in
repositories with deployments a dispatch can do whatever the workflow does,
which is why each one needs your confirmation.

## The actions

| Action | Tool / command | GitHub API (through `gh api`) | Risk |
| --- | --- | --- | --- |
| Rerun the failed jobs of a run | `rerun_failed` · `/rerun N` | `POST …/actions/runs/{id}/rerun-failed-jobs` | `write` |
| Rerun a whole run | `rerun_run` · `/rerun N --all` | `POST …/actions/runs/{id}/rerun` | `write` |
| Dispatch a workflow on a ref | `dispatch` · `/dispatch N [ref] [xK]` | `POST …/actions/workflows/{id}/dispatches` | `write` |
| Cancel a run flakipype started | `cancel` · `/cancel R` | `POST …/actions/runs/{id}/cancel` | `write` |
| Show the started runs | `watched_runs` · `/runs` | `GET …/actions/runs/{id}` and its jobs | `read` |

`N` is a finding number, as everywhere in the chat. `/rerun N` reruns the
finding's newest failed run. `/dispatch N` dispatches the finding's
workflow on the repository's default branch, or on `ref`; `xK` repeats it K
times (each counts against the budget). `R` is the short number a started run
gets in the live panel.

The model gets the same tools. The gate checks their arguments; the model
cannot point them anywhere it likes:

- **Only what the scan found.** Reruns accept only run ids from the current
  scan's findings. Dispatches accept only a finding's workflow, and only if
  its workflow file at that ref declares `workflow_dispatch` without required
  inputs that have no default. flakipype never sends inputs.
- **Only existing refs.** The ref must be an existing branch or tag of the
  repository. flakipype creates nothing.
- **Only its own runs are cancelled.** Cancel accepts only runs started in
  this session, never runs someone else started.
- **Only the configured owner and host.**

## Confirmation

The chat stays in `ask` mode, so every `write` action waits for you. The gate
calls a confirmation function with an **action request** that code builds
from the validated arguments and GitHub's data, never from text the model
wrote:

```text
╭─ Rerun failed jobs? ───────────────────────────────────────────────╮
│ besessener/Archivist · E2E · run 1234567890 (attempt 1 → 2)        │
│ commit 3f2a9c1 on main · failed jobs: e2e                          │
│ Reruns this session: 3 of 10                                       │
│                                                                    │
│                         [ Run ]  [ Don't run ]                     │
╰────────────────────────────────────────────────────────────────────╯
```

The agent waits until you answer. **Don't run** goes back to the model as
"declined by the user" and is never retried in the same question. A
`/rerun` or `/dispatch` you type yourself still shows the dialog: the gate
does not know who asked, and that is intended.

`PolicyGate` changes from "confirm this tool" to "confirm this request".
Tools with a `write` or `critical` risk level must describe their request;
the registry refuses one that does not.

## Budget

| Limit | Default | Setting |
| --- | --- | --- |
| Reruns and dispatches per chat session | 10 | `actions.max_per_session` (1–100) |
| Runs watched at the same time | 10 | `actions.max_watched` (1–50) |
| How long a run is watched | 6 hours | `actions.watch_hours` (1–24) |

Every rerun and every repeat of a dispatch counts once; cancelling does not.
The count is part of the session, so `/resume` does not reset it, but `/new`
does. At the limit, the tool returns "action budget used up" and the
dialog is never shown.

## The live run view

The sidebar gets a second list, **Runs**, under the findings. Each started
run shows its repository, workflow, attempt, state and its jobs as they
finish (`queued`, `in progress`, `✓`, `✗`, `cancelled`):

```text
Runs
R1 Archivist · E2E #1234567890/2   ✓ passed (6m 12s)
R2 Archivist · E2E dispatch 1/3     in progress · e2e ⟳
R3 Archivist · E2E dispatch 2/3     queued
```

- Runs are polled every 10 seconds, one at a time through the same serial
  `gh` queue as the scan. A run is polled only until it finishes or its watch
  time is over.
- **Finding the run.** A rerun keeps its run id and gets the next attempt
  number. A dispatch returns the new run's id from GitHub; on GitHub
  Enterprise Server versions that do not, flakipype looks for the
  `workflow_dispatch` run on that ref created by the logged-in user after the
  dispatch.
- **When a run finishes**, a note in the conversation says so with the
  result, for example "R1: E2E passed on attempt 2 (failed on attempt 1): a
  proven flaky event". `watched_runs` gives the model the same facts, and the
  next scan picks the run up like any other, so a passing rerun becomes
  evidence of flakiness without any new detection rules.
- For a repeated dispatch, the note sums up: "E2E on 3f2a9c1: 2 of 3 passed".

Started runs and their state are saved in the session. A resumed session
polls the runs that have not finished.

## Audit log

Every action request is stored in the cache database, whether it ran or not:
time, session, tool, who asked (model or command), the request, your answer,
GitHub's answer and the run id. `/actions` lists this session's entries. The
log is append-only. Nothing in flakipype deletes it, apart from deleting
the cache file.

## Permissions and errors

Rerunning, dispatching and cancelling need write access to Actions. A classic
token or a `gh auth login` needs the `repo` scope, which is the default. A
fine-grained token needs **Actions: read and write**. `doctor` reports
missing scopes where GitHub shows them (classic tokens). Otherwise the first
`403` explains which permission is missing, and nothing is retried.

Other errors work like in the scan: typed exceptions, shown in the chat with
a next step. A rate limit stops polling until the reset time. The panel
shows that the run is waiting.

## Safety, summarised

- No branch, tag, file or pull request is created or changed. The
  default-branch rule is untouched.
- Every action is confirmed in a dialog. The gate enforces this in code, and
  the dialog text comes from code.
- Targets are limited to what the scan found and what flakipype started.
- A per-session budget, an audit log, and loop detection as for every tool.
- Logs of rerun jobs are data, like all logs.

## Testing

- The gate: requests per risk level, confirm and decline, the budget, and
  arguments outside the scan.
- The tools against the `gh` stub with recorded responses: rerun, dispatch
  (200 with a run id, and 204 with a run found by search), cancel, `403`, and
  rate limits.
- Polling with a fake clock: state changes, watch time, resume.
- The confirmation dialog and the Runs panel: Pilot tests and a snapshot.
- The chat model's tool use with the scripted fake model, including a
  declined request.
