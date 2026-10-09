from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from keyring.backends import fail

from flakipype.cli.wiring import (
    NotReadyError,
    build_setup_service,
    check_llm_endpoint,
    open_investigation,
    open_scan,
)
from flakipype.config.secrets import LLM_API_KEY, FileSecretStore
from flakipype.github.binary import GhBinary
from flakipype.github.provider import ManagedGh
from flakipype.llm.client import LlmEndpoint
from flakipype.llm.connection import ConnectionFailed, ConnectionProblem


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())  # type: ignore[no-untyped-call]  # keyring's __init__ is unannotated
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


def test_llm_check_against_a_closed_local_port() -> None:
    endpoint = LlmEndpoint(base_url="http://127.0.0.1:9", api_key="unused", model="m-1")

    result = check_llm_endpoint(endpoint)

    assert isinstance(result, ConnectionFailed)
    assert result.problem is ConnectionProblem.UNREACHABLE


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
