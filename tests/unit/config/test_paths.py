from pathlib import Path

from flakipype.config.paths import app_paths


def test_defaults_follow_the_xdg_fallbacks_under_home(tmp_path: Path) -> None:
    paths = app_paths({}, home=tmp_path)

    assert paths.config_dir == tmp_path / ".config" / "flakipype"
    assert paths.data_dir == tmp_path / ".local" / "share" / "flakipype"
    assert paths.config_file == paths.config_dir / "config.toml"
    assert paths.secrets_file == paths.config_dir / "secrets.json"
    assert paths.bin_dir == paths.data_dir / "bin"


def test_absolute_xdg_variables_take_precedence(tmp_path: Path) -> None:
    environment = {
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }

    paths = app_paths(environment, home=tmp_path / "home")

    assert paths.config_dir == tmp_path / "cfg" / "flakipype"
    assert paths.data_dir == tmp_path / "data" / "flakipype"


def test_relative_xdg_variables_are_ignored(tmp_path: Path) -> None:
    paths = app_paths({"XDG_CONFIG_HOME": "relative/dir"}, home=tmp_path)

    assert paths.config_dir == tmp_path / ".config" / "flakipype"
