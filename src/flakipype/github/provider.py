from pathlib import Path
from typing import Protocol

from flakipype.github.binary import (
    DownloadProgress,
    GhBinary,
    GhInstaller,
    GhInstallError,
    ignore_progress,
    locate_gh,
)
from flakipype.github.gh import GhCli
from flakipype.github.release import UnsupportedPlatformError, linux_architecture


class GhProvider(Protocol):
    def find(self) -> GhBinary | None: ...

    def install(self, *, on_progress: DownloadProgress = ignore_progress) -> GhBinary: ...

    def cli(self, binary: GhBinary, host: str) -> GhCli: ...


class ManagedGh:
    """gh from PATH if recent enough, else the copy flakipype downloaded."""

    def __init__(self, installer: GhInstaller, *, on_path: Path | None, machine: str) -> None:
        self._installer = installer
        self._on_path = on_path
        self._machine = machine

    def find(self) -> GhBinary | None:
        candidates = [self._on_path] if self._on_path else []
        return locate_gh([*candidates, self._installer.target])

    def install(self, *, on_progress: DownloadProgress = ignore_progress) -> GhBinary:
        try:
            architecture = linux_architecture(self._machine)
        except UnsupportedPlatformError as error:
            raise GhInstallError(str(error)) from error
        return self._installer.install(architecture, on_progress=on_progress)

    def cli(self, binary: GhBinary, host: str) -> GhCli:
        return GhCli([str(binary.path)], host=host)
