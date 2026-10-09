import re
import tomllib
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import tomli_w
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_GITHUB_HOST = "github.com"

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_GITHUB_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_HOSTNAME = re.compile(r"^[A-Za-z0-9.-]+(?::\d{1,5})?$")


class SettingsError(Exception):
    """The configuration file exists but cannot be read or is invalid."""


def validate_base_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if not parts.hostname:
        message = "must be a URL like https://api.anthropic.com"
        raise ValueError(message)
    if parts.scheme == "https":
        return value.strip().rstrip("/")
    if parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS:
        return value.strip().rstrip("/")
    message = "must use https (plain http is only allowed for localhost)"
    raise ValueError(message)


def validate_github_host(value: str) -> str:
    host = value.strip().lower()
    if not _HOSTNAME.match(host):
        message = "must be a host name like github.com or github.example.com, without https://"
        raise ValueError(message)
    return host


def validate_owner(value: str) -> str:
    owner = value.strip()
    if owner and not _GITHUB_LOGIN.match(owner):
        message = "must be a GitHub user or organisation name"
        raise ValueError(message)
    return owner


class LlmSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: Annotated[str, AfterValidator(validate_base_url)] = DEFAULT_BASE_URL
    model: str = ""


class GitHubSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: Annotated[str, AfterValidator(validate_github_host)] = DEFAULT_GITHUB_HOST
    owner: Annotated[str, AfterValidator(validate_owner)] = ""


class ScanSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # GitHub keeps run history for 400 days; logs usually for 90.
    window_days: int = Field(default=30, ge=1, le=400)
    # Hard limit per scan; log downloads are the slow, heavy part.
    max_log_downloads: int = Field(default=50, ge=0, le=1000)
    # One failure that passed on rerun can be an outage; flaky means it keeps happening.
    min_flaky_runs: int = Field(default=2, ge=1, le=100)


class AgentSettings(BaseModel):
    """Hard limits for investigations; reaching one ends the work with a summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_rounds: int = Field(default=12, ge=1, le=50)
    max_tokens_per_investigation: int = Field(default=200_000, ge=10_000, le=2_000_000)
    max_seconds_per_investigation: int = Field(default=300, ge=30, le=3_600)
    max_tokens_per_run: int = Field(default=1_000_000, ge=10_000, le=20_000_000)
    parallel: int = Field(default=3, ge=1, le=8)
    max_output_tokens: int = Field(default=16_000, ge=1_000, le=64_000)
    thinking: Literal["adaptive", "enabled", "off"] = "adaptive"
    thinking_budget: int = Field(default=8_000, ge=1_024, le=60_000)
    excerpt_lines: int = Field(default=120, ge=20, le=400)


class ActionSettings(BaseModel):
    """Hard limits for reruns and dispatches started from the chat."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_per_session: int = Field(default=10, ge=1, le=100)
    max_watched: int = Field(default=10, ge=1, le=50)
    watch_hours: int = Field(default=6, ge=1, le=24)


class FixSettings(BaseModel):
    """Hard limits for fixes: pull requests, diff size, verification and the fixer agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_prs_per_session: int = Field(default=3, ge=1, le=20)
    max_files: int = Field(default=10, ge=1, le=50)
    max_changed_lines: int = Field(default=400, ge=10, le=2_000)
    verify_runs: int = Field(default=3, ge=1, le=10)
    max_rounds: int = Field(default=20, ge=5, le=60)
    max_tokens: int = Field(default=300_000, ge=10_000, le=2_000_000)
    max_seconds: int = Field(default=600, ge=60, le=3_600)


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    llm: LlmSettings = LlmSettings()
    github: GitHubSettings = GitHubSettings()
    scan: ScanSettings = ScanSettings()
    agent: AgentSettings = AgentSettings()
    actions: ActionSettings = ActionSettings()
    fix: FixSettings = FixSettings()


def load_settings(path: Path) -> Settings:
    if not path.exists():
        return Settings()
    try:
        return Settings.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    except (tomllib.TOMLDecodeError, ValidationError, OSError) as error:
        message = f"Cannot read {path}: {error}"
        raise SettingsError(message) from error


def save_settings(settings: Settings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(settings.model_dump()), encoding="utf-8")
