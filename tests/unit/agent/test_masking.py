import time

import pytest

from flakipype.agent.masking import Masker

# Secret-looking values are assembled at runtime so no scanner mistakes this file for a leak.
GITHUB_TOKEN = "gh" + "p_" + "a1B2" * 9
FINE_GRAINED = "github_" + "pat_" + "Z9" * 30
ANTHROPIC_KEY = "sk-" + "ant-" + "api03-" + "x" * 30
AWS_KEY = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
KEY_BLOCK = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END " + "RSA PRIVATE KEY-----"
JWT = "ey" + "J" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20
SHORT_HEADER = "ey" + "J" + "a" * 9 + "." + "b" * 10 + "." + "c" * 10


GITHUB_APP_TOKEN = "gh" + "s_" + "c3D4" * 9
GITHUB_OAUTH_TOKEN = "gh" + "o_" + "e5F6" * 9
AWS_SESSION_KEY = "AS" + "IA" + "QRSTUVWXYZ234567"
SLACK_TOKEN = "xo" + "xb-" + "1234567890-" + "abcdefghij"
BEARER = "q" * 20 + "wxyz"
PASSWORD = "correct-horse-battery"  # noqa: S105 - a fake password the masker must hide
API_KEY = "abcdef" + "123456"
URL_PASSWORD = "hunter2secret"  # noqa: S105 - a fake password the masker must hide


@pytest.mark.parametrize(
    ("text", "secret", "kind"),
    [
        (f"token is {GITHUB_TOKEN} here", GITHUB_TOKEN, "github token"),
        (f"app {GITHUB_APP_TOKEN} here", GITHUB_APP_TOKEN, "github token"),
        (f"oauth {GITHUB_OAUTH_TOKEN} here", GITHUB_OAUTH_TOKEN, "github token"),
        (f"using {FINE_GRAINED}", FINE_GRAINED, "github token"),
        (f"ANTHROPIC_API_KEY={ANTHROPIC_KEY}", ANTHROPIC_KEY, "anthropic key"),
        (f"aws {AWS_KEY} end", AWS_KEY, "aws key"),
        (f"aws session {AWS_SESSION_KEY} end", AWS_SESSION_KEY, "aws key"),
        (f"slack {SLACK_TOKEN} end", SLACK_TOKEN, "slack token"),
        (f"key:\n{KEY_BLOCK}\nafter", KEY_BLOCK, "private key"),
        (f"Authorization: Bearer {BEARER}", BEARER, "bearer token"),
        (f"cookie {JWT}", JWT, "jwt"),
        (f"https://deploy:{URL_PASSWORD}@example.com/repo.git", URL_PASSWORD, "url credentials"),
        (f"DB_PASSWORD={PASSWORD}", PASSWORD, "secret"),
        ('"api_key": "' + API_KEY + '"', API_KEY, "secret"),
    ],
)
def test_secret_values_are_masked(text: str, secret: str, kind: str) -> None:
    masked = Masker().mask(text)

    assert f"[masked: {kind}]" in masked
    assert secret not in masked
    # A pattern that masks only a prefix leaves the tail behind.
    assert secret[-4:] not in masked


def test_known_secrets_are_masked_even_without_a_pattern() -> None:
    masker = Masker.with_secrets(["plain-but-secret-value", "short", "plain-but-secret"])

    masked = masker.mask("value plain-but-secret-value and short")

    assert masked == "value [masked: configured secret] and short"


def test_ordinary_log_text_is_left_alone() -> None:
    text = "Expected: 2\nReceived: 1\nTimeout:  20000ms\ntoken expired after 5 s"

    assert Masker().mask(text) == text


def test_an_unterminated_key_masks_only_its_body() -> None:
    truncated = "-----BEGIN " + "RSA PRIVATE KEY-----\\nMIIE"
    text = f"assert '{truncated}…' == key\n</tool-result>\n#2 next finding"

    masked = Masker().mask(text)

    assert masked == "assert '[masked: private key]…' == key\n</tool-result>\n#2 next finding"


def test_pgp_private_key_blocks_are_masked() -> None:
    armor = "PGP " + "PRIVATE KEY BLOCK-----"
    block = f"-----BEGIN {armor}\nVersion: x\n\nlQOYBF\n=ab12\n-----END {armor}"

    assert Masker().mask(f"key:\n{block}\nafter") == "key:\n[masked: private key]\nafter"


@pytest.mark.parametrize("assignment", ["password    = ", "password:  ", "token\t=\t"])
def test_aligned_assignments_are_masked(assignment: str) -> None:
    value = "correct" + "-horse"

    assert Masker().mask(f"{assignment}{value}") == f"{assignment}[masked: secret]"


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        (f"x-{JWT} y", "x-[masked: jwt] y"),
        (f"a.{JWT}.d", "a.[masked: jwt].d"),
        (f"x_{JWT}", f"x_{JWT}"),
        ("ab-eyJ" + "a" * 10 + "." + "b" * 10 + "." + "c" * 10, "ab-[masked: jwt]"),
        (SHORT_HEADER, SHORT_HEADER),
        ("eyJ" + "a" * 20 + ".short.c", "eyJ" + "a" * 20 + ".short.c"),
    ],
)
def test_jwts_are_masked_where_they_start(text: str, masked: str) -> None:
    assert Masker().mask(text) == masked


def test_masking_a_long_dotless_line_takes_linear_time() -> None:
    line = "eyJ-" * 250_000

    started = time.perf_counter()
    masked = Masker().mask(line)

    assert masked == line
    assert time.perf_counter() - started < 1
