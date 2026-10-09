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
  "runs": 1396,
  "logs_not_read": 0,
  "problems": [],
  "min_flaky_runs": 2,
  "jobs": [
    {
      "status": "flaky",
      "repository": "octo-org/app",
      "workflow": {"name": "CI", "path": ".github/workflows/ci.yml"},
      "job": "test",
      "step": "E2E (Electron under Xvfb)",
      "flaky_failures": 4,
      "affected_runs": 4,
      "total_runs": 509,
      "flake_rate": 0.0079,
      "signals": {"rerun_passed": 4, "same_commit": 0},
      "first_seen": "2026-09-30T14:02:11Z",
      "last_seen": "2026-10-07T09:28:45Z",
      "passing_since": "2026-10-07T09:17:20Z",
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
  ],
  "recurring_errors": [
    {
      "repository": "octo-org/app",
      "workflow": {"name": "CI", "path": ".github/workflows/ci.yml"},
      "job": "test",
      "step": "Run npm ci",
      "runs": 2,
      "branches": ["dependabot/npm_and_yarn/typescript-7.0.2"],
      "first_seen": "2026-10-04T08:12:40Z",
      "last_seen": "2026-10-05T08:13:02Z",
      "examples": ["https://github.com/octo-org/app/actions/runs/3/job/4"],
      "signature": {"category": "dependencies", "message": "npm error code ERESOLVE", "fingerprint": "8d1e…"}
    }
  ]
}
```

How the statuses are decided: [how flakiness is detected](../explanation/flake-detection.md).

### Top level

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Format version, currently `1` |
| `owner`, `host` | string | What was scanned |
| `window.start`, `window.end` | UTC timestamp | Runs created in this range |
| `complete` | bool | `false` if the scan stopped early (rate limit) |
| `repositories` | int | Repositories scanned (no archived ones, no forks) |
| `runs` | int | Workflow runs listed in the window |
| `logs_not_read` | int | Failed jobs whose log was not read yet (limit or early stop) |
| `problems` | list of strings | Repositories or items that could not be read |
| `min_flaky_runs` | int | Runs needed for status `flaky` |
| `jobs` | list | Jobs with proven flaky events: all `flaky` ones in ranking order, then `seen_once`, then `fixed` |
| `recurring_errors` | list | Same error in several runs without proof; flaky or a real bug, never ranked |

### `jobs[]`

| Field | Meaning |
| --- | --- |
| `status` | `flaky`, `seen_once` (fewer runs than `min_flaky_runs`) or `fixed` (all events before the workflow passed for good) |
| `repository`, `workflow.name`, `workflow.path`, `job`, `step` | Where the failures happen; `step` is the first failed step, empty if unknown |
| `flaky_failures` | Failed jobs with proof (one run can contribute several attempts) |
| `affected_runs` | Distinct runs with such a failure |
| `total_runs` | Finished runs (success or failure) of this workflow in the window |
| `flake_rate` | `affected_runs / total_runs`, 4 decimals; only meaningful for `flaky` |
| `signals.rerun_passed` | Failures in an attempt that a later attempt of the same run fixed |
| `signals.same_commit` | Failures of runs whose commit passed in another run of the workflow |
| `first_seen`, `last_seen` | When the oldest and the newest such failure finished |
| `passing_since` | First passing run of the workflow from the last affected run on; `null` if none |
| `examples` | Up to 3 job URLs, newest first |
| `signatures[]` | Error signatures from the logs read so far, most frequent first |

### `recurring_errors[]`

| Field | Meaning |
| --- | --- |
| `repository`, `workflow`, `job`, `step` | As in `jobs[]` |
| `runs` | Runs that ended with this error |
| `branches` | Branches those runs were on |
| `first_seen`, `last_seen`, `examples` | As in `jobs[]` |
| `signature` | `category`, `message`, `fingerprint` of the shared error |

### `signatures[]`

| Field | Meaning |
| --- | --- |
| `category` | `runner`, `resources`, `rate limit`, `network`, `dependencies`, `timeout`, `assertion`, `exit code` or `other` |
| `message` | Normalised error text: stand-alone numbers become `N`, durations `<duration>`, hashes `<hex>`, times `<time>`, temp paths `<tmp>` |
| `fingerprint` | 12 hex characters; equal fingerprints mean the same error |
| `occurrences` | Failures of this job with this signature |
