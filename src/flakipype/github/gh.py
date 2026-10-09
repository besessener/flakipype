"""Run gh as a subprocess against one GitHub host."""

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

_DEFAULT_TIMEOUT_SECONDS = 60


class GhCommandError(Exception):
    """gh exited with an error."""

    def __init__(self, result: "GhResult") -> None:
        super().__init__(result.stderr.strip() or f"gh exited with code {result.exit_code}")
        self.result = result


@dataclass(frozen=True)
class GhResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


class GhCli:
    def __init__(self, command: Sequence[str], host: str) -> None:
        self._command = list(command)
        self._host = host

    @property
    def host(self) -> str:
        return self._host

    def run(self, arguments: Sequence[str], stdin_text: str = "") -> GhResult:
        completed = subprocess.run(  # noqa: S603 - argument list, never a shell
            [*self._command, *arguments],
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
            check=False,
            env=self._environment(),
        )
        return GhResult(completed.returncode, completed.stdout, completed.stderr)

    def run_interactive(self, arguments: Sequence[str]) -> int:
        """Run with the user's terminal attached, e.g. for the browser login."""
        completed = subprocess.run(  # noqa: S603 - argument list, never a shell
            [*self._command, *arguments],
            check=False,
            env=self._environment(),
        )
        return completed.returncode

    def _environment(self) -> dict[str, str]:
        return {**os.environ, "GH_HOST": self._host, "NO_COLOR": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
