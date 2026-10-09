"""Propose a fix for one finding: fixer, code checks, reviewer, at most one revision."""

from collections.abc import Callable
from dataclasses import dataclass

from anthropic import Anthropic

from flakipype.agent.budget import InvestigationBudget, Limits, RunBudget
from flakipype.agent.finding_tools import ContentsSource, FindingTools, LogSource
from flakipype.agent.fix_tools import FixTools
from flakipype.agent.fixer import FixDecision, Fixer, FixOutcome, FixProposal, FixReview, FixStatus
from flakipype.agent.investigator import ModelSettings
from flakipype.agent.masking import Masker
from flakipype.agent.pipeline import finding_text
from flakipype.agent.prompts import FIX_REVIEWER_SYSTEM, data_block
from flakipype.agent.reviewer import Reviewer, ReviewKind, ReviewUnavailableError
from flakipype.agent.verdict import Verdict
from flakipype.agent.workcopy import FileChange, RepositoryFiles, WorkingCopy, unified_diff
from flakipype.flaky.findings import Evidence, Finding

FIX_REVIEW = ReviewKind(FIX_REVIEWER_SYSTEM, "Submit your review of the fix.", FixReview)
# The fixer reads files of its working copy, not of arbitrary refs.
_REPLACED_TOOLS = frozenset({"read_file"})

type ChangeCheck = Callable[[list[FileChange]], list[str]]


@dataclass(frozen=True)
class FixConfig:
    client: Anthropic
    settings: ModelSettings
    limits: Limits
    masker: Masker
    logs: LogSource
    contents: ContentsSource
    files: RepositoryFiles
    clock: Callable[[], float]
    excerpt_lines: int = 120


@dataclass(frozen=True)
class FixRequest:
    finding: Finding
    evidence: Evidence
    verdict: Verdict
    commit: str
    default_branch: str
    check: ChangeCheck
    # An earlier proposal to start from, and what the user wants changed in it.
    earlier: tuple[FileChange, ...] = ()
    instructions: str = ""


@dataclass(frozen=True)
class FixResult:
    status: FixStatus
    proposal: FixProposal | None
    changes: tuple[FileChange, ...]
    accepted: bool
    review: str
    detail: str
    tokens: int


def fix_task(request: FixRequest) -> str:
    key = request.finding.key
    where = f"{key.repository} at commit {request.commit[:12]} of {request.default_branch}"
    parts = [
        finding_text(request.finding),
        data_block("verdict", request.verdict.model_dump_json(indent=2)),
        f"The working copy is {where}.",
    ]
    if request.instructions:
        parts.append(
            "The working copy already holds an earlier proposal. The user asked in the chat for "
            f"these changes to it:\n{request.instructions}"
        )
    parts.append("Fix the cause and submit with submit_fix.")
    return "\n\n".join(parts)


def review_task(task: str, proposal: FixProposal, changes: list[FileChange]) -> str:
    return "\n\n".join([
        task,
        data_block("proposal", f"{proposal.title}\n\n{proposal.explanation}"),
        data_block("diff", unified_diff(changes)),
        "Review this fix and answer with submit_review.",
    ])  # fmt: skip


def propose_fix(config: FixConfig, request: FixRequest) -> FixResult:
    budget = InvestigationBudget(config.limits, RunBudget(config.limits.tokens), config.clock)
    copy = WorkingCopy(config.files, request.finding.key.repository, request.commit)
    copy.apply(list(request.earlier))
    finding_tools = FindingTools(
        request.finding, request.evidence, config.logs, config.contents, config.excerpt_lines
    )
    fixer = Fixer(
        client=config.client,
        settings=config.settings,
        tools=[t for t in finding_tools.tools() if t.name not in _REPLACED_TOOLS]
        + FixTools(copy).tools(),
        budget=budget,
        masker=config.masker,
        check=lambda: request.check(copy.changes()),
    )
    reviewer = Reviewer(client=config.client, settings=config.settings, budget=budget)
    task = fix_task(request)

    def result(outcome: FixOutcome, review: str, *, accepted: bool = False) -> FixResult:
        changes = tuple(copy.changes())
        return FixResult(
            outcome.status, outcome.proposal, changes, accepted, review, outcome.detail,
            budget.tokens,
        )  # fmt: skip

    def reviewed(proposal: FixProposal) -> FixReview:
        content = config.masker.mask(review_task(task, proposal, copy.changes()))
        return reviewer.ask(FIX_REVIEW, content)

    outcome = fixer.start(task)
    if outcome.proposal is None:
        return result(outcome, "")
    try:
        review = reviewed(outcome.proposal)
    except ReviewUnavailableError as error:
        return result(outcome, f"not reviewed: {error}")
    if review.decision is not FixDecision.REVISE:
        return result(outcome, _describe(review), accepted=review.decision is FixDecision.ACCEPT)
    revised = fixer.revise(review.points or [review.reason])
    if revised.proposal is None:
        return result(revised, f"sent back, revision ended: {revised.detail}")
    try:
        second = reviewed(revised.proposal)
    except ReviewUnavailableError as error:
        return result(revised, f"revised, not reviewed again: {error}")
    return result(
        revised,
        "revised, then " + _describe(second),
        accepted=second.decision is FixDecision.ACCEPT,
    )


def _describe(review: FixReview) -> str:
    labels = {
        FixDecision.ACCEPT: "accepted",
        FixDecision.REVISE: "sent back again",
        FixDecision.REJECT: "rejected",
    }
    return f"{labels[review.decision]}: {review.reason}"
