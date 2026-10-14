"""Deterministic checks of a fix's diff: errors send it back; warnings and code need a person."""

import json
import re
import tomllib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

import yaml

from flakipype.agent.masking import MASK_MARKER
from flakipype.agent.workcopy import FileChange

# GitHub runs only top-level .yml and .yaml files in .github/workflows/ as workflows.
_WORKFLOW_FILE = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$", re.IGNORECASE)
_GITHUB = ".github/"
# `.skip(` and `.only(` count on test receivers only, not on Mongo's `.skip(n)` or Django's.
_HIDES = re.compile(
    r"continue-on-error:\s*true|\bif:\s*(\$\{\{\s*)?always\(\)|"
    r"\b(it|test|describe|context|suite|fixture|this)(\.\w+)*\.(skip|only)\(|"
    r"\bxit\(|\bxdescribe\(|\bxtest\(|\bpytest\.(skip|xfail)\(|"
    r"\bpytest\.mark\.(skip|xfail)|\.skipTest\(|\bSkipTest\b|"
    r"@unittest\.skip|@Disabled\b|@Ignore\b|\bt\.Skip(Now|f)?\("
)
# A loopback URL is exempt only when its host ends right after the name and has no userinfo.
_REACHES_OUT = re.compile(
    r"\bsecrets\.|github\.token|\bprintenv\b|(^|[;&|]|run:)\s*env\s*($|[|>])|"
    r"\b(curl|wget|nc|ncat)\b|(?i:https?://[^/?#\s]*@)|"
    r"(?i:https?://(?!(localhost|127\.0\.0\.1|\[::1\])([:/?#'\"`)\]>,;\s]|$)))"
)
_TEST_DECLARATION = re.compile(
    r"^\s*((async\s+)?def test_|(it|test|describe)(\.\w+)*\(|func Test|@Test\b)"
)
_PROSE_SUFFIXES = (".md", ".markdown", ".rst", ".adoc")
# Instructions for coding agents, which a workflow may run with the repository's secrets.
_AGENT_INSTRUCTIONS = frozenset({"agents.md", "claude.md", "gemini.md"})
# Folders whose files tests read as input.
_TEST_FOLDERS = frozenset({"test", "tests", "spec", "specs", "__tests__", "fixtures", "testdata"})
# Prose that doc tools run: doctest prompts, code fences, reStructuredText directives.
_CODE_IN_PROSE = re.compile(r">>>|```|~~~|^\s*\.\.\s+\S+::", re.MULTILINE)


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
        hides = _added_matches(_HIDES, change)
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


def executable_paths(changes: list[FileChange]) -> list[str]:
    """Changed files that may run as code or feed it: everything except plain documentation."""
    return [change.path for change in changes if not _is_prose(change)]


def _is_prose(change: FileChange) -> bool:
    *folders, name = change.path.lower().split("/")
    return (
        name.endswith(_PROSE_SUFFIXES)
        and name not in _AGENT_INSTRUCTIONS
        and not any(folder.startswith(".") or folder in _TEST_FOLDERS for folder in folders)
        and not _CODE_IN_PROSE.search(change.after)
    )


def _matches(pattern: re.Pattern[str], lines: list[str]) -> list[str]:
    found = {match.group(0).strip() for line in lines for match in pattern.finditer(line)}
    return [f"adds `{text}`" for text in sorted(found)]


def _added_matches(pattern: re.Pattern[str], change: FileChange) -> list[str]:
    """Matches on added lines that the file now holds more often, so an edited line is no news."""
    before = _occurrences(pattern, change.before or "")
    after = _occurrences(pattern, change.after)
    found = {match.group(0).strip() for line in change.added for match in pattern.finditer(line)}
    return [f"adds `{text}`" for text in sorted(found) if after[text] > before[text]]


def _occurrences(pattern: re.Pattern[str], text: str) -> Counter[str]:
    return Counter(
        match.group(0).strip() for line in text.splitlines() for match in pattern.finditer(line)
    )


def _count(pattern: re.Pattern[str], lines: list[str]) -> int:
    return sum(1 for line in lines if pattern.search(line))


def _parse_problem(change: FileChange) -> str | None:
    """Only an edit that breaks a file counts; one that never parsed strictly is left alone."""
    suffix = change.path[change.path.rfind(".") :].lower() if "." in change.path else ""
    parse = _PARSERS.get(suffix)
    if parse is None:
        return None
    try:
        document = parse(change.after)
    except RecursionError:
        problem = "it is nested too deeply to check"
    # YAML loaders let KeyError and AttributeError escape for invalid tagged values (`!!bool on1`).
    except (yaml.YAMLError, ValueError, KeyError, AttributeError) as error:
        problem = (str(error).splitlines() or [type(error).__name__])[0]
    else:
        if _WORKFLOW_FILE.match(change.path) and not _is_workflow(document):
            return f"{change.path} is no longer a workflow: it needs `on` and `jobs`."
        return None
    if change.before and not _parses(parse, change.before):
        return None
    return f"{change.path} no longer parses: {problem}"


def _parses(parse: Callable[[str], object], text: str) -> bool:
    try:
        parse(text)
    except (yaml.YAMLError, ValueError, KeyError, AttributeError, RecursionError):
        return False
    return True


class _AnyTagLoader(yaml.SafeLoader):
    """Reads application tags (`!Sub`, `!!python/name`) as plain values: only syntax is judged."""


def _untagged(
    loader: yaml.SafeLoader,
    _suffix: str,
    node: yaml.ScalarNode | yaml.SequenceNode | yaml.MappingNode,
) -> object:
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_scalar(node)


_AnyTagLoader.add_multi_constructor("!", _untagged)
_AnyTagLoader.add_multi_constructor("tag:", _untagged)


def _yaml_documents(text: str) -> list[object]:
    return list(yaml.load_all(text, Loader=_AnyTagLoader))


def _json(text: str) -> object:
    return json.loads(text.removeprefix("\ufeff"))


_PARSERS: dict[str, Callable[[str], object]] = {
    ".yml": _yaml_documents,
    ".yaml": _yaml_documents,
    ".json": _json,
    ".toml": tomllib.loads,
}


def _is_workflow(documents: object) -> bool:
    # YAML 1.1 reads the unquoted key `on` as the boolean true.
    if not isinstance(documents, list) or len(documents) != 1:
        return False
    document = documents[0]
    return (
        isinstance(document, dict)
        and ("on" in document or True in document)
        and ("jobs" in document)
    )
