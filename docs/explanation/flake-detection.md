# How flakiness is detected

A failing pipeline is not automatically flaky. A test that fails because the
code is broken fails every time; a flaky one fails *sometimes on the same
code*. flakipype therefore only counts a failure as flaky when there is proof
that the same code also passed. Plain failures are ignored. The detection is
pure logic in the `flaky` package; no model is involved.

## Two signals

**Passed on rerun (strong).** A run's attempt failed and a later attempt of
the *same run* passed. Same commit, same workflow file, same inputs — only
the luck changed. This is the classic "just rerun it" flake.

**Same commit passed (medium).** A run failed, but another run of the same
workflow on the same commit passed, for example a push and a manual dispatch.
Weaker, because the runs can differ in event, inputs or environment.

A run that still fails after a rerun is not flaky; it is broken.

Generated workflows without a file in the repository (Dependabot's
`dynamic/…` runs) are skipped: their name changes with every update and there
is nothing to fix in the repository.

## Counting

Flaky failures are grouped by repository, workflow, job and first failed
step. The **flake rate** is the number of runs with such a failure divided by
the finished runs of the workflow in the window. Ranking: most affected runs
first, then the higher rate, then the most recent.

## Why it stays cheap

GitHub's run list only shows the last attempt of each run. flakipype lists
all runs (about one call per 100 runs, and the window is split when GitHub's
1,000-result cap would cut the list), then fetches jobs only for the attempts
that can be flaky by the rules above. On a repository with 1,400 runs a
month that is a few dozen extra calls. Finished attempts never change, so
their jobs are cached for good.

## Error signatures

For each flaky failure flakipype reads the job log (limited per scan, newest
first, cached) and extracts one signature:

1. The first `##[error]` annotation that is not the generic
   *Process completed with exit code N*.
2. If there is only the generic one, the most telling line shortly before
   it: lines with `ERR!`, `Error:`, `fatal:`, `Traceback`, `FAILED` and
   similar win; warnings and stack frames are skipped.

The text is normalised (numbers, durations, hashes, timestamps and temporary
paths are replaced by placeholders), so the same error on another day or a
shifted line number gives the same **fingerprint**. A category (timeout,
network, dependencies, …) comes from keyword rules, the more specific ones
first.

Logs are written by anyone who can push code, so they are untrusted:
terminal escape sequences and control characters are removed before anything
is stored or shown, and signatures will reach the model only as data, never
as instructions (see the [safety model](safety-model.md)).

## Known limits

- Without a rerun or a second run on the same commit, a flaky failure looks
  like any other failure and is not counted.
- The signature heuristics are tuned on real logs (Playwright, npm, Stryker)
  and will improve; changing them bumps a version so cached signatures are
  recomputed.
- Logs older than GitHub's retention (90 days by default) cannot be read.
