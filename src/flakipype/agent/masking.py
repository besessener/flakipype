"""Mask secrets in anything that is sent to the model."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

_MIN_KNOWN_SECRET = 8

# Ordered: specific token formats first, generic assignments last. Group "keep" is preserved.
_PATTERNS = (
    ("private key", re.compile(
        r"(?P<keep>)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
        re.DOTALL,
    )),
    ("github token", re.compile(
        r"(?P<keep>)\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"
    )),
    ("anthropic key", re.compile(r"(?P<keep>)\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("aws key", re.compile(r"(?P<keep>)\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack token", re.compile(r"(?P<keep>)\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("jwt", re.compile(
        r"(?P<keep>)\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    )),
    ("url credentials", re.compile(r"(?P<keep>://)[^/\s:@]+:[^/\s@]+(?=@)")),
    ("bearer token", re.compile(r"(?i)(?P<keep>bearer )[A-Za-z0-9._~+/=-]{16,}")),
    ("secret", re.compile(
        r"(?i)(?P<keep>(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)"
        r"[\"']?\s?[:=]\s?[\"']?)(?!\[masked)[^\s\"',;]{6,}"
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
            text = text.replace(secret, "[masked: configured secret]")
        for kind, pattern in _PATTERNS:
            text = pattern.sub(rf"\g<keep>[masked: {kind}]", text)
        return text
