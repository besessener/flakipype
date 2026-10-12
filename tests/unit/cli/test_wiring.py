import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from keyring.backends import fail

from flakipype.agent.tools import ActionRequest, Mode, ToolError
from flakipype.cli.wiring import (
    NotReadyError,
    build_daemon,
    build_setup_service,
    check_llm_endpoint,
    open_chat,
    open_investigation,
    open_run,
    open_scan,
    unit_options,
)
from flakipype.config.secrets import LLM_API_KEY, FileSecretStore
from flakipype.config.settings import SecretStoreChoice, Settings
from flakipype.fix.service import FixTarget
from flakipype.github.binary import GhBinary
from flakipype.github.provider import ManagedGh
from flakipype.llm.client import LlmEndpoint
from flakipype.llm.connection import ConnectionFailed, ConnectionProblem
from flakipype.scan.service import ScanRequest
from flakipype.setup.daemon import UnitOptions
from flakipype.store.lock import RunLockedError
from flakipype.unattended.service import RunService

from support.fake_fix import verdict
from support.fake_runs import e2e_evidence, e2e_finding


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    yield tmp_path
    keyring.set_keyring(previous)


def write_config(home: Path, content: str) -> None:
    config_dir = home / "config" / "flakipype"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(content, encoding="utf-8")


def test_service_uses_xdg_dirs_and_the_file_fallback(isolated_home: Path) -> None:
    service = build_setup_service()

    assert service.paths.config_dir == isolated_home / "config" / "flakipype"
    assert service.secret_location.startswith("file ")
    assert service.find_gh() is None


@pytest.mark.parametrize(
    ("config", "choice", "location"),
    [
        ('[secrets]\nstore = "keyring"\n', None, "system keyring"),
        ('[secrets]\nstore = "keyring"\n', SecretStoreChoice.FILE, "file "),
        ("broken = = toml", None, "file "),
    ],
)
def test_the_setup_service_uses_the_chosen_or_saved_store(
    isolated_home: Path, config: str, choice: SecretStoreChoice | None, location: str
) -> None:
    write_config(isolated_home, config)

    assert build_setup_service(choice).secret_location.startswith(location)


def test_an_unreadable_keyring_is_not_ready(isolated_home: Path) -> None:
    write_config(isolated_home, '[llm]\nmodel = "m-1"\n\n[secrets]\nstore = "keyring"\n')

    with (
        pytest.raises(NotReadyError, match=r"Cannot read the API key from the system keyring"),
        open_investigation(),
    ):
        pass


def test_a_run_holds_the_lock_and_is_wired_with_the_mode(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(isolated_home, '[llm]\nmodel = "m-1"\n\n[github]\nowner = "octo-org"\n')
    store_api_key(isolated_home)
    binary = GhBinary(path=isolated_home / "gh", version=(2, 102, 0))
    monkeypatch.setattr(ManagedGh, "find", lambda _: binary)
    requests: list[str] = []

    def request_for(settings: Settings) -> ScanRequest:
        requests.append(settings.github.owner)
        return ScanRequest("octo-org", "github.com", 30, 50)

    with open_run(Mode.ASK, request_for) as service:
        assert isinstance(service, RunService)
        with pytest.raises(RunLockedError), open_run(Mode.AUTO, request_for):
            pass

    assert requests == ["octo-org"]
    assert (isolated_home / "data" / "flakipype" / "run.lock").exists()


def test_the_daemon_and_its_units_come_from_the_environment(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(isolated_home, "[run]\nmax_minutes = 30\n")
    command = isolated_home / "bin" / "flakipype"
    monkeypatch.setattr(sys, "argv", [str(command), "daemon", "install"])
    monkeypatch.setattr(shutil, "which", lambda _: str(command))

    options = unit_options("weekly", Mode.AUTO)

    assert options == UnitOptions(command, "weekly", "auto", 30)
    assert build_daemon().unit_dir == isolated_home / "config" / "systemd" / "user"


def test_llm_check_against_a_closed_local_port() -> None:
    endpoint = LlmEndpoint(base_url="http://127.0.0.1:9", api_key="unused", model="m-1")

    result = check_llm_endpoint(endpoint)

    assert isinstance(result, ConnectionFailed)
    assert result.problem is ConnectionProblem.UNREACHABLE


FOUNDRY_URL = "https://acme.services.ai.azure.com/anthropic"


def test_llm_check_names_a_conflicting_foundry_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "acme")
    endpoint = LlmEndpoint(base_url=FOUNDRY_URL, api_key="unused", model="m-1")

    result = check_llm_endpoint(endpoint)

    assert isinstance(result, ConnectionFailed)
    assert result.problem is ConnectionProblem.ENVIRONMENT
    assert "ANTHROPIC_FOUNDRY_RESOURCE" in result.detail


def test_scan_needs_a_readable_config(isolated_home: Path) -> None:
    write_config(isolated_home, "broken = = toml")

    with pytest.raises(NotReadyError, match="Run `flakipype setup`"), open_scan():
        pass


@pytest.mark.usefixtures("isolated_home")
def test_scan_needs_gh() -> None:
    with pytest.raises(NotReadyError, match="No usable gh found"), open_scan():
        pass


def test_scan_is_wired_with_settings_and_a_cache(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(isolated_home, '[github]\nowner = "octo-org"\n\n[scan]\nwindow_days = 7\n')
    binary = GhBinary(path=isolated_home / "gh", version=(2, 102, 0))
    monkeypatch.setattr(ManagedGh, "find", lambda _: binary)

    with open_scan() as (_, settings):
        assert settings.github.owner == "octo-org"
        assert settings.scan.window_days == 7

    assert (isolated_home / "data" / "flakipype" / "cache.sqlite3").exists()


def store_api_key(home: Path) -> None:
    FileSecretStore(home / "config" / "flakipype" / "secrets.json").put(LLM_API_KEY, "key-1")


@pytest.mark.parametrize(
    ("config", "with_key", "reason"),
    [
        ('[github]\nowner = "octo-org"\n', True, "No model configured"),
        ('[llm]\nmodel = "m-1"\n', False, "No API key stored"),
    ],
)
def test_investigation_needs_model_and_key(
    isolated_home: Path,
    config: str,
    with_key: bool,  # noqa: FBT001 - parametrised test data
    reason: str,
) -> None:
    write_config(isolated_home, config)
    if with_key:
        store_api_key(isolated_home)

    with pytest.raises(NotReadyError, match=reason), open_investigation():
        pass


def test_investigation_is_wired_with_agent_settings(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = '[llm]\nmodel = "m-1"\n\n[github]\nowner = "octo-org"\n\n[agent]\nparallel = 2\n'
    write_config(isolated_home, config)
    store_api_key(isolated_home)
    binary = GhBinary(path=isolated_home / "gh", version=(2, 102, 0))
    monkeypatch.setattr(ManagedGh, "find", lambda _: binary)

    with open_investigation() as (service, settings):
        assert settings.agent.parallel == 2
        assert service is not None


def test_a_conflicting_foundry_resource_is_not_ready(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "acme")
    write_config(isolated_home, f'[llm]\nmodel = "m-1"\nbase_url = "{FOUNDRY_URL}"\n')
    store_api_key(isolated_home)
    binary = GhBinary(path=isolated_home / "gh", version=(2, 102, 0))
    monkeypatch.setattr(ManagedGh, "find", lambda _: binary)

    with pytest.raises(NotReadyError, match="ANTHROPIC_FOUNDRY_RESOURCE"), open_investigation():
        pass


def test_chat_is_wired_with_scan_settings_and_sessions(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = (
        '[llm]\nmodel = "m-1"\n\n[github]\nowner = "octo-org"\n\n[scan]\nwindow_days = 9\n\n'
        "[actions]\nmax_per_session = 3\n\n[fix]\nmax_prs_per_session = 2\n"
    )
    write_config(isolated_home, config)
    store_api_key(isolated_home)
    binary = GhBinary(path=isolated_home / "gh", version=(2, 102, 0))
    monkeypatch.setattr(ManagedGh, "find", lambda _: binary)

    with open_chat() as (chat, settings):
        assert chat.workspace.request.owner == "octo-org"
        assert chat.workspace.request.window_days == 9
        assert settings.actions.max_per_session == 3
        assert chat.handle("/sessions")[1].text == "No saved sessions yet."
        assert chat.handle("/actions")[1].text == "No actions requested in this session."
        assert not chat.confirmer(ActionRequest("Rerun?", ()))
        assert chat.mode is Mode.ASK
        assert chat.handle("/mode auto")[1].text.startswith("Mode: auto.")
        fixes = chat.workspace.fixes
        fixes.opened = 2
        target = FixTarget(e2e_finding(), e2e_evidence(), verdict(), "accepted: ok")
        with pytest.raises(ToolError, match="Pull request budget used up: 2 of 2"):
            fixes.prepare(target)
        chat.close()
        assert chat.handle("Hi")[1].text.startswith("Stopped at the request to stop.")
