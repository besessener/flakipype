"""Mask secrets in anything that is sent to the model."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

_MIN_KNOWN_SECRET = 8
MASK_MARKER = "[masked: "
_JWT = f"{MASK_MARKER}jwt]"
# Maximal runs of token characters; JWTs are found inside them in linear time.
_TOKEN_RUN = re.compile(r"[A-Za-z0-9_.-]+")
_JWT_START = re.compile(r"(?:^|(?<=-))eyJ")
_JWT_SEGMENT = 10
_JWT_PARTS = 3

# Ordered: specific token formats first, generic assignments last. Group "keep" is preserved.
# JWTs are masked before these, by _mask_jwts.
_PATTERNS = (
    # Without its END line, only the key body is masked, never the rest of the prompt.
    ("private key", re.compile(
        r"(?P<keep>)-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----"
        r"(?:.*?-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|(?:[A-Za-z0-9+/=:,\s-]|\\n)*)",
        re.DOTALL,
    )),
    ("github token", re.compile(
        r"(?P<keep>)\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"
    )),
    ("anthropic key", re.compile(r"(?P<keep>)\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("aws key", re.compile(r"(?P<keep>)\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack token", re.compile(r"(?P<keep>)\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("url credentials", re.compile(r"(?P<keep>://)[^/\s:@]+:[^/\s@]+(?=@)")),
    ("bearer token", re.compile(r"(?i)(?P<keep>bearer )[A-Za-z0-9._~+/=-]{16,}")),
    ("secret", re.compile(
        r"(?i)(?P<keep>(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)"
        r"[\"']?[ \t]*[:=][ \t]*[\"']?)(?!\[masked)[^\s\"',;]{6,}"
    )),
)  # fmt: skip


@dataclass(frozen=True)
class Masker:
    """Replaces known secrets (e.g. the configured API key) and secret-looking values."""

    known_secrets: tuple[str, ...] = ()

    @classmethod
    def with_secrets(cls, secrets: Iterable[str]) -> "Masker":
        usable = sorted({s for s in secrets if len(s) >= _MIN_KNOWN_SECRET}, key=len, reverse=True)
        return cls(tuple(usable))

    def mask(self, text: str) -> str:
        for secret in self.known_secrets:
            text = text.replace(secret, f"{MASK_MARKER}configured secret]")
        text = _TOKEN_RUN.sub(_mask_jwts, text)
        for kind, pattern in _PATTERNS:
            text = pattern.sub(rf"\g<keep>{MASK_MARKER}{kind}]", text)
        return text


def _mask_jwts(run: re.Match[str]) -> str:
    """Masks `eyJ…` segments followed by two more dotted segments of at least 10 characters."""
    if "eyJ" not in run.group(0):
        return run.group(0)
    segments = run.group(0).split(".")
    kept: list[str] = []
    index = 0
    while index < len(segments):
        start = _jwt_start(segments, index)
        if start is None:
            kept.append(segments[index])
            index += 1
        else:
            kept.append(segments[index][:start] + _JWT)
            index += _JWT_PARTS
    return ".".join(kept)


def _jwt_start(segments: list[str], index: int) -> int | None:
    rest = segments[index + 1 : index + _JWT_PARTS]
    if len(rest) < _JWT_PARTS - 1 or any(len(segment) < _JWT_SEGMENT for segment in rest):
        return None
    # A later `eyJ` in the segment has fewer characters after it, so only the first counts.
    found = _JWT_START.search(segments[index])
    if found is None or len(segments[index]) - found.end() < _JWT_SEGMENT:
        return None
    return found.start()
