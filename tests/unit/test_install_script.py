import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]


def assignment(name: str) -> str:
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    found = re.search(rf'^{name}="([^"]+)"$', text, flags=re.MULTILINE)
    assert found, f"{name} is not set in install.sh"
    return found.group(1)


def test_the_install_script_installs_this_version() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert assignment("FLAKIPYPE_VERSION") == "v" + project["project"]["version"]


def test_the_install_script_pins_uv() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", assignment("UV_VERSION"))
