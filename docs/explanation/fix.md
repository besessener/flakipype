# Fixes: from verdict to draft pull request

> Status: design for M5, not implemented yet.

An investigation explains a flaky finding and suggests a fix. M5 lets the
agent write that fix, shows you the diff, pushes it as a new branch, opens a
draft pull request and reruns the fix branch to check whether it holds.
Merging stays your decision.

## Scope

- **In**: `/fix N` and a `fix` tool in the chat; a fixer agent that edits
  an in-memory copy of the repository; deterministic checks of the diff; one
  confirmation for push, pull request and verification; a branch plus one
  signed commit through GitHub's API; a draft pull request; verification
  reruns with a result comment; `/mode ask|auto` in the chat.
- **Out**: headless fixes (`flakipype run --auto`, M6); forks (a fix needs
  push access to the repository); deleting files; updating a pull request
  after it was opened; merging, ever.

## The flow

```text
/fix 2 ──▶ verdict? ──no──▶ investigate first
              │ flaky_test · flaky_infrastructure · configuration, reviewed
              ▼
        ┌───────────┐  read tools + edit tools on an in-memory copy
        │  Fixer    │  of the default branch at one pinned commit
        └─────┬─────┘
              ▼ submit_fix(title, explanation)
        ┌───────────┐
        │ Checks    │  size caps, parse, warnings (code)
        └─────┬─────┘
              ▼
        ┌───────────┐
        │ Reviewer  │  does the diff fix the cause without hiding it? (model)
        └─────┬─────┘
              ▼ critical: one confirmation (ask) or the auto rules
   branch + commit ──▶ draft pull request ──▶ verification runs ──▶ PR comment
```

1. **Which findings.** `/fix N` needs a reviewed verdict classified
   `flaky_test`, `flaky_infrastructure` or `configuration`. Without a verdict
   it investigates first. `real_bug`, `fixed`, `unclear` and unreviewed
   verdicts are refused with the reason. If an open flakipype pull request
   for the finding exists, `/fix` links it instead of opening a second one.
2. **Push access.** flakipype reads the repository's `permissions.push`
   before the fixer starts. Without it, `/fix` stops and says so. No forks.
3. **Fixer.** A fresh agent per fix, like an investigator: the finding, the
   verdict with its evidence (as data), and the tools below. It ends with
   `submit_fix`.
4. **Checks** in code, then a **reviewer** pass on the diff (below). A fix
   that fails a check or is rejected goes back to the fixer once with the
   reasons, then the fix ends without a pull request.
5. **Delivery** after confirmation: branch, commit, draft pull request,
   verification. Each step reports its result; a failure stops the next step
   and says what exists already.

## The fixer's tools

The fixer works on an in-memory working copy pinned to the head commit of
the default branch when the fix starts. Nothing is cloned or written to
disk, no repository code runs on your machine, and no git hooks exist to
run.

| Tool | Does | Risk |
| --- | --- | --- |
| `list_files(path)` | Files and directories under a path at the pinned commit (git trees API) | `read` |
| `read_file(path, from_line, to_line)` | The working copy's version: edited if edited, else from GitHub | `read` |
| `replace_in_file(path, old, new)` | Replaces one exact, unique occurrence; an ambiguous or missing `old` is an error | `read` |
| `write_file(path, content)` | Creates a new file or replaces a whole file | `read` |
| `show_diff()` | Unified diff of the working copy against the pinned commit | `read` |
| `submit_fix(title, explanation)` | Ends the fix | – |

Plus the investigator's tools (`failure_excerpt`, `log_range`,
`run_history`, `compare_commits`, `file_diff`, `workflow_file`). Edits are
risk `read`: they change only memory. The one `critical` action is the push
(below), confirmed once with the full diff. Only UTF-8 text files can be
edited, and only inside the finding's repository; paths are normalised and
`.git/` and absolute or `..` paths are refused.

## Checks in code

Deterministic, before the reviewer and before any dialog:

| Check | Rule |
| --- | --- |
| Not empty | At least one changed line |
| Size | At most 10 files and 400 changed lines (`fix.max_files`, `fix.max_changed_lines`) |
| Still parses | Changed `.yml`, `.yaml`, `.json`, `.toml` files parse; workflow files still have `on` and `jobs` |
| Hides failures | Adds `continue-on-error: true`, `if: always()` on a test step, a test skip marker (`skip`, `xfail`, `.skip(`, `@Disabled`, `t.Skip`) or deletes a test |
| Reaches out | Adds a `secrets.` reference, `${{ github.token }}`, an environment dump (`env`, `printenv`), `curl`, `wget`, `nc`, or an `http(s)://` URL other than localhost |
| Touches `.github/` | Changes workflows or composite actions under `.github/` |

The first three are errors: the fix goes back to the fixer. The last three
are **warnings**: in `ask` mode they are shown at the top of the
confirmation and in the pull request; in `auto` mode a fix with any of them
is not pushed (see [modes](#modes)).

## Reviewer

A second model call with the finding, the verdict, the diff and the fixer's
explanation, not the fixer's whole conversation. It answers `accept`,
`revise` (with concrete points; the fixer continues once) or `reject` (with
a reason), and checks:

- The diff addresses the cause the verdict names, not a symptom.
- It does not hide the failure: no blanket retries, no longer timeouts
  without a reason in the evidence, no skipped tests.
- No change unrelated to the cause.

A fix the reviewer does not accept is not pushed. The chat shows the diff
and the reason, so you can still ask for changes.

## Confirmation

The push is one `critical` action. The dialog shows facts from code at the
top, the model's text clearly labelled, and the full diff in a scrollable
pane:

```text
╭──────────────────────────────────────────────────────────────────────────╮
│ Push fix and open a draft pull request?                                  │
│                                                                          │
│ octo-org/app · base main @ 3f2a9c1                                       │
│ new branch flakipype/fix-e2e-7c41d0                                      │
│ 2 files · +14 −3 · tests/e2e/scan.spec.ts, playwright.config.ts          │
│ then reruns E2E on the fix branch 3 times                                │
│ Pull requests this session: 1 of 3 · Actions: 4 of 10                    │
│ Warnings: none                                                           │
│ ── written by the model ─────────────────────────────────────────────    │
│ Wait for the document rows instead of a fixed delay                      │
│ The test counts rows before the second import finished …                 │
│ ── diff ─────────────────────────────────────────────────────────────    │
│ --- a/tests/e2e/scan.spec.ts                                             │
│ +++ b/tests/e2e/scan.spec.ts                                             │
│ …                                                                        │
│                         Push           Don't push                        │
╰──────────────────────────────────────────────────────────────────────────╯
```

**Don't push** has the focus. A declined fix stays in the session: `/fix N`
shows it again, and you can ask the model for changes. Everything else
follows the gate of [actions](actions.md): no second write request after a
decline in the same turn, and an audit log entry for every request.

## Delivery

All through `gh api`, against the configured owner and host only:

1. **Branch.** `POST /repos/{o}/{r}/git/refs` creates
   `refs/heads/flakipype/fix-<workflow>-<hash>` at the pinned commit. The
   name always starts with `flakipype/` and never equals the default branch;
   code checks both. If the name exists, a suffix is added; flakipype never
   writes to a branch it did not create in this fix.
2. **Commit.** GraphQL `createCommitOnBranch` adds the changed files as one
   commit, with `expectedHeadOid` set to the pinned commit, so it can only
   append to the new branch and never overwrite anything. GitHub signs the
   commit, so it shows as *Verified* and passes branch rules that require
   signed commits. Message: the title, the explanation, and a
   `Generated-by: flakipype` trailer.
3. **Pull request.** `POST /repos/{o}/{r}/pulls` with `draft: true`, always,
   in both modes. The body is a code template (below).
4. **Verification** starts (below).

If a step fails, the following steps do not run and the message says what
exists: for example "Branch flakipype/fix-e2e-7c41d0 created, commit failed:
… The branch was left as it is." flakipype never deletes branches.

The pull request body:

```markdown
<!-- flakipype:finding=octo-org/app/E2E/… -->
## Flaky: E2E in octo-org/app

**Scan facts:** failed 4 of 31 runs on main in 30 days; 3 passed when the
same commit was rerun.
**Verdict** (model's assessment, reviewed): flaky_test, high confidence. …

### The change (written by the model)
…

### Warnings
none

### Verification
Pending: flakipype reruns E2E on this branch 3 times.

---
Opened by flakipype as a draft. Merging is up to you.
```

## Verification

The fix branch has to show it passes where the default branch flakes:

1. flakipype waits for the run of the finding's workflow on the fix commit
   (event `pull_request` or `push`). If the workflow is not triggered by
   either but allows `workflow_dispatch`, flakipype dispatches it on the fix
   branch. Otherwise the result is "cannot verify automatically" and the
   comment says so.
2. When the run finishes, it reruns the whole run until the workflow has
   run `fix.verify_runs` times (default 3) on the fix commit. The runs show
   in the Runs list as in [actions](actions.md) and count against the same
   action budget; the push confirmation already covers them.
3. The result is posted as a comment on the pull request, written by code:

```text
flakipype verification: E2E passed 3 of 3 runs on this branch.
On main, E2E failed 4 of 31 runs (13%) in the last 30 days. Three passes in
a row would also happen by chance 66% of the time without a fix, so this is
a first signal, not proof.
```

A failure with the finding's error signature says the fix did not hold; a
failure with another signature is reported as such. The chance shown is
`(1 − rate)^runs`, computed from the scan's numbers. Verification is watched
while the chat is open; a resumed session continues it.

## Modes

`/mode ask|auto` switches the chat's mode. The chat always starts in `ask`;
the mode is not stored in the session, and the status line shows it.

| | `ask` | `auto` |
| --- | --- | --- |
| Reruns, dispatches, cancels (`write`) | dialog | run within the budget |
| Push and draft PR (`critical`) | dialog with the diff | run within the budget, if no warning |
| Fix with a warning (hides failures, reaches out, `.github/`) | dialog shows the warnings | not pushed; kept for `/mode ask` |
| Draft pull request | always | always |

The `.github/` rule exists because a pushed branch in the same repository
triggers its `push` workflows with the repository's secrets, using the
workflow files from that branch, before anyone reviews the pull request.
Job logs and repository files can contain text that tries to steer the
model; in `ask` mode you see every line of the diff first, in `auto` mode
code refuses the changes that could leak secrets or hide failures. Audit
entries record `auto` as the answer.

## Budget

| Limit | Default | Setting |
| --- | --- | --- |
| Pull requests per chat session | 3 | `fix.max_prs_per_session` (1–20) |
| Files and changed lines per fix | 10 and 400 | `fix.max_files` (1–50), `fix.max_changed_lines` (10–2,000) |
| Verification runs per fix | 3 | `fix.verify_runs` (1–10) |
| Fixer tool rounds | 20 | `fix.max_rounds` (5–60) |
| Fixer tokens (fixer and reviewer) | 300,000 | `fix.max_tokens` (10,000–2,000,000) |
| Fixer wall-clock time | 10 minutes | `fix.max_seconds` (60–3,600) |

Verification reruns count against `actions.max_per_session`. Reaching a
limit ends the fix with a summary, as everywhere.

## Permissions

The `repo` and `workflow` scopes flakipype already asks for cover branches,
commits (including workflow files) and pull requests. A fine-grained token
needs **Contents**, **Pull requests** and **Workflows: read and write**, plus
**Actions: read and write** for verification. A `403` explains which
permission is missing, and nothing is retried.

## Where it lives

- **`agent`**: the fixer and its reviewer (`fixer.py`), the edit tools, and
  the working copy (`workcopy.py`: an overlay of edited files over the
  pinned commit, with the unified diff from `difflib`).
- **`fix`** (new, between `investigate` and `actions`): the checks, the
  delivery steps, the pull request body, verification and its comment, the
  pull request budget and the session state of fixes.
- **`github`**: `pulls.py` for refs, `createCommitOnBranch`, pull requests,
  comments, push permission and the tree listing.
- **`investigate`**: `/fix`, `/mode`, the `fix` tool's workspace side.
- **`tui`**: the diff in the confirmation dialog, the mode in the status
  line.

## Testing

- The working copy and edit tools: unique and ambiguous replacements, new
  files, path normalisation, the diff.
- Every check, with diffs that pass and fail it.
- The fixer and reviewer with the scripted fake model: accept, revise,
  reject, a failing check, budget ends.
- `pulls.py` against the `gh` stub with recorded responses, including the
  GraphQL commit, an existing branch name, `403` and a failure after the
  branch was created.
- Delivery, verification (passes, same signature, other signature, cannot
  verify) and the comment text with a fake clock.
- The gate in both modes, including warnings in `auto`.
- The confirmation with a diff and the mode in the status line: Pilot tests
  and snapshots.
