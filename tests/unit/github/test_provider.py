from pathlib import Path

import httpx2
import pytest

from flakipype.github.binary import GhBinary, GhInstaller, GhInstallError
from flakipype.github.provider import ManagedGh


def offline_installer(bin_dir: Path) -> GhInstaller:
    transport = httpx2.MockTransport(lambda _: httpx2.Response(503))
    return GhInstaller(httpx2.Client(transport=transport), bin_dir)


def test_nothing_found_without_candidates(tmp_path: Path) -> None:
    managed = ManagedGh(offline_installer(tmp_path), on_path=None, machine="x86_64")

    assert managed.find() is None


def test_unsupported_machine_is_an_install_error(tmp_path: Path) -> None:
    managed = ManagedGh(offline_installer(tmp_path), on_path=None, machine="riscv64")

    with pytest.raises(GhInstallError, match="riscv64"):
        managed.install()


def test_cli_runs_the_found_binary_against_the_host(tmp_path: Path) -> None:
    managed = ManagedGh(offline_installer(tmp_path), on_path=None, machine="x86_64")

    gh = managed.cli(GhBinary(path=tmp_path / "gh", version=(2, 102, 0)), "github.example.com")

    assert gh.host == "github.example.com"


def test_install_goes_through_the_installer(tmp_path: Path) -> None:
    managed = ManagedGh(offline_installer(tmp_path), on_path=tmp_path / "gh", machine="aarch64")

    with pytest.raises(GhInstallError, match="Downloading gh failed"):
        managed.install()
    assert managed.find() is None
