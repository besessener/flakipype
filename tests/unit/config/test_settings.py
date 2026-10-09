from pathlib import Path

import pytest
from pydantic import ValidationError

from flakipype.config.settings import (
    GitHubSettings,
    LlmSettings,
    Settings,
    SettingsError,
    load_settings,
    save_settings,
)


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "config.toml")

    assert settings.llm.base_url == "https://api.anthropic.com"
    assert settings.github.host == "github.com"
    assert settings.llm.model == ""
    assert settings.github.owner == ""


def test_saved_settings_load_back_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "config.toml"
    settings = Settings(
        llm=LlmSettings(base_url="https://example.services.ai.azure.com/anthropic", model="m"),
        github=GitHubSettings(host="github.example.com", owner="acme"),
    )

    save_settings(settings, path)

    assert load_settings(path) == settings


def test_scan_settings_have_safe_defaults_and_limits(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[scan]\nmax_log_downloads = 0\n", encoding="utf-8")

    assert Settings().scan.window_days == 30
    assert Settings().scan.max_log_downloads == 50
    assert load_settings(path).scan.max_log_downloads == 0
    for content in ("[scan]\nwindow_days = 0\n", "[scan]\nmax_log_downloads = 5000\n"):
        path.write_text(content, encoding="utf-8")
        with pytest.raises(SettingsError):
            load_settings(path)


def test_invalid_toml_is_a_settings_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("this is = = not toml", encoding="utf-8")

    with pytest.raises(SettingsError, match="Cannot read"):
        load_settings(path)


def test_unknown_keys_are_a_settings_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[llm]\nbase_url = "https://api.anthropic.com"\napi_key = "x"\n')

    with pytest.raises(SettingsError, match="api_key"):
        load_settings(path)


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("https://api.anthropic.com/", "https://api.anthropic.com"),
        (" https://proxy.example.com/anthropic ", "https://proxy.example.com/anthropic"),
        ("http://localhost:8080", "http://localhost:8080"),
        ("http://127.0.0.1:9000/v1", "http://127.0.0.1:9000/v1"),
    ],
)
def test_accepted_base_urls_are_normalised(given: str, stored: str) -> None:
    assert LlmSettings(base_url=given).base_url == stored


@pytest.mark.parametrize(
    ("given", "reason"),
    [
        ("http://api.anthropic.com", "must use https"),
        ("ftp://api.anthropic.com", "must use https"),
        ("api.anthropic.com", "must be a URL"),
        ("", "must be a URL"),
    ],
)
def test_rejected_base_urls_say_why(given: str, reason: str) -> None:
    with pytest.raises(ValidationError, match=reason):
        LlmSettings(base_url=given)


def test_github_host_is_normalised_and_rejects_urls() -> None:
    assert GitHubSettings(host=" GitHub.Example.com ").host == "github.example.com"
    with pytest.raises(ValidationError, match="without https://"):
        GitHubSettings(host="https://github.com")


@pytest.mark.parametrize("owner", ["acme", "Acme-Corp", "a1", ""])
def test_valid_owners(owner: str) -> None:
    assert GitHubSettings(owner=owner).owner == owner


@pytest.mark.parametrize("owner", ["-acme", "acme/repo", "a" * 40, "with space"])
def test_invalid_owners(owner: str) -> None:
    with pytest.raises(ValidationError, match="user or organisation"):
        GitHubSettings(owner=owner)
