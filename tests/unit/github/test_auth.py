import os

import pytest

from flakipype.github.auth import (
    AuthCheckFailed,
    Authenticated,
    NotAuthenticated,
    auth_status,
    browser_login_arguments,
    login_with_token,
    parse_user_response,
    refresh_scopes_command,
)
from flakipype.github.gh import GhCommandError, without_windows_drives

from support.fake_gh import FakeGh, gh_fixture

USER_CALL = ["api", "user", "--include"]


def test_recorded_user_response_is_parsed() -> None:
    authenticated = parse_user_response(gh_fixture("api-user-include.txt"))

    assert authenticated.login == "octocat"
    assert authenticated.scopes == frozenset({"gist", "read:org", "repo", "workflow"})
    assert authenticated.missing_scopes == frozenset()


def test_crlf_output_without_scope_header_means_unknown_scopes() -> None:
    output = 'HTTP/2.0 200 OK\r\nContent-Type: application/json\r\n\r\n{"login": "bot"}'

    authenticated = parse_user_response(output)

    assert authenticated == Authenticated(login="bot", scopes=None)
    assert authenticated.missing_scopes == frozenset()


@pytest.mark.parametrize(
    ("scopes", "missing"),
    [
        ({"repo"}, {"workflow", "read:org"}),
        ({"repo", "workflow", "admin:org"}, set()),
        ({"repo", "workflow", "write:org"}, set()),
        (set(), {"repo", "workflow", "read:org"}),
    ],
)
def test_missing_scopes(scopes: set[str], missing: set[str]) -> None:
    assert Authenticated("me", frozenset(scopes)).missing_scopes == missing


def test_auth_status_through_gh(fake_gh: FakeGh) -> None:
    fake_gh.record(USER_CALL, stdout=gh_fixture("api-user-include.txt"))

    status = auth_status(fake_gh.cli(host="github.example.com"))

    assert isinstance(status, Authenticated)
    assert status.login == "octocat"
    assert fake_gh.invocations()[0]["gh_host"] == "github.example.com"


@pytest.mark.parametrize(
    ("exit_code", "stderr"),
    [
        (4, "To get started with GitHub CLI, please run:  gh auth login\n"),
        (1, "gh: Bad credentials (HTTP 401)\n"),
    ],
)
def test_not_logged_in(fake_gh: FakeGh, exit_code: int, stderr: str) -> None:
    fake_gh.record(USER_CALL, stderr=stderr, exit_code=exit_code)

    assert isinstance(auth_status(fake_gh.cli()), NotAuthenticated)


def test_unreachable_host(fake_gh: FakeGh) -> None:
    fake_gh.record(USER_CALL, stderr="error connecting to ghes.example\n", exit_code=1)

    assert auth_status(fake_gh.cli()) == AuthCheckFailed("error connecting to ghes.example")


def test_failure_without_message(fake_gh: FakeGh) -> None:
    fake_gh.record(USER_CALL, exit_code=2)

    assert auth_status(fake_gh.cli()) == AuthCheckFailed("gh exited with code 2")


def test_garbled_answer(fake_gh: FakeGh) -> None:
    fake_gh.record(USER_CALL, stdout="HTTP/2.0 200 OK\n\nnot json")

    status = auth_status(fake_gh.cli())

    assert isinstance(status, AuthCheckFailed)
    assert "Unexpected answer" in status.detail


def test_login_with_token_passes_the_token_on_stdin(fake_gh: FakeGh) -> None:
    arguments = ["auth", "login", "--hostname", "github.com", "--with-token"]
    fake_gh.record(arguments)

    login_with_token(fake_gh.cli(), "token-value")

    invocation = fake_gh.invocations()[0]
    assert invocation["args"] == arguments
    assert invocation["stdin"] == "token-value"


def test_rejected_token_raises(fake_gh: FakeGh) -> None:
    arguments = ["auth", "login", "--hostname", "github.com", "--with-token"]
    fake_gh.record(arguments, stderr="error validating token: HTTP 401\n", exit_code=1)

    with pytest.raises(GhCommandError, match="error validating token"):
        login_with_token(fake_gh.cli(), "bad")


def test_command_error_without_stderr_names_the_exit_code(fake_gh: FakeGh) -> None:
    arguments = ["auth", "login", "--hostname", "github.com", "--with-token"]
    fake_gh.record(arguments, exit_code=3)

    with pytest.raises(GhCommandError, match="exited with code 3"):
        login_with_token(fake_gh.cli(), "bad")


def test_browser_login_requests_the_required_scopes() -> None:
    arguments = browser_login_arguments("github.com")

    assert arguments[:5] == ["auth", "login", "--hostname", "github.com", "--web"]
    assert arguments[-1] == "read:org,repo,workflow"


def test_refresh_hint() -> None:
    hint = refresh_scopes_command("github.com", frozenset({"workflow", "read:org"}))

    assert hint == "gh auth refresh --hostname github.com --scopes read:org,workflow"


@pytest.mark.skipif(os.pathsep != ":", reason="POSIX PATH separator")
def test_windows_drives_are_removed_from_path() -> None:
    path = "/usr/local/bin:/mnt/c/Windows/system32:/usr/bin:/mnt/d:/mnt/data/tools:/bin"

    assert without_windows_drives(path) == "/usr/local/bin:/usr/bin:/mnt/data/tools:/bin"


def test_gh_runs_without_windows_drives_on_path(
    fake_gh: FakeGh, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", os.pathsep.join(["/mnt/c/Windows", "/usr/bin"]))
    fake_gh.record(["auth", "status"])

    fake_gh.cli().run(["auth", "status"])

    assert fake_gh.invocations()[0]["path"] == "/usr/bin"


def test_interactive_run_returns_the_exit_code(fake_gh: FakeGh) -> None:
    fake_gh.record(["auth", "status"], exit_code=0)

    assert fake_gh.cli().run_interactive(["auth", "status"]) == 0
