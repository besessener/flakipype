"""Texts code writes around a push: the confirmation's facts and what the push did."""

from dataclasses import dataclass

from flakipype.fix.state import OpenedPull, Proposal
from flakipype.fix.verify import Stage, Verification

_PATHS_SHOWN = 3


@dataclass(frozen=True)
class Budgets:
    """What the session used and may use, as the confirmation shows it."""

    pulls_opened: int
    max_pulls: int
    actions_used: int
    max_actions: int
    max_attempts: int


def confirmation(proposal: Proposal, budgets: Budgets) -> tuple[str, tuple[str, ...]]:
    """The dialog's title and facts: a new pull request, or one more commit on one."""
    retry_of = proposal.retry_of
    if retry_of is None:
        return "Push fix and open a draft pull request?", _new_pull_details(proposal, budgets)
    number = retry_of.verification.pull_number
    title = f"Push a revised fix to draft pull request #{number}?"
    return title, _retry_details(proposal, retry_of, budgets)


def opened_text(opened: OpenedPull) -> str:
    verification = opened.verification
    return (
        f"Opened draft pull request #{verification.pull_number}: {opened.url} "
        f"(branch {opened.branch}).\n{_status(verification)}"
    )


def retried_text(pull: OpenedPull, max_attempts: int, problem: str) -> str:
    verification = pull.verification
    lines = [
        (
            f"Pushed a revised fix to draft pull request #{verification.pull_number}: "
            f"{pull.url} (attempt {pull.attempt} of {max_attempts}, "
            f"commit {verification.commit[:7]})."
        ),
        _status(verification),
    ]
    if problem:
        lines.append(problem)
    return "\n".join(lines)


def _new_pull_details(proposal: Proposal, budgets: Budgets) -> tuple[str, ...]:
    verification = proposal.verification
    return (
        f"{proposal.repository} · base {proposal.base} @ {proposal.commit[:7]}",
        f"new branch {verification.branch}",
        _change_summary(proposal),
        _reruns(verification),
        (
            f"Pull requests this session: {budgets.pulls_opened + 1} of {budgets.max_pulls} · "
            f"Actions: {budgets.actions_used} of {budgets.max_actions}"
        ),
        "Opens a draft pull request; merging stays with you.",
        *_warning_lines(proposal),
    )


def _retry_details(proposal: Proposal, retry_of: OpenedPull, budgets: Budgets) -> tuple[str, ...]:
    return (
        f"{proposal.repository} · branch {retry_of.branch} @ {proposal.commit[:7]}",
        (
            f"one more commit on draft pull request #{retry_of.verification.pull_number}, "
            f"attempt {retry_of.attempt + 1} of {budgets.max_attempts}"
        ),
        _change_summary(proposal),
        _reruns(proposal.verification),
        f"Actions: {budgets.actions_used} of {budgets.max_actions}",
        "The pull request stays a draft; merging stays with you.",
        *_warning_lines(proposal),
    )


def _change_summary(proposal: Proposal) -> str:
    changes = proposal.changes
    added = sum(len(change.added) for change in changes)
    removed = sum(len(change.removed) for change in changes)
    paths = [change.path for change in changes]
    shown = ", ".join(paths[:_PATHS_SHOWN]) + (" …" if len(paths) > _PATHS_SHOWN else "")
    return f"{len(changes)} files · +{added} −{removed} · {shown}"


def _reruns(verification: Verification) -> str:
    return f"then reruns {verification.workflow_name} on the fix branch {verification.wanted} times"


def _warning_lines(proposal: Proposal) -> tuple[str, ...]:
    if not proposal.warnings:
        return ("Warnings: none",)
    return ("Warnings:", *(f"⚠ {item}" for item in proposal.warnings))


def _status(verification: Verification) -> str:
    if verification.stage is Stage.DONE:
        return verification.outcome
    return (
        f"Verification: {verification.wanted} runs of {verification.workflow_name} on "
        "the branch; the result follows here and on the pull request."
    )
