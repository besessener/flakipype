import json
import os
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import Protocol

from keyring.backend import KeyringBackend
from keyring.backends import fail, null
from keyring.errors import KeyringError

from flakipype.config.settings import SecretStoreChoice

SERVICE_NAME = "flakipype"
LLM_API_KEY = "llm-api-key"
# Long enough to type a password into an unlock prompt, short enough that a timer run never hangs.
KEYRING_SECONDS = 15.0


class SecretStoreError(Exception):
    """The secret store could not be read or written."""


class SecretStore(Protocol):
    @property
    def location(self) -> str: ...

    def get(self, name: str) -> str | None: ...

    def put(self, name: str, value: str) -> None: ...


class KeyringSecretStore:
    def __init__(self, backend: KeyringBackend, *, wait_seconds: float = KEYRING_SECONDS) -> None:
        self._backend = backend
        self._wait_seconds = wait_seconds

    @property
    def location(self) -> str:
        return f"system keyring ({self._backend.name})"

    def get(self, name: str) -> str | None:
        return self._answer(lambda: self._backend.get_password(SERVICE_NAME, name))

    def put(self, name: str, value: str) -> None:
        """Reads the secret back: some backends accept a secret and keep nothing."""
        self._answer(lambda: self._backend.set_password(SERVICE_NAME, name, value))
        if self.get(name) != value:
            message = f"the {self.location} accepted the secret but does not return it"
            raise SecretStoreError(message)

    def _answer[Answer](self, call: Callable[[], Answer]) -> Answer:
        """A locked keyring can wait forever for an unlock prompt nobody answers."""
        answer: Future[Answer] = Future()

        def ask() -> None:
            try:
                answer.set_result(call())
            except Exception as error:  # noqa: BLE001 - handed to the waiting caller below
                answer.set_exception(error)

        # A daemon thread, so a call stuck on D-Bus never keeps the process from exiting.
        threading.Thread(target=ask, name="keyring", daemon=True).start()
        try:
            return answer.result(timeout=self._wait_seconds)
        except TimeoutError as error:
            message = (
                f"the {self.location} did not answer within {self._wait_seconds:g} s; "
                "it is probably locked with nothing here to unlock it"
            )
            raise SecretStoreError(message) from error
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

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            content = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            message = f"Cannot read {self._path}: {error}"
            raise SecretStoreError(message) from error
        if not isinstance(content, dict):
            message = f"Cannot read {self._path}: expected a JSON object"
            raise SecretStoreError(message)
        return {str(key): str(value) for key, value in content.items()}

    def _write(self, secrets: dict[str, str]) -> None:
        # A new file replaces the old one whole, so a failed write never leaves it empty or partial.
        temporary: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # mkstemp creates the file with 0600, so the secret is never readable by others.
            descriptor, name = tempfile.mkstemp(dir=self._path.parent, prefix=".secrets-")
            temporary = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(secrets, file)
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(self._path)
        except OSError as error:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            message = f"Cannot write {self._path}: {error}"
            raise SecretStoreError(message) from error


def secret_store(choice: SecretStoreChoice, backend: KeyringBackend, file: Path) -> SecretStore:
    """The store `secrets.store` names; "auto" uses the file only where no keyring exists."""
    # The null backend is the usual way to switch keyring off; it keeps nothing.
    no_keyring = isinstance(backend, fail.Keyring | null.Keyring)
    if choice is SecretStoreChoice.FILE or (choice is SecretStoreChoice.AUTO and no_keyring):
        return FileSecretStore(file)
    return KeyringSecretStore(backend)
