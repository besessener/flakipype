"""Turn a job log into an error signature that groups the same failure across runs."""

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum

_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b.")
# Logs are untrusted: drop every control character except newline and tab.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_ERROR_MARK = "##[error]"
# Bump whenever messages or fingerprints change, so cached signatures are recomputed.
SIGNATURE_VERSION = 3
_GENERIC_EXIT = re.compile(r"^Process completed with exit code \d+\.?$")
_LIST_MARKER = re.compile(r"^\d+\)\s*")
_LOOKBACK_ENTRIES = 40
_STACK_FRAME = re.compile(r"^\s+at\s")
_WARNING = re.compile(r"\bwarn(?:ing)?\b", re.IGNORECASE)
_STRONG_ERROR = re.compile(
    r"ERR!|\b(?:Error|error|fatal|FATAL|panic):|Traceback|\bFAILED\b|\bException\b"
)
_WEAK_ERROR = re.compile(r"\b(?:error|failed|failure)\b", re.IGNORECASE)
_MESSAGE_LINES = 3
_MESSAGE_LENGTH = 400
_EXCERPT_LINES = 12
_EXCERPT_LENGTH = 1500
_FINGERPRINT_LENGTH = 12

_UUID = r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
_NORMALISERS = (
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\b"), "<time>"),
    (re.compile(_UUID, re.IGNORECASE), "<id>"),
    (re.compile(r"\b[0-9a-f]{7,}\b", re.IGNORECASE), "<hex>"),
    (re.compile(r"/tmp/\S+"), "<tmp>"),  # noqa: S108 - matches temp paths in log text, creates none
    (re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|seconds?|m|min|minutes?)\b"), "<duration>"),
    (re.compile(r"\b\d+\b"), "N"),
    (re.compile(r"\s+"), " "),
)


class Category(StrEnum):
    RUNNER = "runner"
    RESOURCES = "resources"
    RATE_LIMIT = "rate limit"
    NETWORK = "network"
    DEPENDENCIES = "dependencies"
    TIMEOUT = "timeout"
    ASSERTION = "assertion"
    EXIT_CODE = "exit code"
    OTHER = "other"


# First match wins, so the more specific causes come first (a network timeout is "network").
_CATEGORY_PATTERNS = (
    (Category.RUNNER, (
        r"lost communication with the server|runner has received a shutdown|"
        r"hosted runner encountered an error|runner .* (?:was )?(?:lost|terminated)"
    )),
    (Category.RESOURCES, (
        r"out of memory|oomkilled|heap out of memory|enospc|"
        r"no space left on device|exit code 137"
    )),
    (Category.RATE_LIMIT, r"rate limit|too many requests|\b429\b"),
    (Category.NETWORK, (
        r"econnreset|econnrefused|etimedout|enotfound|eai_again|socket hang up|"
        r"connection (?:reset|refused|timed out)|could not resolve host|"
        r"temporary failure in name resolution|tls handshake|\b50[234]\b|network is unreachable"
    )),
    (Category.DEPENDENCIES, (
        r"npm err!|npm error|could not resolve dependencies|"
        r"no matching distribution|unable to locate package|failed to download"
    )),
    (Category.TIMEOUT, r"timed? ?out|timeout|deadline exceeded"),
    (Category.ASSERTION, r"assert|expect\(|\bexpected\b|test failed|failed tests?\b"),
)  # fmt: skip
_COMPILED_CATEGORIES = tuple(
    (category, re.compile(pattern, re.IGNORECASE)) for category, pattern in _CATEGORY_PATTERNS
)


@dataclass(frozen=True)
class ErrorSignature:
    category: Category
    message: str
    fingerprint: str
    excerpt: str


def clean_text(text: str) -> str:
    return _CONTROL.sub("", _ANSI.sub("", text.replace("\r\n", "\n").replace("\r", "\n")))


def log_entries(log: str) -> list[str]:
    """Split a log into entries: a timestamped line plus the untimestamped lines after it."""
    entries: list[str] = []
    for line in clean_text(log).split("\n"):
        stamped = _TIMESTAMP.match(line)
        if stamped:
            entries.append(line[stamped.end() :])
        elif entries:
            entries[-1] += "\n" + line
        elif line:
            entries.append(line)
    return entries


def error_entries(log: str) -> list[str]:
    return [
        entry.removeprefix(_ERROR_MARK).strip()
        for entry in log_entries(log)
        if entry.startswith(_ERROR_MARK)
    ]


def cause_before(entries: list[str], end: int) -> list[str]:
    """The most telling error lines before a generic exit-code error, or none."""
    start = max(0, end - _LOOKBACK_ENTRIES)
    window = [
        entry.strip()
        for entry in entries[start:end]
        if entry.strip()
        and not _STACK_FRAME.match(entry)
        and not entry.startswith("##[")
        and not _WARNING.search(entry)
    ]
    for pattern in (_STRONG_ERROR, _WEAK_ERROR):
        for index, entry in enumerate(window):
            if pattern.search(entry):
                return window[index:]
    return []


def normalise(text: str) -> str:
    normalised = _LIST_MARKER.sub("", text.strip())
    for pattern, replacement in _NORMALISERS:
        normalised = pattern.sub(replacement, normalised)
    return normalised.strip()


def categorise(text: str) -> Category:
    if _GENERIC_EXIT.match(text.strip()):
        return Category.EXIT_CODE
    for category, pattern in _COMPILED_CATEGORIES:
        if pattern.search(text):
            return category
    return Category.OTHER


def signature_from_log(log: str) -> ErrorSignature | None:
    entries = log_entries(log)
    marked = [index for index, entry in enumerate(entries) if entry.startswith(_ERROR_MARK)]
    if not marked:
        return None
    messages = [entries[index].removeprefix(_ERROR_MARK).strip() for index in marked]
    specific = [entry for entry in messages if not _GENERIC_EXIT.match(entry)]
    if specific:
        lines = _lines(specific[0])
        message_lines = lines[:_MESSAGE_LINES]
    else:
        cause = cause_before(entries, marked[0])
        lines = _lines("\n".join(cause)) or _lines(messages[0])
        message_lines = lines[:1]
    message = " · ".join(normalise(line) for line in message_lines)[:_MESSAGE_LENGTH]
    fingerprint = hashlib.sha256(message.encode()).hexdigest()[:_FINGERPRINT_LENGTH]
    excerpt = "\n".join(lines[:_EXCERPT_LINES])[:_EXCERPT_LENGTH]
    return ErrorSignature(categorise("\n".join(lines)), message, fingerprint, excerpt)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]
