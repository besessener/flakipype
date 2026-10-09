import hashlib
import io
import sys
import tarfile
from pathlib import Path

import httpx2
import pytest

from flakipype.github.binary import (
    ChecksumMismatchError,
    GhBinary,
    GhInstaller,
    GhInstallError,
    RateLimitedError,
    locate_gh,
    read_gh_version,
)
from flakipype.github.release import LATEST_RELEASE_URL

FAKE_BINARY = b"#!/bin/sh\necho 'gh version 2.102.0 (2026-09-30)'\n"
DOWNLOADS = "https://github.com/cli/cli/releases/download/v2.102.0"


def tarball(member: str = "gh_2.102.0_linux_amd64/bin/gh", content: bytes = FAKE_BINARY) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo(member)
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def release_server(archive: bytes, digest: str | None = None) -> dict[str, httpx2.Response]:
    checksum = digest or hashlib.sha256(archive).hexdigest()
    checksums = (
        f"{'0' * 64}  gh_2.102.0_linux_arm64.tar.gz\n{checksum}  gh_2.102.0_linux_amd64.tar.gz\n"
    )
    return {
        LATEST_RELEASE_URL: httpx2.Response(
            302, headers={"location": "https://github.com/cli/cli/releases/tag/v2.102.0"}
        ),
        f"{DOWNLOADS}/gh_2.102.0_checksums.txt": httpx2.Response(200, text=checksums),
        f"{DOWNLOADS}/gh_2.102.0_linux_amd64.tar.gz": httpx2.Response(200, content=archive),
    }


def installer(routes: dict[str, httpx2.Response], bin_dir: Path) -> GhInstaller:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return routes.get(str(request.url), httpx2.Response(404))

    return GhInstaller(httpx2.Client(transport=httpx2.MockTransport(handler)), bin_dir)


def test_install_verifies_and_writes_the_binary(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"

    installed = installer(release_server(tarball()), bin_dir).install("amd64")

    assert installed == GhBinary(path=bin_dir / "gh", version=(2, 102, 0))
    assert installed.path.read_bytes() == FAKE_BINARY
    assert list(bin_dir.iterdir()) == [bin_dir / "gh"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes do not exist on Windows")
def test_installed_binary_is_executable(tmp_path: Path) -> None:
    installed = installer(release_server(tarball()), tmp_path).install("amd64")

    assert installed.path.stat().st_mode & 0o111


def test_checksum_mismatch_installs_nothing(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    routes = release_server(tarball(), digest="f" * 64)

    with pytest.raises(ChecksumMismatchError, match="expected f"):
        installer(routes, bin_dir).install("amd64")

    assert not bin_dir.exists()


def test_architecture_missing_from_checksums_installs_nothing(tmp_path: Path) -> None:
    with pytest.raises(GhInstallError, match="not listed"):
        installer(release_server(tarball()), tmp_path).install("armv6")


def test_latest_release_is_resolved_without_the_rate_limited_api(tmp_path: Path) -> None:
    requested: list[str] = []
    routes = release_server(tarball())

    def handler(request: httpx2.Request) -> httpx2.Response:
        requested.append(str(request.url))
        return routes.get(str(request.url), httpx2.Response(404))

    client = httpx2.Client(transport=httpx2.MockTransport(handler), follow_redirects=True)
    GhInstaller(client, tmp_path).install("amd64")

    assert requested[0] == LATEST_RELEASE_URL
    assert not any("api.github.com" in url for url in requested)


def test_network_errors_become_install_errors(tmp_path: Path) -> None:
    routes = release_server(tarball())
    routes[LATEST_RELEASE_URL] = httpx2.Response(503)

    with pytest.raises(GhInstallError, match="Downloading gh failed"):
        installer(routes, tmp_path).install("amd64")


@pytest.mark.parametrize("status", [403, 429])
def test_rate_limit_explains_what_to_do(tmp_path: Path, status: int) -> None:
    routes = release_server(tarball())
    routes[f"{DOWNLOADS}/gh_2.102.0_checksums.txt"] = httpx2.Response(status)

    with pytest.raises(RateLimitedError, match="rate limit") as error:
        installer(routes, tmp_path).install("amd64")

    assert "https://cli.github.com" in str(error.value)
    assert not (tmp_path / "gh").exists()


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, text="<html>release page</html>"),
        httpx2.Response(302, headers={"location": "https://github.com/login"}),
        httpx2.Response(302),
    ],
)
def test_unexpected_latest_release_answer_is_an_install_error(
    tmp_path: Path, response: httpx2.Response
) -> None:
    routes = release_server(tarball())
    routes[LATEST_RELEASE_URL] = response

    with pytest.raises(GhInstallError, match="Downloading gh failed"):
        installer(routes, tmp_path).install("amd64")


@pytest.mark.parametrize(
    ("archive", "reason"),
    [
        (tarball(member="somewhere/else/gh"), "unusable"),
        (b"not a tarball", "unusable"),
    ],
)
def test_broken_archive_is_an_install_error(tmp_path: Path, archive: bytes, reason: str) -> None:
    with pytest.raises(GhInstallError, match=reason):
        installer(release_server(archive), tmp_path).install("amd64")


def test_directory_member_is_an_install_error(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("gh_2.102.0_linux_amd64/bin/gh")
        info.type = tarfile.DIRTYPE
        tar.addfile(info)

    with pytest.raises(GhInstallError, match="not a file"):
        installer(release_server(buffer.getvalue()), tmp_path).install("amd64")


def test_locate_returns_the_first_recent_enough_candidate() -> None:
    versions = {Path("/old/gh"): (2, 30, 0), Path("/broken/gh"): None, Path("/new/gh"): (2, 102, 0)}

    found = locate_gh(list(versions), version_of=versions.__getitem__)

    assert found == GhBinary(path=Path("/new/gh"), version=(2, 102, 0))


def test_locate_without_usable_candidate() -> None:
    assert locate_gh([Path("/old/gh")], version_of=lambda _: (2, 0, 0)) is None
    assert locate_gh([]) is None


def test_read_version_of_something_that_is_not_gh(tmp_path: Path) -> None:
    assert read_gh_version(Path(sys.executable)) is None
    assert read_gh_version(tmp_path / "missing") is None
