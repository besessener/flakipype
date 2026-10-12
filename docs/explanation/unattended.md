# Unattended runs and release

> Status: design for M6.

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
2. **Continue.** Unfinished verifications of earlier runs are polled again
   ([verifications](#verifications-across-runs)).
3. **Scan** the configured owner, as `flakipype scan` does.
4. **Investigate** the flaky and recurring findings, as `flakipype
   investigate` does: cached verdicts are reused until a finding has a newer
   failure.
5. **Fix** findings with a reviewed verdict classified `flaky_test`,
   `flaky_infrastructure` or `configuration`, highest ranked first, through
   the same `fix` tool and policy gate as the chat ([fixes](fix.md)).
   Skipped: findings with an open flakipype pull request, and findings whose
   fix an earlier run did not push (warnings, rejected by the reviewer,
   failed checks), until they have a newer failure, so a run does not pay
   for the same rejected fix every day.
6. **Poll** started verifications every 10 seconds until all are done or
   `run.max_minutes` is reached.
7. **Summary** on standard output, which systemd sends to the journal.

Options: `--mode auto|ask` (default `auto`), `--json`, and `--owner`,
`--repo` and `--days` as for `scan`. Progress goes to standard error and only
on a terminal.

### Modes without a window

| | `auto` (default) | `ask` |
| --- | --- | --- |
| Scan, investigate, fixer and reviewer | run | run |
| Push and draft pull request (`critical`) | run within the budgets, if the diff has no warning | not run: reported with its diff |
| Verification reruns of the run's own fix branches (`write`) | run within the budgets | none (nothing was pushed) |
| Fix with a warning (hides failures, reaches out, `.github/`) | not pushed, kept | kept |
| Draft pull request | always | – |

`ask` without a window is a dry run that still goes through the gate: the
gate's confirmation function answers every request with `report only`, and
the audit log records it so. A fix that was not pushed is kept in the run's
session for the chat (below). A headless run never starts a rerun or dispatch
on anything but its own fix branches; the scan's runs are only read.

### Summary and exit codes

```text
flakipype run · octo-org · auto · 2026-10-12 06:02–06:41
Scan: 42 repositories, 1,204 runs, 5 flaky findings
Investigated: 2 (1 flaky_test, 1 real_bug), 3 verdicts from the cache
Fixes: draft pull request octo-org/app#57 opened
       octo-org/api e2e not pushed: the diff changes .github/ (kept for the chat)
Verification: octo-org/app#51 passed 3 of 3 · octo-org/app#57 1 of 3, continues next run
Budget: pull requests today 1 of 3 · actions today 4 of 20 · tokens 412k of 1M (today 412k of 3M)
```

`--json` prints the same as one object with `schema_version` 1.

| Code | Meaning |
| --- | --- |
| 0 | The run finished; a reached budget or time limit is a normal end and named in the summary |
| 1 | Something was incomplete: the scan stopped early, GitHub or the model failed, an investigation or a delivery failed |
| 2 | Not ready: no configuration, no key, an unreachable keyring, no `gh` login |
| 3 | Another `flakipype run` holds the lock |

## Verifications across runs

A fix branch is verified by up to `fix.verify_runs` runs, which can take
longer than one run may last. Each run is stored as a session, like a chat
session, with its scan, verdicts, kept fixes, started runs and opened pull
requests. When a run reaches `run.max_minutes`, unfinished verifications
stay in its session, and the next run polls them first, until they finish or
their watch time (`actions.watch_hours`) is over; the pull request comment
then says after how many runs and why, as in the chat. Reruns started for an
earlier run's verification count against today's action limit.

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
pull request limit, no further investigations or fixes after a token limit;
polling verifications continues within the action limit. The summary names
the limit.

## Running next to the chat

- **Run lock.** `run` holds an exclusive `flock` on
  `$XDG_DATA_HOME/flakipype/run.lock` for its whole duration; the kernel
  releases it if the process dies. A second run exits with code 3 and touches
  nothing.
- **Database.** The cache database switches to SQLite's WAL journal with a
  busy timeout, so the chat and a run can read and write it at the same time.
- **Duplicate pull requests.** The chat and a run may fix the same finding
  at the same time. Delivery looks for an open flakipype pull request for
  the finding again right before it creates the branch, and links that one
  instead.
- **Audit.** Entries from runs have the origin `run`, next to `model` and
  `command`.

## Secrets under systemd

A user timer often runs without a desktop session. Then the system keyring
is missing (keyring falls back to the `0600` file, which is empty if setup
stored the key in the keyring) or locked (today an uncaught error with a
traceback). M6 changes this:

- New setting `secrets.store`: `auto` (default, today's behaviour),
  `keyring` or `file`. `flakipype setup --secret-store file` stores the key
  in `~/.config/flakipype/secrets.json` (mode `0600`), which a timer can read
  without a session.
- A locked or unreachable keyring is a typed error: exit code 2 and the next
  step ("run `flakipype setup --secret-store file`"), never a traceback.
- `doctor` says which store holds the key.
- `daemon install` checks before it installs anything (below).

The GitHub token stays `gh`'s login. If `gh` keeps it in the keyring, the
same applies to `gh`; `gh auth login --insecure-storage` keeps it in `gh`'s
own config file instead, which the how-to will show.

## `flakipype daemon`

| Command | Does |
| --- | --- |
| `daemon install [--schedule S] [--mode auto\|ask]` | Checks, writes the units, `systemctl --user daemon-reload`, enables and starts the timer |
| `daemon install --print` | Prints the units and changes nothing |
| `daemon uninstall` | Disables the timer and removes the units flakipype wrote |
| `daemon status` | The timer's next and last start, the last run's exit code and summary |

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
TimeoutStartSec=130min
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
- `TimeoutStartSec` is `run.max_minutes` plus 10 minutes, so systemd only
  stops a run that ignored its own limit.
- `Type=oneshot` means systemd never starts the service twice at once; the
  run lock covers manual runs.
- Unit files flakipype did not write (no `generated by flakipype` line) are
  never overwritten or removed.

**Checks before installing.** `daemon install` runs
`systemd-run --user --wait --pipe --collect <flakipype> doctor`, so `doctor`
runs in the same environment as the timer will. If it fails, nothing is
installed and the output says why, typically the keyring. Without lingering
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
3. Runs `uv tool install --python 3.12
   git+https://github.com/besessener/flakipype@v0.1.0`. The tag is the one
   the script was released with. uv verifies the Python it downloads itself.
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

A new job `smoke` in `.github/workflows/ci.yml`, on pull requests and pushes
to `main`, and runnable with `act pull_request -j smoke`. A matrix of
containers, images pinned by digest: `ubuntu:24.04`, `debian:12`,
`fedora:latest` and `archlinux:latest`. Each one, as a non-root user:

1. installs `curl`, `git`, `ca-certificates` and `systemd` with the
   distribution's package manager;
2. runs `install.sh` with `FLAKIPYPE_SOURCE` set to the checkout, which also
   exercises the verified `uv` download, since no image has `uv`;
3. checks `flakipype --version` against `pyproject.toml`;
4. checks that `flakipype doctor` without a configuration exits with code 2
   and the setup hint;
5. renders the units with `daemon install --print` and checks them with
   `systemd-analyze verify`.

The job has `permissions: {}` and checks out without credentials, like the
existing jobs. Real GitHub and a real model are not used; `run` itself is
tested in the `test` job with the `gh` stub and the fake model.

## Where it lives

- **`unattended`** (new, on the layer of `tui`, independent of it): the run
  service (the steps above, daily limits, the summary), the headless
  confirmation function, and the choice of findings to fix. It uses
  `investigate`, `fix` and `actions` the way the chat does.
- **`setup`**: `daemon.py` renders the units (pure text) and installs them
  through a `systemctl`/`systemd-run` runner it is given.
- **`store`**: the run lock, WAL, run sessions, the fix attempts that were
  not pushed, and audit queries over 24 hours.
- **`config`**: `[run]` and `[secrets]`, the typed keyring error.
- **`fix`** and **`actions`**: the origin `run`, texts that do not mention
  `/new` or `/mode` outside the chat, the check for an open pull request
  before delivery.
- **`cli`**: `run` and `daemon`, wired in `wiring.py`.

## Testing

- The run service against the `gh` stub and the fake model: both modes, a fix
  with warnings, a rejected fix that is not retried, every budget and daily
  limit, the time limit with verifications left over and continued by the
  next run, exit codes, the summary and its JSON.
- Daily limits from audit entries at given times with a fake clock.
- The run lock with two processes; WAL with a chat and a run writing at once.
- `/resume` of a run session: copied scan, verdicts and kept fixes; the
  run's pull requests are not polled by the chat.
- Unit rendering with snapshots; install, uninstall and status against a
  fake runner, including a failing `doctor` and foreign unit files.
- The keyring error and each `secrets.store` value.
- `install.sh` with ShellCheck (`shellcheck-py`, a dev dependency) in
  `poe check`, and end to end in the smoke job.
