from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "flakipype"


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def secrets_file(self) -> Path:
        return self.config_dir / "secrets.json"

    @property
    def bin_dir(self) -> Path:
        return self.data_dir / "bin"

    @property
    def cache_file(self) -> Path:
        return self.data_dir / "cache.sqlite3"


def _xdg_base(environment: Mapping[str, str], variable: str, fallback: Path) -> Path:
    # The XDG spec says relative values are invalid and must be ignored.
    value = environment.get(variable, "")
    if value and Path(value).is_absolute():
        return Path(value)
    return fallback


def app_paths(environment: Mapping[str, str], home: Path) -> AppPaths:
    config_home = _xdg_base(environment, "XDG_CONFIG_HOME", home / ".config")
    data_home = _xdg_base(environment, "XDG_DATA_HOME", home / ".local" / "share")
    return AppPaths(config_dir=config_home / APP_NAME, data_dir=data_home / APP_NAME)
