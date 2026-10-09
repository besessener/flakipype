from pathlib import Path

import pytest

from flakipype.flaky.signature import (
    Category,
    categorise,
    clean_text,
    error_entries,
    log_entries,
    normalise,
    signature_from_log,
)

LOGS = Path(__file__).parents[2] / "fixtures" / "logs"
STAMP = "2026-10-07T09:27:35.3592891Z "


def recorded_log(name: str) -> str:
    return (LOGS / name).read_text(encoding="utf-8")


def test_recorded_playwright_failure() -> None:
    signature = signature_from_log(recorded_log("playwright-timeout.log"))

    assert signature is not None
    assert signature.category is Category.TIMEOUT
    assert signature.message == (
        'tests/e2e/scan.spec.ts:N:N > analysing selected files in the privacy mode ,automatisch" '
        "> archives a project group with each document keeping its own topic"
        " · Error: expect(locator).toHaveCount(expected) failed"
        " · Locator: getByTestId('document-row')"
    )
    assert (
        signature.excerpt.splitlines()[1] == "Error: expect(locator).toHaveCount(expected) failed"
    )
    assert "Timeout:  20000ms" in signature.excerpt
    assert len(signature.fingerprint) == 12


def test_same_failure_on_another_day_and_line_has_the_same_fingerprint() -> None:
    original = recorded_log("playwright-timeout.log")
    later = original.replace("2026-10-07", "2026-10-09").replace("spec.ts:77:7", "spec.ts:81:7")

    first, second = signature_from_log(original), signature_from_log(later)

    assert first is not None
    assert second is not None
    assert first.fingerprint == second.fingerprint


def test_recorded_npm_failure_behind_a_generic_exit_code() -> None:
    signature = signature_from_log(recorded_log("npm-gyp-exit-code.log"))

    assert signature is not None
    assert signature.category is Category.DEPENDENCIES
    assert signature.message == "npm error gyp ERR! Completion callback never invoked!"
    assert "Node-gyp failed to build your package." in signature.excerpt


def test_recorded_stryker_failure_skips_stack_frames() -> None:
    signature = signature_from_log(recorded_log("stryker-exit-code.log"))

    assert signature is not None
    assert signature.message == "Error: Something went wrong in the initial test run"
    assert signature.excerpt.splitlines() == [
        "Error: Something went wrong in the initial test run",
        "Node.js v22.23.3",
    ]


def test_weak_error_words_are_the_last_resort() -> None:
    log = f"{STAMP}step one\n{STAMP}upload failed, retrying\n{STAMP}done\n"
    log += f"{STAMP}##[error]Process completed with exit code 1.\n"

    signature = signature_from_log(log)

    assert signature is not None
    assert signature.message == "upload failed, retrying"


def test_generic_exit_code_is_the_fallback() -> None:
    log = f"{STAMP}compiling\n{STAMP}##[error]Process completed with exit code 2.\n"

    signature = signature_from_log(log)

    assert signature is not None
    assert signature.category is Category.EXIT_CODE
    assert signature.message == "Process completed with exit code N."


def test_log_without_error_marker_has_no_signature() -> None:
    assert signature_from_log(f"{STAMP}all good\n") is None


def test_escape_sequences_and_control_characters_are_removed() -> None:
    hostile = "\x1b[31mred\x1b[0m \x1b]0;title\x07bell\x07 \x9bcsi \x00nul\ttab"

    assert clean_text(hostile) == "red bell csi nul\ttab"


def test_entries_join_continuation_lines_and_normalise_newlines() -> None:
    log = f"\nbefore stamp\r\n{STAMP}first\r\ncontinued\r\n{STAMP}##[error]boom\n  detail\n"

    assert log_entries(log) == ["before stamp", "first\ncontinued", "##[error]boom\n  detail\n"]
    assert error_entries(log) == ["boom\n  detail"]


@pytest.mark.parametrize(
    ("raw", "normalised"),
    [
        ("1) took 2026-10-07T09:27:35Z", "took <time>"),
        ("id 0f8cf866-ad7e-3242-1a21-9fc551a0a0ea", "id <id>"),
        ("commit deadbeef1234", "commit <hex>"),
        ("wrote /tmp/pytest-of-runner/x.txt", "wrote <tmp>"),
        ("after 20000ms and 1.5 s", "after <duration> and <duration>"),
        ("line 42   col 7", "line N col N"),
        ("tests/e2e/a.spec.ts:77:7 v2", "tests/e2e/a.spec.ts:N:N v2"),
    ],
)
def test_normalise(raw: str, normalised: str) -> None:
    assert normalise(raw) == normalised


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("The self-hosted runner lost communication with the server.", Category.RUNNER),
        ("FATAL ERROR: Reached heap limit - JavaScript heap out of memory", Category.RESOURCES),
        ("API rate limit exceeded for installation", Category.RATE_LIMIT),
        ("Error: read ECONNRESET", Category.NETWORK),
        ("connect ETIMEDOUT 140.82.112.3:443", Category.NETWORK),
        ("npm error code E404", Category.DEPENDENCIES),
        ("The job running on runner X has exceeded the maximum execution time", Category.OTHER),
        ("Test timed out after 5000ms", Category.TIMEOUT),
        ("AssertionError: expected 2 to equal 1", Category.ASSERTION),
        ("Process completed with exit code 1.", Category.EXIT_CODE),
        ("Something odd happened", Category.OTHER),
    ],
)
def test_categories(text: str, category: Category) -> None:
    assert categorise(text) is category
