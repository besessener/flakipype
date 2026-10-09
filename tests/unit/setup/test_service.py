from dataclasses import replace
from pathlib import Path

import pytest

from flakipype.config.secrets import LLM_API_KEY
from flakipype.config.settings import load_settings
from flakipype.github.auth import AuthCheckFailed, Authenticated
from flakipype.github.binary import GhInstallError
from flakipype.llm.client import LlmEndpoint
from flakipype.setup.service import GhMissingError, InvalidSetupError

from support.fake_gh import FakeGh
from support.fake_setup import INSTALLED_GH, complete_draft, logged_in, setup_world


def test_fresh_machine_loads_defaults_without_key(tmp_path: Path, fake_gh: FakeGh) -> None:
    state = setup_world(tmp_path, fake_gh).service.load()

    assert state.settings.llm.base_url == "https://api.anthropic.com"
    assert not state.has_api_key
    assert state.problem == ""


def test_broken_config_file_is_reported_not_fatal(tmp_path: Path, fake_gh: FakeGh) -> None:
    world = setup_world(tmp_path, fake_gh)
    world.paths.config_dir.mkdir(parents=True)
    world.paths.config_file.write_text("broken = = toml", encoding="utf-8")

    state = world.service.load()

    assert "Cannot read" in state.problem
    assert state.settings.github.host == "github.com"


def test_save_writes_settings_and_keeps_the_key_out_of_the_file(
    tmp_path: Path, fake_gh: FakeGh
) -> None:
    world = setup_world(tmp_path, fake_gh)

    world.service.save(complete_draft(api_key="key-1"))

    assert load_settings(world.paths.config_file).github.owner == "octo-org"
    assert "key-1" not in world.paths.config_file.read_text(encoding="utf-8")
    assert world.secrets.get(LLM_API_KEY) == "key-1"
    assert world.service.load().has_api_key


def test_save_keeps_existing_scan_settings(tmp_path: Path, fake_gh: FakeGh) -> None:
    world = setup_world(tmp_path, fake_gh)
    world.paths.config_dir.mkdir(parents=True)
    world.paths.config_file.write_text("[scan]\nwindow_days = 7\n", encoding="utf-8")

    world.service.save(complete_draft())

    assert load_settings(world.paths.config_file).scan.window_days == 7


def test_empty_key_keeps_the_stored_key(tmp_path: Path, fake_gh: FakeGh) -> None:
    world = setup_world(tmp_path, fake_gh)
    world.secrets.put(LLM_API_KEY, "stored-key")

    world.service.save(complete_draft(api_key=""))

    assert world.secrets.get(LLM_API_KEY) == "stored-key"


def test_every_problem_is_reported_at_once(tmp_path: Path, fake_gh: FakeGh) -> None:
    draft = replace(
        complete_draft(api_key=""), base_url="http://remote.example", model=" ", owner=""
    )

    with pytest.raises(InvalidSetupError) as error:
        setup_world(tmp_path, fake_gh).service.save(draft)

    assert error.value.errors == {
        "llm.base_url": "must use https (plain http is only allowed for localhost)",
        "llm.model": "is required",
        "llm.api_key": "is required",
        "github.owner": "is required",
    }


def test_invalid_github_host_is_reported(tmp_path: Path, fake_gh: FakeGh) -> None:
    draft = replace(complete_draft(), host="https://github.com")

    with pytest.raises(InvalidSetupError, match=r"github\.host"):
        setup_world(tmp_path, fake_gh).service.settings_from(draft)


def test_llm_check_needs_only_the_model_part(tmp_path: Path, fake_gh: FakeGh) -> None:
    world = setup_world(tmp_path, fake_gh)
    world.secrets.put(LLM_API_KEY, "stored-key")
    draft = replace(complete_draft(api_key=""), owner="")

    world.service.check_llm(draft)

    assert world.llm.endpoints == [LlmEndpoint("https://api.anthropic.com", "stored-key", "m-1")]


def test_install_keeps_an_existing_gh(tmp_path: Path, fake_gh: FakeGh) -> None:
    world = setup_world(tmp_path, fake_gh)

    assert world.service.install_gh() == INSTALLED_GH
    assert world.gh.install_count == 0


def test_install_downloads_when_missing(tmp_path: Path, fake_gh: FakeGh) -> None:
    world = setup_world(tmp_path, fake_gh)
    world.gh.installed = None

    assert world.service.install_gh() == INSTALLED_GH
    assert world.gh.install_count == 1


def test_install_errors_propagate(tmp_path: Path, fake_gh: FakeGh) -> None:
    world = setup_world(tmp_path, fake_gh)
    world.gh.installed = None
    world.gh.install_error = "checksum mismatch"

    with pytest.raises(GhInstallError, match="checksum mismatch"):
        world.service.install_gh()


def test_github_auth_through_gh(tmp_path: Path, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)

    status = setup_world(tmp_path, fake_gh).service.github_auth("github.com")

    assert isinstance(status, Authenticated)
    assert status.login == "octocat"


def test_without_gh_auth_and_login_explain_what_is_missing(tmp_path: Path, fake_gh: FakeGh) -> None:
    world = setup_world(tmp_path, fake_gh)
    world.gh.installed = None

    assert world.service.github_auth("github.com") == AuthCheckFailed("gh is not installed yet.")
    with pytest.raises(GhMissingError):
        world.service.login_with_token("github.com", "token")
    with pytest.raises(GhMissingError):
        world.service.browser_login("github.com")


def test_token_and_browser_login_run_gh(tmp_path: Path, fake_gh: FakeGh) -> None:
    world = setup_world(tmp_path, fake_gh)
    token_login = ["auth", "login", "--hostname", "github.com", "--with-token"]
    fake_gh.record(token_login)
    browser_login = [
        "auth", "login", "--hostname", "github.com", "--web",
        "--git-protocol", "https", "--scopes", "read:org,repo,workflow",
    ]  # fmt: skip
    fake_gh.record(browser_login)

    world.service.login_with_token("github.com", "token-1")
    exit_code = world.service.browser_login("github.com")

    assert exit_code == 0
    assert [call["args"] for call in fake_gh.invocations()] == [token_login, browser_login]
    assert world.service.secret_location.startswith("file ")
