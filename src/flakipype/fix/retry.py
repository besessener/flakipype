"""Retrying a fix whose verification showed the finding's error again: when, and with what."""

from flakipype.agent.fix_pipeline import FailedVerification
from flakipype.fix.state import OpenedPull


def why_no_retry(pull: OpenedPull, max_attempts: int) -> str:
    """Why the pull request cannot get one more fix now; empty when it can."""
    if not pull.verified:
        return "its verification is still running"
    if not pull.verification.same_error_jobs:
        return "its verification did not show the finding's error again, so nothing is retried"
    if pull.attempt >= max_attempts:
        return (
            f"it holds attempt {pull.attempt} of {max_attempts} (fix.max_attempts), "
            "so the rest stays with you"
        )
    return ""


def failed_verification(pull: OpenedPull) -> FailedVerification:
    verification = pull.verification
    return FailedVerification(pull.branch, verification.same_error_jobs, verification.outcome)


def retry_hint(pull: OpenedPull, max_attempts: int) -> str:
    """Added to the note of a finished verification when /fix may try again."""
    if not pull.may_retry(max_attempts):
        return ""
    return (
        f"\nThe fix did not hold: /fix {pull.finding} tries again with the failure log "
        f"(attempt {pull.attempt + 1} of {max_attempts})."
    )
