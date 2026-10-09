"""Readable views of a job log for the agent: the failed step, errors with context."""

import re
from dataclasses import dataclass
from datetime import datetime

from flakipype.flaky.signature import clean_text

_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?Z ?")
_GROUP = "##[group]"
_ERROR = "##[error]"
_GENERIC_EXIT = re.compile(r"Process completed with exit code \d+")
_BEFORE = 20
_AFTER = 15
_BEFORE_GENERIC = 40
_MIN_REPEAT = 3
_MAX_RANGE = 200


@dataclass(frozen=True)
class LogLine:
    number: int
    stamp: datetime | None
    text: str


@dataclass(frozen=True)
class Excerpt:
    text: str
    first_line: int
    last_line: int
    total_lines: int
    step_header: str


def parse_log(log: str) -> list[LogLine]:
    lines = []
    for number, raw in enumerate(clean_text(log).split("\n"), start=1):
        match = _STAMP.match(raw)
        stamp = datetime.fromisoformat(match.group(1)) if match else None
        lines.append(LogLine(number, stamp, raw[match.end() :] if match else raw))
    return lines


def failure_excerpt(log: str, max_lines: int) -> Excerpt:
    """Errors of the failed step with context; repeated lines collapsed; capped at max_lines."""
    lines = parse_log(log)
    errors = [index for index, line in enumerate(lines) if line.text.startswith(_ERROR)]
    if not errors:
        start = max(0, len(lines) - max_lines)
        return _render(lines, [(start, len(lines))], max_lines, header="")
    step_start = _step_start(lines, errors[0])
    windows = _merge([_window(lines, index, step_start) for index in errors])
    header = lines[step_start].text.removeprefix(_GROUP) if _is_group(lines[step_start]) else ""
    return _render(lines, windows, max_lines, header=header)


def log_range(log: str, first: int, last: int) -> str:
    """Numbered raw lines first..last (1-based, inclusive), at most 200."""
    lines = parse_log(log)
    first = max(first, 1)
    last = min(last, first + _MAX_RANGE - 1, len(lines))
    return "\n".join(f"{line.number:>5} {line.text}" for line in lines[first - 1 : last])


def _is_group(line: LogLine) -> bool:
    return line.text.startswith(_GROUP)


def _step_start(lines: list[LogLine], first_error: int) -> int:
    for index in range(first_error, -1, -1):
        if _is_group(lines[index]):
            return index
    return 0


def _window(lines: list[LogLine], index: int, step_start: int) -> tuple[int, int]:
    before = _BEFORE_GENERIC if _GENERIC_EXIT.search(lines[index].text) else _BEFORE
    return max(step_start, index - before), min(len(lines), index + _AFTER + 1)


def _merge(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _render(
    lines: list[LogLine], windows: list[tuple[int, int]], max_lines: int, *, header: str
) -> Excerpt:
    origin = next((line.stamp for line in lines[windows[0][0] :] if line.stamp), None)
    output: list[str] = []
    for position, (start, end) in enumerate(windows):
        if position:
            output.append(f"[… lines {windows[position - 1][1] + 1}-{start} skipped …]")
        output.extend(_collapse([_format(line, origin) for line in lines[start:end]]))
    if len(output) > max_lines:
        output = [*output[:max_lines], "[… excerpt truncated; use log_range for more …]"]
    return Excerpt(
        text="\n".join(output),
        first_line=windows[0][0] + 1,
        last_line=windows[-1][1],
        total_lines=len(lines),
        step_header=header.strip(),
    )


def _format(line: LogLine, origin: datetime | None) -> str:
    if line.stamp is None or origin is None:
        return f"        {line.text}"
    seconds = int((line.stamp - origin).total_seconds())
    return f"+{seconds // 60:02d}:{seconds % 60:02d}  {line.text}"


def _collapse(formatted: list[str]) -> list[str]:
    collapsed: list[str] = []
    index = 0
    while index < len(formatted):
        run_end = index
        while run_end + 1 < len(formatted) and _body(formatted[run_end + 1]) == _body(
            formatted[index]
        ):
            run_end += 1
        repeats = run_end - index + 1
        if repeats >= _MIN_REPEAT and _body(formatted[index]):
            collapsed.append(formatted[index])
            collapsed.append(f"        [… {repeats - 1} identical lines …]")
        else:
            collapsed.extend(formatted[index : run_end + 1])
        index = run_end + 1
    return collapsed


def _body(formatted: str) -> str:
    return formatted[8:].strip()
