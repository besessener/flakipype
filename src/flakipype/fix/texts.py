"""Texts code writes for a fix: branch name, pull request body, commit, verification comment."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from flakipype.actions.targets import finding_runs
from flakipype.agent.verdict import Verdict
from flakipype.agent.workcopy import FileChange, unified_diff
from flakipype.flaky.findings import Evidence, Finding

BRANCH_PREFIX = "flakipype/"
_SLUG = re.compile(r"[^a-z0-9]+")
_HASH_LENGTH = 6
_ALL_BRANCHES = "all branches"
_PERCENT = 100
_SMALL_NUMBERS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}


@dataclass(frozen=True)
class Rate:
    """How often the finding's job failed (at least once per run) on a branch."""

    failed: int
    total: int
    branch: str

    def chance_of_passes(self, runs: int) -> float:
        """How likely `runs` passes in a row are without any fix, at this rate."""
        return (1 - self.failed / self.total) ** runs


def finding_marker(finding: Finding) -> str:
    """Hidden in the pull request body, so a second /fix finds the open pull request."""
    digest = hashlib.sha256(finding.identity.encode()).hexdigest()[:12]
    return f"<!-- flakipype:finding={digest} -->"


def branch_name(finding: Finding, changes: list[FileChange]) -> str:
    stem = PurePosixPath(finding.key.workflow_path).stem.lower()
    slug = _SLUG.sub("-", stem).strip("-") or "workflow"
    digest = hashlib.sha256(unified_diff(changes).encode()).hexdigest()[:_HASH_LENGTH]
    return f"{BRANCH_PREFIX}fix-{slug}-{digest}"


def failure_rate(finding: Finding, evidence: Evidence, branch: str) -> Rate:
    key = finding.key
    finished = [
        run
        for run in evidence.runs
        if run.repository == key.repository
        and run.workflow_path == key.workflow_path
        and run.conclusion is not None
    ]
    failed = {run.run_id for run in finding_runs(finding, evidence)}
    on_branch = [run for run in finished if run.head_branch == branch]
    if on_branch:
        return Rate(sum(run.run_id in failed for run in on_branch), len(on_branch), branch)
    return Rate(sum(run.run_id in failed for run in finished), len(finished), _ALL_BRANCHES)


def rate_text(rate: Rate, workflow: str) -> str:
    if rate.total == 0:
        return ""
    where = "on all branches" if rate.branch == _ALL_BRANCHES else f"on {rate.branch}"
    share = round(_PERCENT * rate.failed / rate.total)
    return f"{where.capitalize()}, {workflow} failed {rate.failed} of {rate.total} runs ({share}%)"


@dataclass(frozen=True)
class PullRequestFacts:
    finding: Finding
    verdict: Verdict
    rate: Rate
    warnings: tuple[str, ...]
    verify_runs: int


def pull_request_body(facts: PullRequestFacts, explanation: str) -> str:
    key, verdict = facts.finding.key, facts.verdict
    rate = rate_text(facts.rate, key.workflow_name)
    scan = (
        f"**Scan facts:** {rate} in the scanned window." if rate else "**Scan facts:** see below."
    )
    facts_list = "\n".join(f"- {fact}" for fact in facts.finding.facts)
    warnings = "\n".join(f"- {warning}" for warning in facts.warnings) or "none"
    return f"""{finding_marker(facts.finding)}
## Flaky: {key.job} in {key.repository}

{scan}

{facts_list}

**Verdict** (model's assessment, reviewed): {verdict.classification.value}, \
{verdict.confidence.value} confidence. {verdict.summary}

### The change (written by the model)

{explanation}

### Warnings

{warnings}

### Verification

Pending: flakipype reruns {key.workflow_name} on this branch {facts.verify_runs} times.

---
Opened by flakipype as a draft. Merging is up to you.
"""


def commit_body(explanation: str) -> str:
    return f"{explanation}\n\nGenerated-by: flakipype"


@dataclass(frozen=True)
class VerificationFacts:
    workflow: str
    # One entry per finished run: "passed", or what failed.
    results: tuple[str, ...]
    wanted: int
    rate: Rate
    stopped: str = ""


def verification_text(facts: VerificationFacts) -> str:
    passed = sum(result == "passed" for result in facts.results)
    lines = [
        (
            f"flakipype verification: {facts.workflow} passed {passed} of "
            f"{len(facts.results)} runs on this branch."
        )
    ]
    lines.extend(
        f"Run {index} {result}."
        for index, result in enumerate(facts.results, 1)
        if result != "passed"
    )
    if facts.stopped:
        lines.append(f"Stopped after {len(facts.results)} of {facts.wanted} runs: {facts.stopped}.")
    rate = rate_text(facts.rate, facts.workflow)
    if rate:
        lines.append(f"{rate} in the scanned window.")
    if rate and facts.results and passed == len(facts.results):
        chance = round(_PERCENT * facts.rate.chance_of_passes(passed))
        count = _SMALL_NUMBERS.get(passed, str(passed))
        passes = "passes in a row" if passed > 1 else "pass"
        lines.append(
            f"{count} {passes} would also happen by chance {chance}% of the time without a fix, "
            "so this is a first signal, not proof."
        )
    return "\n".join(lines)
