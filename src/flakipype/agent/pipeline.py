"""Investigate one finding: investigator, citation check, reviewer, at most one revision."""

from collections.abc import Callable
from dataclasses import dataclass

from anthropic import Anthropic

from flakipype.agent.budget import InvestigationBudget, Limits, RunBudget
from flakipype.agent.finding_tools import ContentsSource, FindingTools, LogSource
from flakipype.agent.investigator import Investigator, ModelSettings, Outcome, Status
from flakipype.agent.masking import Masker
from flakipype.agent.prompts import data_block
from flakipype.agent.reviewer import Reviewer, ReviewUnavailableError
from flakipype.agent.tools import Mode, PolicyGate, deny_all
from flakipype.agent.verdict import Decision, Review, Verdict, apply_review
from flakipype.flaky.findings import Evidence, Finding


@dataclass(frozen=True)
class AgentConfig:
    client: Anthropic
    settings: ModelSettings
    limits: Limits
    masker: Masker
    logs: LogSource
    contents: ContentsSource
    clock: Callable[[], float]
    excerpt_lines: int = 120


@dataclass(frozen=True)
class FindingResult:
    status: Status
    verdict: Verdict | None
    review: str
    detail: str
    tokens: int
    rounds: int


def finding_text(finding: Finding) -> str:
    key = finding.key
    lines = [
        f"Repository: {key.repository}",
        f"Workflow: {key.workflow_name} ({key.workflow_path})",
        f"Job: {key.job}",
        f"First failed step: {key.step or 'unknown'}",
        *finding.facts,
        "Failed jobs, newest first: " + ", ".join(str(job_id) for job_id in finding.job_ids[:10]),
    ]
    return data_block("finding", "\n".join(lines), number=str(finding.number))


def describe_review(review: Review, *, revised: bool) -> str:
    prefix = "revised, then " if revised else ""
    if review.decision is Decision.ACCEPT:
        return f"{prefix}accepted: {review.reason}"
    return f"{prefix}{review.decision.value}: {review.reason}"


def investigate_finding(
    config: AgentConfig, finding: Finding, *, evidence: Evidence, run_budget: RunBudget
) -> FindingResult:
    budget = InvestigationBudget(config.limits, run_budget, config.clock)
    tools = FindingTools(finding, evidence, config.logs, config.contents, config.excerpt_lines)
    investigator = Investigator(
        client=config.client,
        settings=config.settings,
        tools=tools.tools(),
        # Investigations only read; nothing beyond that is confirmed in a headless run.
        gate=PolicyGate(Mode.ASK, deny_all),
        budget=budget,
        masker=config.masker,
    )
    text = finding_text(finding)
    reviewer = Reviewer(client=config.client, settings=config.settings, budget=budget)

    def result(outcome: Outcome, verdict: Verdict | None, review: str) -> FindingResult:
        return FindingResult(
            outcome.status, verdict, review, outcome.detail, budget.tokens, budget.rounds
        )

    outcome = investigator.start(text)
    if outcome.verdict is None:
        return result(outcome, None, "")
    try:
        review = reviewer.review(text, outcome.verdict, config.masker)
    except ReviewUnavailableError as error:
        return result(outcome, outcome.verdict, f"not reviewed: {error}")
    if review.decision is not Decision.REVISE:
        return result(
            outcome, apply_review(outcome.verdict, review), describe_review(review, revised=False)
        )
    revised = investigator.revise(review.questions)
    if revised.verdict is None:
        note = f"sent back, revision ended: {revised.detail}"
        return result(outcome, apply_review(outcome.verdict, review), note)
    try:
        second = reviewer.review(text, revised.verdict, config.masker)
    except ReviewUnavailableError as error:
        return result(revised, revised.verdict, f"revised, second review unavailable: {error}")
    return result(
        revised, apply_review(revised.verdict, second), describe_review(second, revised=True)
    )
