import contextlib
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import Button, Input, Static

from flakipype.config.secrets import LLM_API_KEY
from flakipype.config.settings import load_settings
from flakipype.llm.connection import ConnectionFailed, ConnectionProblem
from flakipype.tui.setup_wizard import SetupWizard, StatusLine

from support.fake_gh import FakeGh
from support.fake_setup import (
    USER_CALL,
    complete_draft,
    logged_in,
    setup_world,
)

SIZE = (110, 60)


async def settle(pilot: Pilot[bool]) -> None:
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def status_text(app: SetupWizard, widget_id: str) -> str:
    return str(app.query_one(f"#{widget_id}", StatusLine).render())


def status_classes(app: SetupWizard, widget_id: str) -> set[str]:
    return set(app.query_one(f"#{widget_id}", StatusLine).classes)


async def click_button(pilot: Pilot[bool], widget_id: str) -> None:
    # Buttons ignore clicks during their 0.2 s press animation, as they would for a person.
    button = pilot.app.query_one(f"#{widget_id}", Button)
    while button.has_class("-active"):
        await pilot.pause(0.05)
    await pilot.click(f"#{widget_id}")


async def type_into(pilot: Pilot[bool], widget_id: str, text: str) -> None:
    await pilot.click(f"#{widget_id}")
    await pilot.press(*text)


async def test_fresh_setup_is_filled_in_and_saved(tmp_path: Path, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)
    world = setup_world(tmp_path, fake_gh)
    app = SetupWizard(world.service)

    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert "octocat" in status_text(app, "auth-status")
        assert "2.102.0" in status_text(app, "gh-status")
        await type_into(pilot, "api-key", "key-1")
        await type_into(pilot, "model", "m-1")
        await type_into(pilot, "owner", "octo-org")
        await click_button(pilot, "save")
        await pilot.pause()

    assert app.return_value is True
    assert load_settings(world.paths.config_file).github.owner == "octo-org"
    assert world.secrets.get(LLM_API_KEY) == "key-1"


async def test_save_shows_every_missing_field(tmp_path: Path, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)
    app = SetupWizard(setup_world(tmp_path, fake_gh).service)

    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("ctrl+s")
        await pilot.pause()
        message = str(app.query_one("#save-status", Static).render())

    assert app.return_value is None
    assert "llm.model" in message
    assert "llm.api_key" in message
    assert "github.owner" in message


async def test_existing_settings_are_loaded(tmp_path: Path, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)
    world = setup_world(tmp_path, fake_gh)
    world.service.save(complete_draft())
    app = SetupWizard(world.service)

    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert app.query_one("#owner", Input).value == "octo-org"
        assert app.query_one("#api-key", Input).value == ""
        assert "stored" in app.query_one("#api-key", Input).placeholder


async def test_broken_config_is_shown(tmp_path: Path, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)
    world = setup_world(tmp_path, fake_gh)
    world.paths.config_dir.mkdir(parents=True)
    world.paths.config_file.write_text("broken = = toml", encoding="utf-8")
    app = SetupWizard(world.service)

    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert "Cannot read" in str(app.query_one("#save-status", Static).render())


async def test_connection_test_success_and_failure(tmp_path: Path, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)
    world = setup_world(tmp_path, fake_gh)
    app = SetupWizard(world.service)

    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await click_button(pilot, "test-llm")
        await settle(pilot)
        assert "llm.model" in status_text(app, "llm-status")

        await type_into(pilot, "api-key", "key-1")
        await type_into(pilot, "model", "m-1")
        await click_button(pilot, "test-llm")
        await settle(pilot)
        assert "m-1-20260101" in status_text(app, "llm-status")
        assert "ok" in status_classes(app, "llm-status")

        world.llm.result = ConnectionFailed(ConnectionProblem.NOT_FOUND, "model not found")
        await click_button(pilot, "test-llm")
        await settle(pilot)
        assert "model not found" in status_text(app, "llm-status")
        assert "failed" in status_classes(app, "llm-status")


async def test_gh_download(tmp_path: Path, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)
    world = setup_world(tmp_path, fake_gh)
    world.gh.installed = None
    app = SetupWizard(world.service)

    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert "No gh" in status_text(app, "gh-status")
        await click_button(pilot, "install-gh")
        await settle(pilot)
        assert "2.102.0" in status_text(app, "gh-status")
        assert "octocat" in status_text(app, "auth-status")


async def test_gh_download_failure(tmp_path: Path, fake_gh: FakeGh) -> None:
    world = setup_world(tmp_path, fake_gh)
    world.gh.installed = None
    world.gh.install_error = "Checksum mismatch for gh.tar.gz"
    app = SetupWizard(world.service)

    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await click_button(pilot, "install-gh")
        await settle(pilot)
        assert "Checksum mismatch" in status_text(app, "gh-status")
        assert "failed" in status_classes(app, "gh-status")


async def test_token_login(tmp_path: Path, fake_gh: FakeGh) -> None:
    fake_gh.record(USER_CALL, stderr="To get started with GitHub CLI", exit_code=4)
    token_login = ["auth", "login", "--hostname", "github.com", "--with-token"]
    fake_gh.record(token_login, stderr="error validating token: HTTP 401", exit_code=1)
    app = SetupWizard(setup_world(tmp_path, fake_gh).service)

    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        assert "Not logged in" in status_text(app, "auth-status")

        await click_button(pilot, "login-token")
        await pilot.pause()
        assert "Paste a token first" in status_text(app, "auth-status")

        await type_into(pilot, "token", "bad-token")
        await click_button(pilot, "login-token")
        await settle(pilot)
        assert "error validating token" in status_text(app, "auth-status")

        fake_gh.calls.clear()
        fake_gh.record(token_login)
        logged_in(fake_gh)
        await click_button(pilot, "login-token")
        await settle(pilot)
        assert "octocat" in status_text(app, "auth-status")
        assert app.query_one("#token", Input).value == ""


async def test_browser_login_without_a_real_terminal_shows_the_command(
    tmp_path: Path, fake_gh: FakeGh
) -> None:
    logged_in(fake_gh)
    world = setup_world(tmp_path, fake_gh)
    app = SetupWizard(world.service)

    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await click_button(pilot, "login-browser")
        await pilot.pause()
        assert "gh auth login --hostname github.com --web" in status_text(app, "auth-status")

        world.gh.installed = None
        await click_button(pilot, "login-browser")
        await pilot.pause()
        assert "Download gh first" in status_text(app, "auth-status")


async def test_browser_login_hands_over_the_terminal_and_refreshes(
    tmp_path: Path, fake_gh: FakeGh, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_gh.record(USER_CALL, stderr="To get started with GitHub CLI", exit_code=4)
    browser_login = ["auth", "login", "--hostname", "github.com", "--web"]
    app = SetupWizard(setup_world(tmp_path, fake_gh).service)
    monkeypatch.setattr(app, "suspend", contextlib.nullcontext)

    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        fake_gh.calls.clear()
        fake_gh.record(
            [*browser_login, "--git-protocol", "https", "--scopes", "read:org,repo,workflow"]
        )
        logged_in(fake_gh)
        await click_button(pilot, "login-browser")
        await settle(pilot)
        assert "octocat" in status_text(app, "auth-status")

    assert any(call["args"][:5] == browser_login for call in fake_gh.invocations())


async def test_cancel(tmp_path: Path, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)
    world = setup_world(tmp_path, fake_gh)
    app = SetupWizard(world.service)

    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot)
        await pilot.press("escape")
        await pilot.pause()

    assert app.return_value is False
    assert not world.paths.config_file.exists()


def test_fresh_machine_snapshot(
    tmp_path: Path, fake_gh: FakeGh, snap_compare: Callable[..., bool]
) -> None:
    world = setup_world(tmp_path, fake_gh)
    world.gh.installed = None

    async def run_before(pilot: Pilot[bool]) -> None:
        await settle(pilot)

    run: Callable[[Pilot[bool]], Awaitable[None]] = run_before
    assert snap_compare(SetupWizard(world.service), terminal_size=SIZE, run_before=run)
