# Unattended runs and release

> Status: implemented in M6. Setup: [run on a schedule](../how-to/run-on-a-schedule.md).

The chat needs you at the keyboard. M6 lets flakipype work on a schedule:
`flakipype run` scans, investigates and opens draft pull requests for
fixable findings without a window, `flakipype daemon install` runs it from a
systemd user timer, and an install script plus smoke tests on four
distributions make it installable. Every rule of the
[safety model](safety-model.md) applies unchanged; nobody watching means
tighter limits, not looser ones.

## Scope

- **In**: `flakipype run [--mode auto|ask]`; continuing fix verifications
  across runs; daily limits across runs; a run lock; `flakipype daemon
  install|uninstall|status` for a systemd user timer; a `secrets.store`
  setting and a clean error for an unreachable keyring; `install.sh`; the
  first release tag `v0.1.0`; a CI smoke job on Ubuntu, Debian, Fedora and
  Arch.
- **Out**: reruns or dispatches on the default branch to gather evidence
  (headless runs only rerun flakipype's own fix branches); a model that
  decides what to do (the run's steps are fixed in code); system-wide
  services, cron files, container images; PyPI; a release workflow.

## `flakipype run`

One run does, in this order, all in code and without an orchestrator model:

```text
lock ──▶ continue earlier verifications ──▶ scan ──▶ investigate ──▶ fix ──▶ poll until done or time is up ──▶ summary
```

1. **Lock.** A second `flakipype run` while one is running exits with code 3
   at once (below).
2. **Continue.** The pull requests the last run left unverified are taken
   over ([verifications](#verifications-across-runs)) and saved in the new
   run's session at once, so a run that dies later still hands them on.
3. **Scan** the configured owner, as `flakipype scan` does. A scan stopped by
   GitHub's rate limit ends the step here: investigations would only see
   GitHub refuse their tools, so they and the fixes wait for the next run.
4. **Investigate** the flaky and recurring findings, as `flakipype
   investigate` does: cached verdicts are reused until a finding has a newer
   failure. A finding whose investigation in an earlier run ended without a
   verdict (`no_verdict` or a loop, in either mode) is not investigated again
   until it has a newer failure; running out of tokens or a model error is
   tried again next time. No investigation starts after `run.max_minutes`.
5. **Fix** findings with a reviewed verdict classified `flaky_test`,
   `flaky_infrastructure` or `configuration`, highest ranked first, through
   the same `fix` tool and policy gate as the chat ([fixes](fix.md)).
   Skipped: findings with an open flakipype pull request or without push
   access, and findings whose fix an earlier `auto` run did not push
   (warnings, no fix, rejected by the reviewer, or a commit pushed whose pull
   request could not be opened), until they have a newer failure, so a run
   does not pay for the same rejected fix every day. A model error during the
   fix or its review is a problem of the run (exit code 1) and is tried
   again next time. A fix gets at most the time the run has left, even when
   `fix.max_seconds` is longer. A pushed commit whose pull request could not
   be opened counts against the pull request limits like an opened one.
6. **Poll** (`auto` only) started verifications every 10 seconds until all
   are done or `run.max_minutes` is reached.
7. **Summary** on standard output, which systemd sends to the journal.

Options: `--mode auto|ask` (default `auto`), `--json`, and `--repo` and
`--days` as for `scan`. `--owner` must name the configured `github.owner`
(in any case): a run fixes only that owner, so another one is refused with
exit code 2 before anything is read; `scan` and `investigate` read other
owners. Progress goes to standard error and only
on a terminal.

### Modes without a window

| | `auto` (default) | `ask` |
| --- | --- | --- |
| Scan, investigate, fixer and reviewer | run | run |
| Push and draft pull request (`critical`) | run within the budgets, if the diff has no warning | not run: reported with its diff |
| Verification reruns of the run's own fix branches (`write`) | run within the budgets | none: earlier runs' pull requests wait for the next `auto` run |
| Fix with a warning (hides failures, reaches out, `.github/`) | not pushed, kept | kept |
| A fix that was not pushed | remembered until the finding fails again | not remembered |
| Draft pull request | always | – |

`ask` without a window is a dry run that still goes through the gate: the
`HeadlessGate` answers every `write` and `critical` request with `report
only`, and the audit log records it so. A fix that was not pushed is kept in
the run's session for the chat (below). A headless run never starts a rerun
or dispatch on anything but its own fix branches; the scan's runs are only
read.

### Summary and exit codes

```text
flakipype run · octo-org · auto · 2026-10-12 06:02–06:41
Scan: 42 repositories, 1,204 runs, 5 flaky, 2 recurring error
Investigated: 2 (1 flaky_test, 1 real_bug), 3 verdicts from the cache
Fixes: #1 octo-org/app › E2E › e2e: Opened draft pull request #57: https://github.com/octo-org/app/pull/57 (branch flakipype/fix-e2e-7c41d0).
       #2 octo-org/app › CI › lint: not fixed: real bug, which flakipype does not fix
       #4 octo-org/api › CI › test: not pushed: the diff has warnings: changes .github/: .github/workflows/ci.yml (kept for the chat)
       #6 octo-org/api › CodeQL › analyze: not investigated again: an earlier run ended without a verdict (no_verdict: …), and it has not failed since
Verification: octo-org/app#51: flakipype verification: E2E passed 3 of 3 runs on this branch.
              octo-org/app#57: 1 of 3 runs, continues in the next run
Budget: pull requests today 1 of 3 · actions today 4 of 20 · tokens 412,000 of 1,000,000 (today 412,000 of 3,000,000)
```

`Fixes` has a line for every flaky finding and recurring error: the pull
request, or why there is none (no verdict, a classification flakipype does
not fix, a verdict whose review could not run, a limit, a fix that was not
pushed). Further lines name the limits that stopped a step (`Stopped by:`)
and the errors (`Problems:`). `--json` prints the same as one object with
`schema_version` 1, including the diff of every fix that was not pushed.

| Code | Meaning |
| --- | --- |
| 0 | The run finished; a reached budget or time limit is a normal end and named in the summary |
| 1 | Something was incomplete: the scan stopped early, GitHub or the model failed, an investigation or a delivery failed |
| 2 | Not ready: no configuration, no key, an unreachable keyring, no `gh` login, an `--owner` other than the configured one |
| 3 | Another `flakipype run` holds the lock |

## Verifications across runs

A fix branch is verified by up to `fix.verify_runs` runs, which can take
longer than one run may last. Each run is stored as a session, like a chat
session, with its scan, verdicts, kept fixes, started runs and opened pull
requests. When a run reaches `run.max_minutes`, unfinished verifications
stay in its session. The next run takes over the pull requests the last run
left unverified, with the runs they follow under their numbers, and an `auto`
run polls them until they finish or their watch time
(`actions.watch_hours`) is over; the pull request comment then says after how
many runs and why, as in the chat. An `ask` run only keeps them for the next
`auto` run. Reruns started for an earlier run's verification count against
the action limits of the run that starts them.

**In the chat**, `/sessions` lists run sessions marked `run`. `/resume` on a
run session starts a new chat session with a copy of the run's scan,
verdicts and kept fixes, in `ask` mode. The run's started runs and pull
requests stay with the run session, so only the timer polls them and nothing
is rerun twice. A kept fix with warnings then works as in the chat: `/fix N`
shows the confirmation with the warnings and the full diff.

## Budgets

The limits of one run are the existing session limits; a run is one
session. On top, daily limits count every headless run of the last 24 hours,
so a short timer interval cannot multiply them:

| Limit | Default | Setting |
| --- | --- | --- |
| Draft pull requests per run | 3 | `fix.max_prs_per_session` |
| Reruns and dispatches per run | 10 | `actions.max_per_session` |
| Tokens per run, investigations and fixes together | 1,000,000 | `agent.max_tokens_per_run` |
| Wall-clock time per run | 120 minutes | `run.max_minutes` (10–720) |
| Draft pull requests in 24 hours | 3 | `run.max_prs_per_day` (1–20) |
| Reruns and dispatches in 24 hours | 20 | `run.max_actions_per_day` (1–200) |
| Tokens in 24 hours | 3,000,000 | `run.max_tokens_per_day` (10k–50M) |

Pull requests and actions in 24 hours are counted from the audit log
(entries with origin `run` that ran); tokens from the run sessions. The chat
does not count against the daily limits, and runs do not count against the
chat's. Reaching a limit stops what it limits: no further fixes after the
pull request limit, no investigation after today's tokens are used up and
no further fix after a token limit (a fix already running still ends at its
own `fix.max_tokens`); polling verifications continues within the action
limit. The summary names the limit.

## Running next to the chat

- **Run lock.** `run` holds an exclusive SQLite lock on
  `$XDG_DATA_HOME/flakipype/run.lock` for its whole duration; the OS
  releases it if the process dies. A second run exits with code 3 and touches
  nothing.
- **Database.** The cache database uses SQLite's WAL journal with a busy
  timeout, so the chat and a run can read and write it at the same time.
- **Duplicate pull requests.** The chat and a run may fix the same finding
  at the same time. Delivery looks for an open flakipype pull request for
  the finding again right before it creates the branch, and links that one
  instead.
- **Audit.** Entries from runs have the origin `run`, next to `model` and
  `command`. Verification reruns and dispatches are recorded too, as
  `verify_rerun` and `verify_dispatch` with the answer `covered by the push`;
  the daily action limit counts them.

## Secrets under systemd

A user timer often runs without a desktop session. Then the system keyring
is missing (keyring falls back to the `0600` file, which is empty if setup
stored the key in the keyring) or locked. So:

- The setting `secrets.store` is `auto` (the keyring where there is one,
  else the file), `keyring` or `file`. `flakipype setup --non-interactive
  --secret-store file --api-key-stdin` stores the key in
  `~/.config/flakipype/secrets.json` (mode `0600`), which a timer can read
  without a session.
- A locked or unreachable keyring is a typed error: exit code 2 and that
  next step, never a traceback.
- `doctor` says which store holds the key.
- `daemon install` checks before it installs anything (below).

The GitHub token stays `gh`'s login. If `gh` keeps it in the keyring, the
same applies to `gh`; `gh auth login --insecure-storage` keeps it in `gh`'s
own config file instead ([run on a schedule](../how-to/run-on-a-schedule.md)).

## `flakipype daemon`

| Command | Does |
| --- | --- |
| `daemon install [--schedule S] [--mode auto\|ask]` | Checks, writes the units, `systemctl --user daemon-reload`, enables and starts the timer |
| `daemon install --print` | Prints the units and changes nothing |
| `daemon uninstall` | Disables the timer and removes the units flakipype wrote |
| `daemon status` | The timer's next and last start, the last result and exit status, and the last run's summary from the journal |

`--schedule` takes a systemd calendar expression, checked with
`systemd-analyze calendar`; default `daily`. The units go to
`$XDG_CONFIG_HOME/systemd/user/`:

```ini
# flakipype.service, generated by flakipype
[Unit]
Description=flakipype: find and fix flaky GitHub Actions pipelines

[Service]
Type=oneshot
ExecStart=/home/me/.local/bin/flakipype run --mode auto
TimeoutStartSec=730min
Nice=10
```

```ini
# flakipype.timer, generated by flakipype
[Unit]
Description=Run flakipype on a schedule

[Timer]
OnCalendar=daily
RandomizedDelaySec=15min
Persistent=true

[Install]
WantedBy=timers.target
```

- `ExecStart` is the absolute path of the running `flakipype`, because a
  user unit's `PATH` does not include `~/.local/bin`.
- `TimeoutStartSec` is the highest allowed `run.max_minutes` (720) plus 10
  minutes. It is a backstop: the run keeps its own `run.max_minutes`, and
  changing that setting later needs no new unit. A step that is already
  running when the limit is reached (the scan, an investigation, a fix's
  last model call) still finishes, so a run can end a few minutes after
  `run.max_minutes`, never anywhere near the unit's limit.
- `Type=oneshot` means systemd never starts the service twice at once; the
  run lock covers manual runs.
- Unit files flakipype did not write (no `generated by flakipype` line) are
  never overwritten or removed.

**Checks before installing.** `daemon install` checks the schedule with
`systemd-analyze calendar` and runs
`systemd-run --user --wait --pipe --collect <flakipype> doctor`, so `doctor`
runs in the same environment as the timer will. If either fails, nothing is
written and the output says why, typically the keyring. The executable path
and the schedule must not contain characters that could add lines to a unit
file. If systemd refuses after the files are written, the message says where
they are and that `daemon uninstall` removes them. Without lingering
(`loginctl show-user` reports `Linger=no`), a warning says that the timer
only runs while you are logged in and that `loginctl enable-linger` changes
that; flakipype does not run it.

## Install script

`install.sh` in the repository root, POSIX `sh`, for a user install without
root:

```bash
curl -fsSLO https://raw.githubusercontent.com/besessener/flakipype/v0.1.0/install.sh
sh install.sh
```

1. Checks Linux, `x86_64` or `aarch64`, glibc, and `curl`, `tar`,
   `sha256sum` and `git`; a missing one is named with the package to
   install.
2. Uses `uv` from `PATH` if there is one. Otherwise it downloads the `uv`
   release pinned in the script from `github.com/astral-sh/uv/releases`,
   verifies the tarball against the release's published `.sha256` file and
   installs `uv` to `~/.local/bin`. A mismatch aborts and installs nothing.
3. Runs `uv tool install --force
   git+https://github.com/besessener/flakipype@v0.1.0`. The tag is the one
   the script was released with. uv takes a Python 3.12 or newer from the
   system or downloads one, which it verifies itself.
4. Prints the next step (`flakipype setup`) and a hint if `~/.local/bin` is
   not on `PATH`.

`FLAKIPYPE_SOURCE` installs from a local checkout instead, for the smoke
tests. `uv tool install git+…` stays documented for people who already
have `uv`.

## Release

The version becomes `0.1.0` in `pyproject.toml`, and `install.sh` names the
tag `v0.1.0`; a unit test checks that both agree. After M6 is merged, you
create the tag `v0.1.0` on `main` and a GitHub release from it. There is no
release workflow and no PyPI package.

## Smoke tests

The job `smoke` in `.github/workflows/ci.yml`, on pull requests and pushes
to `main`, and runnable with `act pull_request -j smoke`. A matrix of
containers, images pinned by digest: `ubuntu:24.04`, `debian:12`,
`fedora:latest` and `archlinux:latest`. Each one installs `curl`, `git` and
`systemd` (and `ca-certificates` or `tar` where the image lacks them) as root,
then runs `tests/smoke/smoke.sh` as a new user without root, which:

1. runs `install.sh` with `FLAKIPYPE_SOURCE` set to a copy of the checkout,
   which also exercises the verified `uv` download, since no image has `uv`;
2. checks `flakipype --version` against `pyproject.toml`;
3. checks that `flakipype doctor` without a configuration exits with code 1
   and points to `flakipype setup`;
4. renders the units with `daemon install --print`, checks that `ExecStart`
   starts the installed command, and checks both units with
   `systemd-analyze verify`.

The job may only read the repository and checks out without credentials,
like the other jobs. Real GitHub and a real model are not used; `run` itself
is tested in the `test` job with in-memory GitHub fakes and a fake model.

## Where it lives

- **`unattended`** (on the layer of `tui`, independent of it): the run
  service with the steps above and its report (`service.py`), the daily
  limits (`limits.py`) and what a run takes over from the last one
  (`carry.py`). It uses the chat's workspace and the `investigate`, `fix`
  and `actions` services the way the chat does.
- **`agent`**: the `HeadlessGate` next to the policy gate (`tools.py`).
- **`setup`**: `daemon.py` renders the units (pure text) and installs them
  through a command runner it is given.
- **`store`**: the run lock (`lock.py`), WAL, run sessions, the fixes a run
  did not push, the investigations that ended without a verdict, and audit
  entries since a time.
- **`config`**: `[run]`, `[secrets]` and the store choice.
- **`fix`** and **`actions`**: the origin `run`, audited verification runs,
  taking over pull requests and runs, the check for an open pull request
  before delivery, and typed errors for a fix that was not made and a failed
  delivery.
- **`investigate`**: run sessions in `/sessions` and `/resume`.
- **`cli`**: `run` and `daemon` (`run_command.py`, `run_report.py`,
  `daemon_commands.py`), wired in `wiring.py`.

## Testing

- The run service over in-memory GitHub fakes and a fake agent and fixer,
  with a settable clock: both modes, a fix with warnings, a rejected fix that
  is not tried again (and is in a dry run), every limit, the time limit with
  verifications left over and finished by the next `auto` run, a failed
  delivery, the session it leaves for the chat.
- A line for every finding that was not fixed, and investigations without a
  verdict that the next run skips until a newer failure.
- Daily usage from audit entries and the per-run limits it leaves.
- The run lock held twice; WAL on a cache file.
- `/resume` of a run session: a new session with the run's fixes not pushed,
  without its pull requests.
- The exact unit files; install, uninstall and status against a fake command
  runner, including a failing `doctor`, foreign unit files and a refused
  start.
- The keyring error and each `secrets.store` value.
- The summary, its JSON and every exit code of `run`; the `daemon` commands.
- `install.sh` and the smoke test with ShellCheck (`shellcheck-py`) in
  `poe check`, a test that the script installs the version in
  `pyproject.toml`, and end to end in the smoke job.
