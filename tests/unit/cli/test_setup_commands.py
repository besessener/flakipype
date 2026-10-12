import asyncio
from pathlib import Path

import click
import pytest
from typer.testing import CliRunner, Result

from flakipype.cli import app, setup_commands, wiring
from flakipype.config.secrets import LLM_API_KEY, SecretStoreError
from flakipype.config.settings import SecretStoreChoice, load_settings
from flakipype.llm.connection import ConnectionFailed, ConnectionProblem
from flakipype.setup.service import SetupService
from flakipype.tui.setup_wizard import SetupWizard

from support.fake_gh import FakeGh
from support.fake_setup import SetupWorld, complete_draft, logged_in, setup_world

runner = CliRunner()


@pytest.fixture
def chosen_stores() -> list[SecretStoreChoice | None]:
    return []


@pytest.fixture
def world(
    tmp_path: Path,
    fake_gh: FakeGh,
    monkeypatch: pytest.MonkeyPatch,
    chosen_stores: list[SecretStoreChoice | None],
) -> SetupWorld:
    created = setup_world(tmp_path, fake_gh)

    def build(choice: SecretStoreChoice | None = None) -> SetupService:
        chosen_stores.append(choice)
        return created.service

    monkeypatch.setattr(wiring, "build_setup_service", build)
    return created


def output_of(result: Result) -> str:
    return click.unstyle(result.output)


def test_headless_setup_saves_and_reports(world: SetupWorld, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)
    arguments = ["setup", "--non-interactive", "--model", "m-1", "--owner", "octo-org"]

    result = runner.invoke(app, [*arguments, "--api-key-stdin"], input="key-1\n")

    assert result.exit_code == 0, result.output
    assert load_settings(world.paths.config_file).llm.model == "m-1"
    assert world.secrets.get(LLM_API_KEY) == "key-1"
    assert "Saved" in output_of(result)
    assert "octocat" in output_of(result)


def test_headless_setup_saves_the_secret_store(
    world: SetupWorld, fake_gh: FakeGh, chosen_stores: list[SecretStoreChoice | None]
) -> None:
    logged_in(fake_gh)
    world.service.save(complete_draft())
    arguments = ["setup", "--non-interactive", "--secret-store", "file", "--api-key-stdin"]

    result = runner.invoke(app, arguments, input="key-2\n")

    assert result.exit_code == 0, result.output
    assert chosen_stores == [SecretStoreChoice.FILE]
    assert load_settings(world.paths.config_file).secrets.store is SecretStoreChoice.FILE


@pytest.mark.parametrize("command", [["doctor"], ["setup", "--non-interactive"]])
def test_an_unreadable_keyring_explains_the_file_store(
    world: SetupWorld, monkeypatch: pytest.MonkeyPatch, command: list[str]
) -> None:
    def locked(name: str) -> str | None:
        message = f"{name}: the collection is locked"
        raise SecretStoreError(message)

    monkeypatch.setattr(world.secrets, "get", locked)

    result = runner.invoke(app, command)

    assert result.exit_code == 2
    text = " ".join(output_of(result).split())
    assert "Secret store: llm-api-key: the collection is locked" in text
    assert "--secret-store file --api-key-stdin" in text


def test_headless_setup_keeps_existing_values(world: SetupWorld, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)
    world.service.save(complete_draft())

    result = runner.invoke(app, ["setup", "--non-interactive", "--owner", "other-org"])

    assert result.exit_code == 0, result.output
    settings = load_settings(world.paths.config_file)
    assert (settings.llm.model, settings.github.owner) == ("m-1", "other-org")
    assert world.secrets.get(LLM_API_KEY) == "key-1"


def test_headless_setup_rejects_invalid_input(world: SetupWorld) -> None:
    result = runner.invoke(app, ["setup", "--non-interactive", "--owner", "octo-org"])

    assert result.exit_code == 2
    assert "llm.model: is required" in output_of(result)
    assert not world.paths.config_file.exists()


def test_headless_setup_downloads_gh(world: SetupWorld, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)
    world.gh.installed = None
    world.service.save(complete_draft())

    result = runner.invoke(app, ["setup", "--non-interactive"])

    assert result.exit_code == 0, result.output
    assert world.gh.install_count == 1


def test_headless_setup_reports_a_failed_download(world: SetupWorld) -> None:
    world.gh.installed = None
    world.gh.install_error = "Checksum mismatch"
    world.service.save(complete_draft())

    result = runner.invoke(app, ["setup", "--non-interactive"])

    assert result.exit_code == 1
    assert "gh: Checksum mismatch" in output_of(result)


def test_wizard_needs_a_terminal(world: SetupWorld) -> None:
    result = runner.invoke(app, ["setup"])

    assert result.exit_code == 2
    assert "No terminal attached" in output_of(result)
    assert not world.paths.config_file.exists()


def test_wizard_saved_then_checks(
    world: SetupWorld, fake_gh: FakeGh, monkeypatch: pytest.MonkeyPatch
) -> None:
    logged_in(fake_gh)
    monkeypatch.setattr(setup_commands, "is_interactive_terminal", lambda: True)

    def save_and_close(wizard: SetupWizard) -> bool:
        world.service.save(complete_draft())
        return wizard is not None

    monkeypatch.setattr(SetupWizard, "run", save_and_close)

    result = runner.invoke(app, ["setup"])

    assert result.exit_code == 0, result.output
    assert "Configuration" in output_of(result)


def test_wizard_cancelled(world: SetupWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_commands, "is_interactive_terminal", lambda: True)
    monkeypatch.setattr(SetupWizard, "run", lambda _: False)

    result = runner.invoke(app, ["setup"])

    assert result.exit_code == 1
    assert "Setup cancelled" in output_of(result)
    assert not world.paths.config_file.exists()


def test_the_wizard_on_an_unreadable_keyring_explains_the_file_store(
    world: SetupWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    def locked(name: str) -> str | None:
        message = f"{name}: the collection is locked"
        raise SecretStoreError(message)

    monkeypatch.setattr(world.secrets, "get", locked)
    monkeypatch.setattr(setup_commands, "is_interactive_terminal", lambda: True)
    monkeypatch.setattr(SetupWizard, "run", lambda _: pytest.fail("the wizard started"))

    result = runner.invoke(app, ["setup"])

    assert result.exit_code == 2
    text = " ".join(output_of(result).split())
    assert "Secret store: llm-api-key: the collection is locked" in text
    assert "--secret-store file --api-key-stdin" in text


def test_the_wizard_saves_the_chosen_secret_store(
    world: SetupWorld, fake_gh: FakeGh, monkeypatch: pytest.MonkeyPatch
) -> None:
    logged_in(fake_gh)
    world.service.save(complete_draft())
    monkeypatch.setattr(setup_commands, "is_interactive_terminal", lambda: True)

    async def press_save(wizard: SetupWizard) -> bool:
        async with wizard.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
        return bool(wizard.return_value)

    monkeypatch.setattr(SetupWizard, "run", lambda wizard: asyncio.run(press_save(wizard)))

    result = runner.invoke(app, ["setup", "--secret-store", "file"])

    assert result.exit_code == 0, result.output
    assert load_settings(world.paths.config_file).secrets.store is SecretStoreChoice.FILE


def test_doctor_healthy(world: SetupWorld, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)
    world.service.save(complete_draft())

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "✔" in result.output


def test_doctor_failing_shows_the_next_step(world: SetupWorld, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)
    world.service.save(complete_draft())
    world.llm.result = ConnectionFailed(ConnectionProblem.AUTHENTICATION, "invalid x-api-key")

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "invalid x-api-key" in output_of(result)
    assert ConnectionProblem.AUTHENTICATION.next_step in " ".join(output_of(result).split())


def test_is_interactive_terminal_is_false_under_test() -> None:
    assert setup_commands.is_interactive_terminal() is False
