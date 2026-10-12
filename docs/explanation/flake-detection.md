# How flakiness is detected

A red pipeline is not evidence of flakiness: catching real bugs is what
pipelines are for. A test is flaky when it fails *sometimes on the same
code*. flakipype therefore separates **proof** from **suspicion**, and only
proof counts. Everything here is pure logic in the `flaky` package; no model
is involved. Judging the unproven cases is the agent's job (M3).

## Proof: the same code both failed and passed

**Passed on rerun (strong).** A run's attempt failed and a later attempt of
the *same run* passed. Same commit, same workflow file, same inputs — only
the luck or the environment changed. The classic "just rerun it" flake.

**Same commit passed (medium).** A run failed, but another run of the same
workflow on the same commit passed, for example a push and a manual dispatch.
Weaker, because the runs can differ in event, inputs or environment.
Pull request runs (`pull_request`, `pull_request_target`) take no part: they
test the merge of the head with the base branch, not the head commit itself,
so a pass on push and a failure on the pull request tested different code.
Their reruns still count as "passed on rerun".

Both compare identical code — the whole repository, not just the workflow —
so code changes elsewhere in the history cannot fake an event. A run that
still fails after a rerun is not flaky; it is broken.

Generated workflows without a file in the repository (Dependabot's
`dynamic/…` runs) are skipped: their name changes with every update and there
is nothing to fix in the repository.

## Verdicts: flaky, seen once, fixed

Proven events are grouped by repository, workflow, job and first failed step
— across commits and branches, because the cause of a flaky test often lives
for months. One event alone is still not enough:

| Verdict | Rule | Why |
| --- | --- | --- |
| **flaky** | Events in at least `scan.min_flaky_runs` runs (default 2) **and** the workflow passed between the first and the last of them | The failure keeps coming back after good phases |
| **seen once** | Fewer runs than `min_flaky_runs` | A single event can be an outage, a runner that died, or a fix outside the code (a repository setting, a secret) followed by a rerun |
| **fixed** | Enough runs, all of them before the workflow passed again for good, and it did pass after the last one | A real error that was fixed, e.g. a push failed twice, the Pages setting was changed, and a dispatch on the same commit passed |

A job with enough runs that has not passed since its last failure is not
fixed: it counts as **flaky** and is investigated, where the agent can still
call it a real bug.

"Passed" means the whole workflow run passed. A run where the job passed but
another job failed does not count as a pass, so the rule leans towards
"fixed" rather than "flaky".

Only **flaky** jobs are ranked. The **flake rate** is the number of runs with
a flaky event divided by the finished runs of the workflow in the window.
Ranking: most affected runs first, then the higher rate, then the most
recent. Seen-once and fixed jobs are listed separately and never ranked.

## Suspicion: recurring errors

Flakiness nobody reran is invisible to the proof rules: a run fails, nobody
reruns, the next commit passes, and a week later it fails again the same way.
But the same pattern also fits a real bug caught several times, or a feature
branch that stays red until it is fixed. Telling them apart needs a look at
what changed between the failure and the next pass — judgement, not a rule.

So flakipype lists **recurring errors** separately: the same job, step and
error fingerprint in at least `min_flaky_runs` runs, on any branch, without
proof. They are labelled "flaky or a real bug", carry no flake rate and are
never ranked. The agent investigates them with the commit diffs in M3. An
error that the same scan proved flaky for the same job and step is not
listed again as a recurring error.

A generic *exit code N* never ties runs together; only a real error line
does.

## What it costs

GitHub's run list only shows the last attempt of each run. flakipype lists
all runs (about one call per 100 runs; the window is split when GitHub's
1,000-result cap would cut the list), then fetches jobs for the attempts that
can be flaky and for the last attempt of every failed run. Finished attempts
never change, so their jobs are cached for good. A scan reads the jobs of at
most `scan.max_job_reads` attempts (default 500), those that can be flaky
first and newest first; the rest are counted as not inspected yet and read
by later scans. On an organisation-sized target (hundreds of repositories)
the first scans therefore build up the cache over several runs.

At most 1,000 repositories of an owner are scanned; a longer list is cut and
named in the scan's problems, and `--repo` picks others. A scan stopped by
GitHub's rate limit still uses every cached job and log result.

Requests are made one after another, as GitHub recommends to avoid its
secondary rate limits. On a real account (18 repositories, about 1,400 runs
in 30 days, about 70 failed runs) the first scan took about 3 minutes and a
repeat scan about 50 seconds, almost all of it GitHub answering pages of 100
runs (about 3 seconds each). Run lists cannot be cached: a rerun of an old
run keeps its creation date, so only listing again sees it.

## Error signatures

flakipype reads job logs — proven flaky failures first, then the other
failed jobs, newest first within each, up to `scan.max_log_downloads` per
scan, cached — and extracts one signature per log:

1. The first `##[error]` annotation that is not the generic
   *Process completed with exit code N*.
2. If there is only the generic one, the most telling line shortly before
   it: lines with `ERR!`, `Error:` (also `TypeError:`, `AssertionError:` and
   other names ending in `Error`), `fatal:`, `Traceback`, `FAILED` and names
   ending in `Exception` win; warnings and stack frames are skipped.

The text is normalised (stand-alone numbers, durations, hashes, timestamps
and temporary paths are replaced by placeholders), so the same error on
another day or a shifted line number gives the same **fingerprint**. A
category (timeout, network, dependencies, …) comes from keyword rules, the
more specific ones first. HTTP status codes (429, 502–504) count only next to
`HTTP/…`, `status` or their reason phrase, never as a bare number such as a
line number or a test count.

Logs are written by anyone who can push code, so they are untrusted:
terminal escape sequences and control characters are removed before anything
is stored or shown, and logs will reach the model only as data, never as
instructions (see the [safety model](safety-model.md)).

## Known limits

- Changes outside the repository (settings, secrets, outside services) are
  not visible in run data; "seen once" and "fixed" exist because of that.
- Recurring errors are suspicion only until the agent has looked at them.
- The signature heuristics are tuned on real logs (Playwright, npm, Stryker)
  and will improve; changing them bumps a version so cached signatures are
  recomputed.
- Logs older than GitHub's retention (90 days by default) cannot be read.
