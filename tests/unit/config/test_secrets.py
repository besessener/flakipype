import stat
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail
from keyring.errors import KeyringError, PasswordDeleteError

from flakipype.config.secrets import (
    FileSecretStore,
    KeyringSecretStore,
    SecretStoreError,
    secret_store,
)
from flakipype.config.settings import SecretStoreChoice


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self, failure: KeyringError | None = None) -> None:
        self.passwords: dict[tuple[str, str], str] = {}
        self.failure = failure

    def get_password(self, service: str, username: str) -> str | None:
        self._fail_if_broken()
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._fail_if_broken()
        self.passwords[service, username] = password

    def delete_password(self, service: str, username: str) -> None:
        self._fail_if_broken()
        if self.passwords.pop((service, username), None) is None:
            raise PasswordDeleteError(username)

    def _fail_if_broken(self) -> None:
        if self.failure is not None:
            raise self.failure


def test_keyring_store_round_trip() -> None:
    backend = MemoryKeyring()
    store = KeyringSecretStore(backend)

    store.put("llm-api-key", "value-1")

    assert store.get("llm-api-key") == "value-1"
    assert backend.passwords == {("flakipype", "llm-api-key"): "value-1"}
    store.delete("llm-api-key")
    assert store.get("llm-api-key") is None
    store.delete("llm-api-key")
    assert "system keyring" in store.location


def test_keyring_errors_become_secret_store_errors() -> None:
    store = KeyringSecretStore(MemoryKeyring(failure=KeyringError("locked")))

    with pytest.raises(SecretStoreError, match="locked"):
        store.get("name")
    with pytest.raises(SecretStoreError, match="locked"):
        store.put("name", "value")
    with pytest.raises(SecretStoreError, match="locked"):
        store.delete("name")


def test_file_store_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config" / "secrets.json"
    store = FileSecretStore(path)

    assert store.get("llm-api-key") is None
    store.put("llm-api-key", "value-1")
    store.put("other", "value-2")
    store.delete("other")
    store.delete("never-stored")

    assert FileSecretStore(path).get("llm-api-key") == "value-1"
    assert FileSecretStore(path).get("other") is None
    assert str(path) in store.location


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes do not exist on Windows")
def test_file_store_is_only_readable_by_the_owner(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o644)

    FileSecretStore(path).put("llm-api-key", "value-1")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_file_that_is_not_utf8_is_a_secret_store_error(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_bytes('{"a": "Größe"}'.encode("latin-1"))

    with pytest.raises(SecretStoreError, match="Cannot read"):
        FileSecretStore(path).get("llm-api-key")


@pytest.mark.parametrize("content", ["not json", "[1, 2]"])
def test_unreadable_file_is_a_secret_store_error(tmp_path: Path, content: str) -> None:
    path = tmp_path / "secrets.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(SecretStoreError, match="Cannot read"):
        FileSecretStore(path).get("llm-api-key")


def no_keyring() -> KeyringBackend:
    return fail.Keyring()


@pytest.mark.parametrize(
    ("choice", "backend", "expected"),
    [
        (SecretStoreChoice.AUTO, MemoryKeyring, KeyringSecretStore),
        (SecretStoreChoice.AUTO, no_keyring, FileSecretStore),
        (SecretStoreChoice.KEYRING, MemoryKeyring, KeyringSecretStore),
        (SecretStoreChoice.KEYRING, no_keyring, KeyringSecretStore),
        (SecretStoreChoice.FILE, MemoryKeyring, FileSecretStore),
    ],
)
def test_the_choice_picks_the_store(
    tmp_path: Path,
    choice: SecretStoreChoice,
    backend: Callable[[], KeyringBackend],
    expected: type[object],
) -> None:
    store = secret_store(choice, backend(), tmp_path / "secrets.json")

    assert isinstance(store, expected)


def test_a_chosen_keyring_that_does_not_exist_is_an_error(tmp_path: Path) -> None:
    store = secret_store(SecretStoreChoice.KEYRING, no_keyring(), tmp_path / "secrets.json")

    with pytest.raises(SecretStoreError):
        store.get("llm-api-key")
