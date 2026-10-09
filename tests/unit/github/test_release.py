import pytest

from flakipype.github.release import (
    ChecksumMissingError,
    GhRelease,
    UnsupportedPlatformError,
    expected_sha256,
    format_version,
    linux_architecture,
    parse_gh_version,
    release_from_tag,
)

DIGEST = "a" * 64


@pytest.mark.parametrize(
    ("machine", "architecture"),
    [
        ("x86_64", "amd64"),
        ("AMD64", "amd64"),
        ("aarch64", "arm64"),
        ("arm64", "arm64"),
        ("armv7l", "armv6"),
        ("armv6l", "armv6"),
        ("i686", "386"),
    ],
)
def test_machine_types_map_to_gh_architectures(machine: str, architecture: str) -> None:
    assert linux_architecture(machine) == architecture


def test_unknown_machine_type_is_unsupported() -> None:
    with pytest.raises(UnsupportedPlatformError, match="riscv64"):
        linux_architecture("riscv64")


def test_release_asset_names_and_urls() -> None:
    release = release_from_tag("v2.102.0")

    assert release == GhRelease(version=(2, 102, 0))
    assert release.tarball_name("arm64") == "gh_2.102.0_linux_arm64.tar.gz"
    assert release.checksums_name == "gh_2.102.0_checksums.txt"
    assert release.binary_member("amd64") == "gh_2.102.0_linux_amd64/bin/gh"
    assert release.download_url("x.tar.gz") == (
        "https://github.com/cli/cli/releases/download/v2.102.0/x.tar.gz"
    )


@pytest.mark.parametrize("tag", ["2.102.0", "v2.102", "v2.102.0-rc1", ""])
def test_unexpected_tags_are_rejected(tag: str) -> None:
    with pytest.raises(ValueError, match="unexpected gh release tag"):
        release_from_tag(tag)


def test_expected_sha256_finds_the_asset_line() -> None:
    checksums = f"{'b' * 64}  gh_2.1.0_linux_386.tar.gz\n{DIGEST}  gh_2.1.0_linux_amd64.tar.gz\n"

    assert expected_sha256(checksums, "gh_2.1.0_linux_amd64.tar.gz") == DIGEST


@pytest.mark.parametrize(
    "checksums",
    [
        "",
        f"{DIGEST}  gh_2.1.0_linux_arm64.tar.gz\n",
        "not-a-digest  gh_2.1.0_linux_amd64.tar.gz\n",
    ],
)
def test_missing_or_malformed_checksum_is_an_error(checksums: str) -> None:
    with pytest.raises(ChecksumMissingError, match="not listed"):
        expected_sha256(checksums, "gh_2.1.0_linux_amd64.tar.gz")


def test_gh_version_output_is_parsed() -> None:
    output = "gh version 2.102.0 (2026-09-30)\nhttps://github.com/cli/cli/releases/tag/v2.102.0\n"

    assert parse_gh_version(output) == (2, 102, 0)
    assert parse_gh_version("Python 3.12.15") is None
    assert format_version((2, 40, 0)) == "2.40.0"
