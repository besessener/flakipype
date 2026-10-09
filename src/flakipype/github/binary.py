"""Find a usable gh, or download one and verify it before first use."""

import hashlib
import io
import subprocess
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx2

from flakipype.github.release import (
    MINIMUM_GH_VERSION,
    ChecksumMissingError,
    GhRelease,
    GhVersion,
    expected_sha256,
    parse_gh_version,
    release_from_tag,
)

LATEST_RELEASE_API = "https://api.github.com/repos/cli/cli/releases/latest"
_VERSION_TIMEOUT_SECONDS = 10


class GhInstallError(Exception):
    """gh could not be downloaded or installed; nothing was installed."""


class ChecksumMismatchError(GhInstallError):
    """The downloaded archive does not match the published SHA-256."""


@dataclass(frozen=True)
class GhBinary:
    path: Path
    version: GhVersion


def read_gh_version(path: Path) -> GhVersion | None:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed arguments, path comes from PATH lookup or our own install
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT_SECONDS,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_gh_version(completed.stdout)


def locate_gh(
    candidates: list[Path],
    version_of: Callable[[Path], GhVersion | None] = read_gh_version,
) -> GhBinary | None:
    """Return the first candidate that runs and is recent enough."""
    for candidate in candidates:
        version = version_of(candidate)
        if version is not None and version >= MINIMUM_GH_VERSION:
            return GhBinary(path=candidate, version=version)
    return None


class GhInstaller:
    def __init__(self, http: httpx2.Client, bin_dir: Path) -> None:
        self._http = http
        self._bin_dir = bin_dir

    @property
    def target(self) -> Path:
        return self._bin_dir / "gh"

    def install(self, architecture: str) -> GhBinary:
        try:
            release = self._latest_release()
            tarball_name = release.tarball_name(architecture)
            checksums = self._get(release.download_url(release.checksums_name)).text
            expected = expected_sha256(checksums, tarball_name)
            archive = self._get(release.download_url(tarball_name)).content
        except (httpx2.HTTPError, ChecksumMissingError, ValueError, KeyError) as error:
            message = f"Downloading gh failed: {error}"
            raise GhInstallError(message) from error
        actual = hashlib.sha256(archive).hexdigest()
        if actual != expected:
            message = f"Checksum mismatch for {tarball_name}: expected {expected}, got {actual}"
            raise ChecksumMismatchError(message)
        self._write_binary(archive, release.binary_member(architecture))
        return GhBinary(path=self.target, version=release.version)

    def _latest_release(self) -> GhRelease:
        payload = self._get(LATEST_RELEASE_API).json()
        return release_from_tag(str(payload["tag_name"]))

    def _get(self, url: str) -> httpx2.Response:
        response = self._http.get(url)
        response.raise_for_status()
        return response

    def _write_binary(self, archive: bytes, member_name: str) -> None:
        try:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
                member = tar.extractfile(member_name)
                if member is None:
                    message = f"{member_name} in the archive is not a file"
                    raise GhInstallError(message)
                content = member.read()
        except (tarfile.TarError, KeyError) as error:
            message = f"The gh archive is unusable: {error}"
            raise GhInstallError(message) from error
        self._bin_dir.mkdir(parents=True, exist_ok=True)
        partial = self._bin_dir / ".gh.partial"
        partial.write_bytes(content)
        partial.chmod(0o755)
        # Atomic rename: a crash never leaves a half-written gh behind.
        partial.replace(self.target)
