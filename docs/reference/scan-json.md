# Scan JSON (`flakipype scan --json`)

The format is versioned by `schema_version`. Fields are only added within a
version; renaming or removing one raises the version.

## Schema version 1

```json
{
  "schema_version": 1,
  "owner": "octo-org",
  "host": "github.com",
  "window": {"start": "2026-09-09T12:00:00Z", "end": "2026-10-09T12:00:00Z"},
  "complete": true,
  "repositories": 18,
  "runs": 1392,
  "logs_not_read": 0,
  "problems": [],
  "flaky": [
    {
      "repository": "octo-org/app",
      "workflow": {"name": "CI", "path": ".github/workflows/ci.yml"},
      "job": "test",
      "step": "E2E (Electron under Xvfb)",
      "flaky_failures": 4,
      "affected_runs": 4,
      "total_runs": 509,
      "flake_rate": 0.0079,
      "signals": {"rerun_passed": 4, "same_commit": 0},
      "last_seen": "2026-10-07T09:28:45Z",
      "examples": ["https://github.com/octo-org/app/actions/runs/1/job/2"],
      "signatures": [
        {
          "category": "timeout",
          "message": "tests/e2e/scan.spec.ts:N:N › … · Error: expect(locator).toHaveCount(expected) failed · …",
          "fingerprint": "3f9a0c1b2d4e",
          "occurrences": 4
        }
      ]
    }
  ]
}
```

### Top level

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Format version, currently `1` |
| `owner`, `host` | string | What was scanned |
| `window.start`, `window.end` | UTC timestamp | Runs created in this range |
| `complete` | bool | `false` if the scan stopped early (rate limit) |
| `repositories` | int | Repositories scanned (no archived ones, no forks) |
| `runs` | int | Workflow runs listed in the window |
| `logs_not_read` | int | Flaky failures whose log was not read yet (limit or early stop) |
| `problems` | list of strings | Repositories or items that could not be read |
| `flaky` | list | Flaky jobs, ranked: most affected runs, then rate, then most recent |

### `flaky[]`

| Field | Meaning |
| --- | --- |
| `repository`, `workflow.name`, `workflow.path`, `job`, `step` | Where the failures happen; `step` is the first failed step, empty if unknown |
| `flaky_failures` | Failed jobs counted as flaky (one run can contribute several attempts) |
| `affected_runs` | Distinct runs with such a failure |
| `total_runs` | Finished runs (success or failure) of this workflow in the window |
| `flake_rate` | `affected_runs / total_runs`, 4 decimals |
| `signals.rerun_passed` | Failures in an attempt that a later attempt of the same run fixed |
| `signals.same_commit` | Failures of runs whose commit passed in another run of the workflow |
| `last_seen` | When the newest flaky failure finished |
| `examples` | Up to 3 job URLs, newest first |
| `signatures[]` | Error signatures from the logs read so far, most frequent first |

### `signatures[]`

| Field | Meaning |
| --- | --- |
| `category` | `runner`, `resources`, `rate limit`, `network`, `dependencies`, `timeout`, `assertion`, `exit code` or `other` |
| `message` | Normalised error text: numbers become `N`, durations `<duration>`, hashes `<hex>`, times `<time>`, temp paths `<tmp>` |
| `fingerprint` | 12 hex characters; equal fingerprints mean the same error |
| `occurrences` | Failures of this job with this signature |
