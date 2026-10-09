"""Who is logged in to gh, and does the token carry the scopes flakipype needs."""

import json
from dataclasses import dataclass

from flakipype.github.gh import GhCli, GhCommandError

REQUIRED_SCOPES = frozenset({"repo", "workflow", "read:org"})
_IMPLIED_BY = {"read:org": frozenset({"write:org", "admin:org"})}
_GH_EXIT_AUTH_REQUIRED = 4
_SCOPES_HEADER = "x-oauth-scopes"


@dataclass(frozen=True)
class Authenticated:
    login: str
    # None for fine-grained tokens and GitHub App tokens: GitHub does not report their permissions.
    scopes: frozenset[str] | None

    @property
    def missing_scopes(self) -> frozenset[str]:
        if self.scopes is None:
            return frozenset()
        granted = self.scopes
        return frozenset(
            scope
            for scope in REQUIRED_SCOPES
            if scope not in granted and not (_IMPLIED_BY.get(scope, frozenset()) & granted)
        )


@dataclass(frozen=True)
class NotAuthenticated:
    detail: str


@dataclass(frozen=True)
class AuthCheckFailed:
    detail: str


type AuthStatus = Authenticated | NotAuthenticated | AuthCheckFailed


def parse_user_response(output: str) -> Authenticated:
    """Parse `gh api user --include`: status line, headers, blank line, JSON body."""
    head, _, body = output.replace("\r\n", "\n").partition("\n\n")
    scopes: frozenset[str] | None = None
    for line in head.splitlines()[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() == _SCOPES_HEADER:
            scopes = frozenset(scope.strip() for scope in value.split(",") if scope.strip())
    login = str(json.loads(body)["login"])
    return Authenticated(login=login, scopes=scopes)


def auth_status(gh: GhCli) -> AuthStatus:
    result = gh.run(["api", "user", "--include"])
    if result.succeeded:
        try:
            return parse_user_response(result.stdout)
        except (ValueError, KeyError) as error:
            return AuthCheckFailed(f"Unexpected answer from gh: {error}")
    detail = result.stderr.strip()
    if result.exit_code == _GH_EXIT_AUTH_REQUIRED or "HTTP 401" in detail:
        return NotAuthenticated(detail)
    return AuthCheckFailed(detail or f"gh exited with code {result.exit_code}")


def login_with_token(gh: GhCli, token: str) -> None:
    result = gh.run(["auth", "login", "--hostname", gh.host, "--with-token"], stdin_text=token)
    if not result.succeeded:
        raise GhCommandError(result)


def browser_login_arguments(host: str) -> list[str]:
    scopes = ",".join(sorted(REQUIRED_SCOPES))
    return [
        "auth",
        "login",
        "--hostname",
        host,
        "--web",
        "--git-protocol",
        "https",
        "--scopes",
        scopes,
    ]


def refresh_scopes_command(host: str, missing: frozenset[str]) -> str:
    return f"gh auth refresh --hostname {host} --scopes {','.join(sorted(missing))}"
