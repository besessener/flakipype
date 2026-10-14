import json
import shutil
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx2
import keyring
import pytest
from keyring.backends import fail

from flakipype.agent.investigator import Status
from flakipype.agent.tools import ActionRequest, Mode, ToolError
from flakipype.cli import wiring
from flakipype.cli.wiring import (
    NotReadyError,
    build_daemon,
    build_setup_service,
    check_llm_endpoint,
    open_chat,
    open_investigation,
    open_run,
    open_scan,
    require_configuration,
    unit_options,
)
from flakipype.config.secrets import LLM_API_KEY, FileSecretStore
from flakipype.config.settings import SecretStoreChoice, Settings
from flakipype.fix.service import FixTarget
from flakipype.github.binary import GhBinary
from flakipype.github.provider import ManagedGh
from flakipype.investigate.service import InvestigationRequest, Selection
from flakipype.llm.client import LlmEndpoint
from flakipype.llm.connection import ConnectionFailed, ConnectionProblem
from flakipype.scan.service import ScanRequest, ScanService
from flakipype.setup.daemon import UnitOptions
from flakipype.store.database import ScanCache
from flakipype.store.lock import RunLockedError
from flakipype.unattended.service import RunService

from support.builders import START
from support.fake_anthropic import ScriptedModel, message, text
from support.fake_fix import verdict
from support.fake_gh import FakeGh
from support.fake_investigation import SCAN, world
from support.fake_runs import e2e_evidence, e2e_finding
from support.fake_setup import USER_CALL, logged_in


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


def use_fake_gh(home: Path, monkeypatch: pytest.MonkeyPatch, fake_gh: FakeGh) -> None:
    binary = GhBinary(path=home / "gh", version=(2, 102, 0))
    monkeypatch.setattr(ManagedGh, "find", lambda _: binary)
    monkeypatch.setattr(ManagedGh, "cli", lambda _, __, host: fake_gh.cli(host))


def test_a_run_holds_the_lock_and_is_wired_with_the_mode(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, fake_gh: FakeGh
) -> None:
    write_config(isolated_home, '[llm]\nmodel = "m-1"\n\n[github]\nowner = "octo-org"\n')
    store_api_key(isolated_home)
    use_fake_gh(isolated_home, monkeypatch, fake_gh)
    logged_in(fake_gh)
    requests: list[str] = []

    def request_for(settings: Settings) -> ScanRequest:
        requests.append(settings.github.owner)
        return ScanRequest("octo-org", "github.com", 30, 50)

    with open_run(Mode.ASK, request_for) as service:
        with pytest.raises(RunLockedError), open_run(Mode.AUTO, request_for):
            pass
        report = service.run()

    assert requests == ["octo-org"]
    assert report.mode is Mode.ASK
    assert (isolated_home / "data" / "flakipype" / "run.lock").exists()


def test_an_auto_run_is_wired_with_its_mode(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, fake_gh: FakeGh
) -> None:
    write_config(isolated_home, '[llm]\nmodel = "m-1"\n\n[github]\nowner = "octo-org"\n')
    store_api_key(isolated_home)
    use_fake_gh(isolated_home, monkeypatch, fake_gh)
    logged_in(fake_gh)

    with open_run(Mode.AUTO, lambda _: ScanRequest("octo-org", "github.com", 30, 50)) as service:
        report = service.run()

    assert report.mode is Mode.AUTO


@pytest.mark.parametrize(("configured", "asked"), [("octo-org", "other-org"), ("", "other-org")])
def test_a_run_only_takes_the_configured_owner(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, configured: str, asked: str
) -> None:
    write_config(isolated_home, f'[llm]\nmodel = "m-1"\n\n[github]\nowner = "{configured}"\n')
    store_api_key(isolated_home)
    binary = GhBinary(path=isolated_home / "gh", version=(2, 102, 0))
    monkeypatch.setattr(ManagedGh, "find", lambda _: binary)

    with (
        pytest.raises(
            NotReadyError, match=f"A run fixes only the configured owner .*, not {asked}"
        ),
        open_run(Mode.AUTO, lambda _: ScanRequest(asked, "github.com", 30, 50)),
    ):
        pass


def test_a_run_takes_the_configured_owner_in_any_case(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, fake_gh: FakeGh
) -> None:
    write_config(isolated_home, '[llm]\nmodel = "m-1"\n\n[github]\nowner = "octo-org"\n')
    store_api_key(isolated_home)
    use_fake_gh(isolated_home, monkeypatch, fake_gh)
    logged_in(fake_gh)

    with open_run(Mode.ASK, lambda _: ScanRequest("Octo-Org", "github.com", 30, 50)) as service:
        assert isinstance(service, RunService)


def test_a_run_without_a_gh_login_is_not_ready(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, fake_gh: FakeGh
) -> None:
    write_config(isolated_home, '[llm]\nmodel = "m-1"\n\n[github]\nowner = "octo-org"\n')
    store_api_key(isolated_home)
    use_fake_gh(isolated_home, monkeypatch, fake_gh)
    fake_gh.record(USER_CALL, stderr="gh auth login", exit_code=4)

    with (
        pytest.raises(NotReadyError, match=r"gh is not logged in to github\.com"),
        open_run(Mode.AUTO, lambda _: ScanRequest("octo-org", "github.com", 30, 50)),
    ):
        pass


def test_a_run_goes_on_when_the_login_cannot_be_checked(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, fake_gh: FakeGh
) -> None:
    write_config(isolated_home, '[llm]\nmodel = "m-1"\n\n[github]\nowner = "octo-org"\n')
    store_api_key(isolated_home)
    use_fake_gh(isolated_home, monkeypatch, fake_gh)
    fake_gh.record(USER_CALL, stderr="gh: Server Error (HTTP 502)", exit_code=1)

    with open_run(Mode.AUTO, lambda _: ScanRequest("octo-org", "github.com", 30, 50)) as service:
        assert isinstance(service, RunService)


def test_the_daemon_and_its_units_come_from_the_environment(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(isolated_home, "[run]\nmax_minutes = 30\n")
    command = isolated_home / "bin" / "flakipype"
    monkeypatch.setattr(sys, "argv", [str(command), "daemon", "install"])
    monkeypatch.setattr(shutil, "which", lambda _: str(command))

    options = unit_options("weekly", Mode.AUTO)

    assert options == UnitOptions(command, "weekly", "auto")
    assert build_daemon().unit_dir == isolated_home / "config" / "systemd" / "user"


def test_installing_units_needs_a_configuration(isolated_home: Path) -> None:
    with pytest.raises(NotReadyError, match=r"No configuration at .*config\.toml\. Run"):
        require_configuration()
    write_config(isolated_home, '[github]\nowner = "octo-org"\n')
    require_configuration()


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


# Obviously fake, long enough to be masked, and matching none of the masker's patterns.
API_KEY = "fake-foundry-key-for-tests"


def store_api_key(home: Path) -> None:
    FileSecretStore(home / "config" / "flakipype" / "secrets.json").put(LLM_API_KEY, API_KEY)


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


@dataclass
class ParallelModel(ScriptedModel):
    """Answers only once two requests are open at the same time."""

    both_open: threading.Barrier = field(default_factory=lambda: threading.Barrier(2, timeout=10))

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        response = super()._handle(request)
        self.both_open.wait()
        return response


def test_investigation_is_wired_with_agent_settings(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, cache: ScanCache
) -> None:
    config = (
        '[llm]\nmodel = "m-1"\n\n[github]\nowner = "octo-org"\n\n'
        "[agent]\nparallel = 2\nmax_tokens_per_run = 10_000\nmax_output_tokens = 2_000\n"
    )
    write_config(isolated_home, config)
    store_api_key(isolated_home)
    binary = GhBinary(path=isolated_home / "gh", version=(2, 102, 0))
    monkeypatch.setattr(ManagedGh, "find", lambda _: binary)
    no_verdict = message(
        text("No verdict yet."), usage={"input_tokens": 10_000, "output_tokens": 0}
    )
    model = ParallelModel([no_verdict, no_verdict])
    monkeypatch.setattr(wiring, "create_client", model.create_client)
    scan = ScanService(actions=world(), cache=cache, now=lambda: START.replace(day=9)).scan(SCAN)
    request = InvestigationRequest(SCAN, Selection(numbers=(1, 2, 3)))

    with open_investigation() as (service, _):
        report = service.investigate(scan, request)

    # 300 seconds per investigation (shorter than a fix), shared with two SDK retries.
    assert model.created == [(LlmEndpoint("https://api.anthropic.com", API_KEY, "m-1"), 100.0)]
    # Two investigations in parallel use up the run's tokens before the third starts.
    assert [(r.status, r.tokens) for r in report.results] == [
        (Status.BUDGET, 10_000), (Status.BUDGET, 10_000), (Status.BUDGET, 0),
    ]  # fmt: skip
    assert report.tokens == 20_000
    assert [(r["model"], r["max_tokens"]) for r in model.requests] == [("m-1", 2_000)] * 2


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
        "[actions]\nmax_per_session = 3\n\n[fix]\nmax_prs_per_session = 2\n\n"
        "[agent]\nmax_output_tokens = 2_000\n"
    )
    write_config(isolated_home, config)
    store_api_key(isolated_home)
    binary = GhBinary(path=isolated_home / "gh", version=(2, 102, 0))
    monkeypatch.setattr(ManagedGh, "find", lambda _: binary)
    model = ScriptedModel([message(text("Noted."))])
    monkeypatch.setattr(wiring, "create_client", model.create_client)

    with open_chat() as (chat, _):
        assert chat.workspace.request.owner == "octo-org"
        assert chat.workspace.request.window_days == 9
        assert chat.workspace.actions.max_per_session == 3
        assert chat.handle("/sessions")[1].text == "No saved sessions yet."
        assert chat.handle("/actions")[1].text == "No actions requested in this session."
        assert chat.handle(f"Is {API_KEY} still valid?")[1].text == "Noted."
        (sent,) = model.requests
        assert sent["max_tokens"] == 2_000
        assert API_KEY not in json.dumps(sent)
        assert "Is [masked: configured secret] still valid?" in json.dumps(sent)
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
