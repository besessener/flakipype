"""What a command needs before it starts; NotReadyError says what to set up."""

from flakipype.github.auth import NotAuthenticated, auth_status
from flakipype.github.gh import GhCli
from flakipype.setup.doctor import RUN_SETUP


class NotReadyError(Exception):
    """flakipype is not set up far enough for this command; the message says what to do."""


def check_logged_in(gh: GhCli, host: str) -> None:
    """A missing or expired login is a setup problem, not a failed run; other answers go on."""
    status = auth_status(gh)
    if isinstance(status, NotAuthenticated):
        message = f"gh is not logged in to {host}, or its token expired. {RUN_SETUP}"
        raise NotReadyError(message)


def check_run_owner(owner: str, configured: str) -> None:
    """A run fixes only the configured owner, so it never scans one it may not fix."""
    if configured and owner.lower() == configured.lower():
        return
    message = (
        f"A run fixes only the configured owner ({configured or 'none set'}), not {owner}. "
        "`flakipype scan` and `flakipype investigate` read other owners."
    )
    raise NotReadyError(message)
