import re
import tomllib
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

import tomli_w
from pydantic import AfterValidator, BaseModel, ConfigDict, ValidationError

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


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    llm: LlmSettings = LlmSettings()
    github: GitHubSettings = GitHubSettings()


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
