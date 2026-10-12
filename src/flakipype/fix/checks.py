"""Deterministic checks of a fix's diff: errors send it back, warnings need a person."""

import json
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml

from flakipype.agent.masking import MASK_MARKER
from flakipype.agent.workcopy import FileChange

if TYPE_CHECKING:
    from collections.abc import Callable

_WORKFLOWS = ".github/workflows/"
_GITHUB = ".github/"
_HIDES = re.compile(
    r"continue-on-error:\s*true|\bif:\s*(\$\{\{\s*)?always\(\)|"
    r"\.skip\(|\bxit\(|\bxdescribe\(|\bxtest\(|\bpytest\.(skip|xfail)\(|"
    r"\bpytest\.mark\.(skip|xfail)|\.skipTest\(|\bSkipTest\b|"
    r"@unittest\.skip|@Disabled\b|@Ignore\b|\bt\.Skip(Now|f)?\(|\.only\("
)
# A loopback URL is exempt only when its host ends right after the name and has no userinfo.
_REACHES_OUT = re.compile(
    r"\bsecrets\.|github\.token|\bprintenv\b|(^|[;&|]|run:)\s*env\s*($|[|>])|"
    r"\b(curl|wget|nc|ncat)\b|(?i:https?://[^/?#\s]*@)|"
    r"(?i:https?://(?!(localhost|127\.0\.0\.1|\[::1\])([:/?#'\"`)\]>,;\s]|$)))"
)
_TEST_DECLARATION = re.compile(r"^\s*((async\s+)?def test_|(it|test|describe)\(|func Test|@Test\b)")


@dataclass(frozen=True)
class DiffLimits:
    max_files: int
    max_changed_lines: int


def change_errors(changes: list[FileChange], limits: DiffLimits) -> list[str]:
    """Problems the fixer must correct before the fix can go anywhere."""
    if not changes:
        return ["The diff is empty: edit the working copy before submitting."]
    errors = []
    if len(changes) > limits.max_files:
        errors.append(
            f"The fix changes {len(changes)} files; at most {limits.max_files} are allowed."
        )
    lines = sum(len(change.added) + len(change.removed) for change in changes)
    if lines > limits.max_changed_lines:
        errors.append(
            f"The fix changes {lines} lines; at most {limits.max_changed_lines} are allowed."
        )
    errors.extend(problem for change in changes if (problem := _parse_problem(change)))
    errors.extend(
        f"{change.path} adds `{MASK_MARKER}...]`: masked lines hide real content; "
        "leave them unchanged."
        for change in changes
        if change.after.count(MASK_MARKER) > (change.before or "").count(MASK_MARKER)
    )
    return errors


def change_warnings(changes: list[FileChange]) -> list[str]:
    """What a person has to look at: hidden failures, reaching out, changes under .github/."""
    warnings: list[str] = []
    for change in changes:
        hides = _matches(_HIDES, change.added)
        removed_tests = _count(_TEST_DECLARATION, change.removed)
        if removed_tests > _count(_TEST_DECLARATION, change.added):
            hides.append("removes a test")
        if hides:
            warnings.append(f"hides failures: {change.path} ({', '.join(hides)})")
        reaches = _matches(_REACHES_OUT, change.added)
        if reaches:
            warnings.append(f"reaches out: {change.path} ({', '.join(reaches)})")
        if change.path.startswith(_GITHUB):
            warnings.append(f"changes .github/: {change.path}")
    return warnings


def _matches(pattern: re.Pattern[str], lines: list[str]) -> list[str]:
    found = {match.group(0).strip() for line in lines for match in pattern.finditer(line)}
    return [f"adds `{text}`" for text in sorted(found)]


def _count(pattern: re.Pattern[str], lines: list[str]) -> int:
    return sum(1 for line in lines if pattern.search(line))


def _parse_problem(change: FileChange) -> str | None:
    parsers: dict[str, Callable[[str], Any]] = {
        ".yml": yaml.safe_load,
        ".yaml": yaml.safe_load,
        ".json": json.loads,
        ".toml": tomllib.loads,
    }
    suffix = change.path[change.path.rfind(".") :].lower() if "." in change.path else ""
    parse = parsers.get(suffix)
    if parse is None:
        return None
    try:
        document = parse(change.after)
    except (yaml.YAMLError, ValueError) as error:
        first_line = str(error).splitlines()[0]
        return f"{change.path} no longer parses: {first_line}"
    if change.path.startswith(_WORKFLOWS) and not _is_workflow(document):
        return f"{change.path} is no longer a workflow: it needs `on` and `jobs`."
    return None


def _is_workflow(document: object) -> bool:
    # YAML 1.1 reads the unquoted key `on` as the boolean true.
    return (
        isinstance(document, dict)
        and ("on" in document or True in document)
        and ("jobs" in document)
    )
