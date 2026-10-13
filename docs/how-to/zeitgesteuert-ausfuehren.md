# Run flakipype on a schedule

`flakipype run` scans, investigates and opens draft pull requests without a
window; a systemd user timer starts it. How it decides and what limits it:
[unattended runs](../explanation/unbeaufsichtigte-laeufe.md).

To try this end to end without touching a real project, point it at the
sandbox [besessener/flakipype-test](https://github.com/besessener/flakipype-test),
which is flaky in known ways and is there to receive draft pull requests and
verification reruns: add `--repo besessener/flakipype-test` to the commands
below.

## 1. Try a dry run

```bash
flakipype run --mode ask
```

`ask` without a window only reports: it scans, investigates and writes fixes,
but pushes nothing and shows what it would open. Fixes it made stay in the
run's session; `/sessions` and `/resume N` in the chat open them, and `/fix N`
shows the confirmation with the diff.

## 2. Run it for real once

```bash
flakipype run
```

The summary names every draft pull request, every fix that was not pushed and
why, the verification of each pull request and how much of today's limits
the runs used. Exit codes: 0 finished, 1 something was incomplete, 2 not set
up, 3 another run is running.

## 3. Make the key readable without a desktop session

A timer often runs while no desktop session has unlocked the system keyring.
Keep the key in a file only you can read instead:

```bash
printf '%s' "$ANTHROPIC_KEY" | flakipype setup --non-interactive --secret-store file --api-key-stdin
```

If `gh` keeps its token in the keyring too, log in again with
`gh auth login --insecure-storage`, which keeps it in `gh`'s own config file.

## 4. Install the timer

```bash
flakipype daemon install                      # daily
flakipype daemon install --schedule "Mon..Fri 06:00"
flakipype daemon install --print              # only show the unit files
```

`install` first runs `flakipype doctor` through `systemd-run --user`, in the
same environment as the timer; if that fails, nothing is installed and the
output says why. Then it writes `flakipype.service` and `flakipype.timer` to
`~/.config/systemd/user/` and starts the timer. Run `install` again to change
the schedule.

Without lingering, a user timer only runs while you are logged in. To run it
on a server without a login session:

```bash
loginctl enable-linger "$USER"
```

## 5. Check on it

```bash
flakipype daemon status                       # next start, last result, last summary
journalctl --user -u flakipype.service        # every run's summary
```

Limits per run and per day are in the `[run]` section of the
[configuration](../reference/konfiguration.md). To stop:

```bash
flakipype daemon uninstall
```
