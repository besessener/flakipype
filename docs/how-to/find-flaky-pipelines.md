# Find flaky pipelines

`flakipype scan` reads the GitHub Actions runs of the configured user or
organisation, finds jobs that failed and passed on the same code, and ranks
the ones where that keeps happening. It needs a finished `flakipype setup`;
the model is not used.

## Scan

```bash
flakipype scan
```

While it runs, a progress bar shows the stage: listing repositories, reading
workflow runs, inspecting failed attempts and reading the logs of failed
jobs. Then it prints a ranking, most affected runs first:

```text
╭─ flakipype scan · octo-org on github.com ─────────────────────────────────────────╮
│ 18 repositories · 1,396 runs · last 30 days (09 Sep – 09 Oct 2026)                  │
│ 1 flaky job in 1 workflow · 4 seen once · 5 recurring errors                         │
╰─────────────────────────────────────────────────────────────────────────────────────╯
  #  Flaky job                                     Runs   Flake rate   Signal
  1  octo-org/app                                  4/509  █░░░  0.8%   ↻ 4 passed on rerun
     CI › test › E2E (Electron under Xvfb)
     timeout ×4 tests/e2e/scan.spec.ts:N:N › … toHaveCount(expected) failed
     latest failure ↗
```

- **Runs**: runs with a flaky failure of this job / finished runs of its workflow.
- **Signal**: `↻ passed on rerun` (strong) or `≡ same commit passed` (medium);
  see [how flakiness is detected](../explanation/flake-detection.md).
- **Signatures**: the error behind the failures, grouped across runs, with a
  category such as timeout, network or dependencies.
- **latest failure ↗** is a terminal hyperlink to the job on GitHub.

Below the ranking, up to three more sections:

- **Seen once**: proven events in a single run only. Could be an outage or a
  fix outside the code followed by a rerun; not counted as flaky.
- **Fixed**: failed in several runs, then the workflow kept passing. A real
  error that was fixed; not flaky.
- **Recurring errors**: the same error in several runs (any branch) without
  proof. Could be a flaky test nobody reran, or a real bug caught again.

Why these are kept apart: [how flakiness is detected](../explanation/flake-detection.md).

## Narrow or widen it

```bash
flakipype scan --days 7                 # look back 7 days instead of 30
flakipype scan --repo app --repo docs   # only these repositories
flakipype scan --owner other-org        # another user or organisation
flakipype scan --max-logs 200           # read more logs this time
flakipype scan --min-runs 3             # need 3 runs before calling a job flaky
```

Defaults come from the `[scan]` section of the
[configuration](../reference/configuration.md).

## Use it in scripts

```bash
flakipype scan --json > flaky.json
jq '.jobs[] | select(.status == "flaky") | .repository + " " + .job' flaky.json
```

The JSON goes to standard output, progress to standard error. The format is
described in the [scan JSON reference](../reference/scan-json.md).

| Exit code | Meaning |
| --- | --- |
| 0 | Scan finished (whether or not flaky jobs were found) |
| 1 | Stopped early (rate limit), or GitHub could not be read at all |
| 2 | Not set up: no configuration, owner or `gh` |

## Repeated scans are fast

Jobs of finished attempts and the results of read logs never change, so
flakipype caches them in `~/.local/share/flakipype/cache.sqlite3`. A second
scan only lists the runs again. Logs are read at most `max_log_downloads` per
scan, newest flaky failures first; the next scan continues where the last one
stopped. Deleting the cache file is always safe.

## When something goes wrong

- **A repository could not be read** (for example Actions disabled): it is
  listed under *Notes*, the rest of the scan continues.
- **Rate limit**: the scan stops, shows what it found so far and exits with 1.
  Run it again later; cached work is not repeated.
- **Login no longer valid**: run `flakipype setup` and log in again.
- **Logs expired**: GitHub keeps logs for 90 days by default. Such failures
  are still counted, just without a signature.
