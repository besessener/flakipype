from pathlib import Path

import click
import pytest
from typer.testing import CliRunner, Result

from flakipype.agent.tools import Mode
from flakipype.cli import app, wiring
from flakipype.setup.daemon import CommandResult, Daemon, UnitOptions

from support.fake_daemon import FakeRunner

runner = CliRunner()


@pytest.fixture
def systemd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeRunner:
    fake = FakeRunner({"loginctl": CommandResult(0, "no")})
    service = Daemon(unit_dir=tmp_path / "units", run=fake, user="me")
    monkeypatch.setattr(wiring, "build_daemon", lambda: service)

    def unit_options(schedule: str, mode: Mode) -> UnitOptions:
        return UnitOptions(Path("/home/me/.local/bin/flakipype"), schedule, mode.value)

    monkeypatch.setattr(wiring, "unit_options", unit_options)
    return fake


def output_of(result: Result) -> str:
    return " ".join(click.unstyle(result.output).split())


def test_install_print_changes_nothing(systemd: FakeRunner) -> None:
    result = runner.invoke(app, ["daemon", "install", "--print", "--mode", "ask"])

    assert result.exit_code == 0
    assert "# --- flakipype.service" in result.output
    assert "ExecStart=/home/me/.local/bin/flakipype run --mode ask" in result.output
    assert "TimeoutStartSec=730min" in result.output
    assert systemd.calls == []


def test_install_starts_the_timer_and_passes_on_notes(systemd: FakeRunner) -> None:
    result = runner.invoke(app, ["daemon", "install", "--schedule", "Mon..Fri 06:00"])

    assert result.exit_code == 0, result.output
    assert "Installed and started flakipype.timer (Mon..Fri 06:00) in" in output_of(result)
    assert "Note: The timer only runs while you are logged in." in output_of(result)
    assert systemd.calls[0] == "systemd-analyze calendar Mon..Fri 06:00"


def test_a_failed_install_says_why(systemd: FakeRunner) -> None:
    systemd.answers["systemd-run"] = CommandResult(2, "Not ready: No API key stored.")

    result = runner.invoke(app, ["daemon", "install"])

    assert result.exit_code == 1
    assert "Not installed: `flakipype doctor` failed in the environment" in output_of(result)
    assert result.stdout == ""
    assert "No API key stored." in output_of(result)


def test_install_needs_a_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(schedule: str, mode: Mode) -> UnitOptions:
        message = f"Cannot read config.toml for {schedule} in {mode}. Run `flakipype setup`."
        raise wiring.NotReadyError(message)

    monkeypatch.setattr(wiring, "unit_options", broken)

    result = runner.invoke(app, ["daemon", "install"])

    assert result.exit_code == 2
    assert "Not ready: Cannot read config.toml" in click.unstyle(result.stderr)
    assert result.stdout == ""


def test_uninstall_and_status(systemd: FakeRunner) -> None:
    nothing = runner.invoke(app, ["daemon", "uninstall"])
    runner.invoke(app, ["daemon", "install"])
    systemd.answers["journalctl"] = CommandResult(0, "flakipype run · octo-org · auto")
    status = runner.invoke(app, ["daemon", "status"])
    systemd.answers["systemctl --user disable"] = CommandResult(1, "Access denied")
    refused = runner.invoke(app, ["daemon", "uninstall"])
    del systemd.answers["systemctl --user disable"]
    removed = runner.invoke(app, ["daemon", "uninstall"])

    assert output_of(nothing) == "Nothing to remove."
    assert "Last run: flakipype run · octo-org · auto" in output_of(status)
    assert (refused.exit_code, refused.stdout) == (1, "")
    assert "Not removed: `systemctl --user disable --now flakipype.timer` failed" in (
        output_of(refused)
    )
    assert output_of(removed) == "Removed flakipype.timer, flakipype.service."


def test_daemon_alone_shows_its_commands() -> None:
    result = runner.invoke(app, ["daemon"])

    assert "install" in result.output
    assert "uninstall" in result.output
