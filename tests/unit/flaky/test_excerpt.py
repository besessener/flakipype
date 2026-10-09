from pathlib import Path

from flakipype.flaky.excerpt import failure_excerpt, log_range, parse_log

LOGS = Path(__file__).parents[2] / "fixtures" / "logs"
STAMP = "2026-10-07T09:00:{:02d}.1234567Z "


def recorded(name: str) -> str:
    return (LOGS / name).read_text(encoding="utf-8")


def test_playwright_failure_excerpt() -> None:
    excerpt = failure_excerpt(recorded("playwright-timeout.log"), max_lines=120)

    lines = excerpt.text.splitlines()
    assert excerpt.step_header == "Run npm run build"
    assert excerpt.first_line == 1
    assert excerpt.total_lines == 28
    assert lines[0] == "+00:00  ##[group]Run npm run build"
    assert any(line.startswith("+09:37") and "✓  138" in line for line in lines)
    assert "            Error: expect(locator).toHaveCount(expected) failed" in lines
    assert "            Timeout:  20000ms" in lines
    assert lines[-2].endswith("Cleaning up orphan processes")


def test_generic_exit_code_gets_a_long_look_back() -> None:
    body = [f"{STAMP.format(second)}line {second}" for second in range(50)]
    log = "\n".join([*body, STAMP.format(55) + "##[error]Process completed with exit code 1."])

    excerpt = failure_excerpt(log, max_lines=120)

    assert excerpt.first_line == 11
    assert excerpt.text.splitlines()[0] == "+00:00  line 10"


def test_distant_errors_get_separate_windows() -> None:
    body = [f"{STAMP.format(second % 60)}line {second}" for second in range(100)]
    body[10] = STAMP.format(10) + "##[error]first"
    body[90] = STAMP.format(30) + "##[error]second"

    excerpt = failure_excerpt("\n".join(body), max_lines=120)

    assert "[… lines 27-70 skipped …]" in excerpt.text
    assert (excerpt.first_line, excerpt.last_line) == (1, 100)


def test_repeated_lines_are_collapsed() -> None:
    log = "\n".join(
        [STAMP.format(1) + "##[error]boom", *["    - locator resolved to 1 element"] * 5, "end"]
    )

    lines = failure_excerpt(log, max_lines=120).text.splitlines()

    assert lines[1:3] == [
        "            - locator resolved to 1 element",
        "        [… 4 identical lines …]",
    ]


def test_long_excerpts_are_truncated() -> None:
    log = "\n".join([STAMP.format(1) + "##[error]boom", *[f"detail {n}" for n in range(30)]])

    lines = failure_excerpt(log, max_lines=5).text.splitlines()

    assert len(lines) == 6
    assert lines[-1] == "[… excerpt truncated; use log_range for more …]"


def test_log_without_errors_shows_the_end() -> None:
    log = "\n".join(f"line {n}" for n in range(10))

    excerpt = failure_excerpt(log, max_lines=3)

    assert excerpt.text.splitlines() == ["        line 7", "        line 8", "        line 9"]
    assert excerpt.step_header == ""


def test_log_range_is_numbered_cleaned_and_capped() -> None:
    log = "\n".join(f"{STAMP.format(1)}\x1b[31mline {n}\x1b[0m" for n in range(1, 400))

    shown = log_range(log, 0, 1000).splitlines()

    assert shown[0] == "    1 line 1"
    assert len(shown) == 200
    assert log_range(log, 398, 500).splitlines() == ["  398 line 398", "  399 line 399"]


def test_parse_keeps_untimestamped_lines() -> None:
    lines = parse_log("plain\n" + STAMP.format(5) + "stamped")

    assert [(line.number, line.stamp is None, line.text) for line in lines] == [
        (1, True, "plain"),
        (2, False, "stamped"),
    ]
