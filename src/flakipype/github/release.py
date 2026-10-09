"""Pure logic for gh releases: asset names, checksums and versions."""

import re
from dataclasses import dataclass

type GhVersion = tuple[int, int, int]

MINIMUM_GH_VERSION: GhVersion = (2, 40, 0)
RELEASE_DOWNLOAD_BASE = "https://github.com/cli/cli/releases/download"
# A web URL, not api.github.com: it redirects to the newest tag and has no API rate limit.
LATEST_RELEASE_URL = "https://github.com/cli/cli/releases/latest"
_TAG_PAGE_PREFIX = "https://github.com/cli/cli/releases/tag/"

_ARCHITECTURES = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv7l": "armv6",
    "armv6l": "armv6",
    "i386": "386",
    "i686": "386",
}
_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_VERSION_OUTPUT = re.compile(r"^gh version (\d+)\.(\d+)\.(\d+)\b", re.MULTILINE)


class UnsupportedPlatformError(Exception):
    """gh publishes no Linux build for this machine."""


class ChecksumMissingError(Exception):
    """The release checksum file does not list the expected asset."""


@dataclass(frozen=True)
class GhRelease:
    version: GhVersion

    @property
    def version_text(self) -> str:
        return format_version(self.version)

    def tarball_name(self, architecture: str) -> str:
        return f"gh_{self.version_text}_linux_{architecture}.tar.gz"

    @property
    def checksums_name(self) -> str:
        return f"gh_{self.version_text}_checksums.txt"

    def download_url(self, asset_name: str) -> str:
        return f"{RELEASE_DOWNLOAD_BASE}/v{self.version_text}/{asset_name}"

    def binary_member(self, architecture: str) -> str:
        return f"gh_{self.version_text}_linux_{architecture}/bin/gh"


def linux_architecture(machine: str) -> str:
    architecture = _ARCHITECTURES.get(machine.lower())
    if architecture is None:
        message = f"gh has no Linux build for the machine type {machine!r}"
        raise UnsupportedPlatformError(message)
    return architecture


def release_from_tag(tag: str) -> GhRelease:
    match = _TAG.match(tag)
    if match is None:
        message = f"unexpected gh release tag {tag!r}"
        raise ValueError(message)
    major, minor, patch = (int(part) for part in match.groups())
    return GhRelease(version=(major, minor, patch))


def release_from_redirect(location: str) -> GhRelease:
    """Read the release from where LATEST_RELEASE_URL redirects to."""
    if not location.startswith(_TAG_PAGE_PREFIX):
        message = f"unexpected redirect for the latest gh release: {location!r}"
        raise ValueError(message)
    return release_from_tag(location.removeprefix(_TAG_PAGE_PREFIX))


def expected_sha256(checksums: str, asset_name: str) -> str:
    for line in checksums.splitlines():
        digest, _, name = line.strip().partition("  ")
        if name == asset_name and re.fullmatch(r"[0-9a-f]{64}", digest):
            return digest
    message = f"{asset_name} is not listed in the release checksums"
    raise ChecksumMissingError(message)


def parse_gh_version(output: str) -> GhVersion | None:
    match = _VERSION_OUTPUT.search(output)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return (major, minor, patch)


def format_version(version: GhVersion) -> str:
    return ".".join(str(part) for part in version)
