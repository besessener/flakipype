import json
import os
from pathlib import Path
from typing import Protocol

from keyring.backend import KeyringBackend
from keyring.backends import fail
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE_NAME = "flakipype"
LLM_API_KEY = "llm-api-key"


class SecretStoreError(Exception):
    """The secret store could not be read or written."""


class SecretStore(Protocol):
    @property
    def location(self) -> str: ...

    def get(self, name: str) -> str | None: ...

    def put(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class KeyringSecretStore:
    def __init__(self, backend: KeyringBackend) -> None:
        self._backend = backend

    @property
    def location(self) -> str:
        return f"system keyring ({self._backend.name})"

    def get(self, name: str) -> str | None:
        try:
            return self._backend.get_password(SERVICE_NAME, name)
        except KeyringError as error:
            raise SecretStoreError(str(error)) from error

    def put(self, name: str, value: str) -> None:
        try:
            self._backend.set_password(SERVICE_NAME, name, value)
        except KeyringError as error:
            raise SecretStoreError(str(error)) from error

    def delete(self, name: str) -> None:
        try:
            self._backend.delete_password(SERVICE_NAME, name)
        except PasswordDeleteError:
            return
        except KeyringError as error:
            raise SecretStoreError(str(error)) from error


class FileSecretStore:
    """Fallback for machines without a keyring: a JSON file only the owner can read."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def location(self) -> str:
        return f"file {self._path} (mode 0600)"

    def get(self, name: str) -> str | None:
        return self._read().get(name)

    def put(self, name: str, value: str) -> None:
        secrets = self._read()
        secrets[name] = value
        self._write(secrets)

    def delete(self, name: str) -> None:
        secrets = self._read()
        if secrets.pop(name, None) is not None:
            self._write(secrets)

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            content = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            message = f"Cannot read {self._path}: {error}"
            raise SecretStoreError(message) from error
        if not isinstance(content, dict):
            message = f"Cannot read {self._path}: expected a JSON object"
            raise SecretStoreError(message)
        return {str(key): str(value) for key, value in content.items()}

    def _write(self, secrets: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Created with 0600 from the start, so the secret is never readable by others.
        descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(secrets, file)
        self._path.chmod(0o600)


def default_secret_store(backend: KeyringBackend, fallback_file: Path) -> SecretStore:
    if isinstance(backend, fail.Keyring):
        return FileSecretStore(fallback_file)
    return KeyringSecretStore(backend)
