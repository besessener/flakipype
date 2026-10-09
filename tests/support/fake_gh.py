import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flakipype.github.gh import GhCli

FAKE_GH_SCRIPT = Path(__file__).parent.parent / "fakes" / "gh.py"
GH_FIXTURES = Path(__file__).parent.parent / "fixtures" / "gh"


def gh_fixture(name: str) -> str:
    return (GH_FIXTURES / name).read_text(encoding="utf-8")


@dataclass
class FakeGh:
    """Scripted gh: record responses, hand out a GhCli, inspect what was called."""

    scenario_file: Path
    log_file: Path
    calls: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self, args: list[str], *, stdout: str = "", stderr: str = "", exit_code: int = 0
    ) -> None:
        self.calls.append(
            {"args": args, "stdout": stdout, "stderr": stderr, "exit_code": exit_code}
        )
        self.scenario_file.write_text(json.dumps({"calls": self.calls}), encoding="utf-8")

    @property
    def command(self) -> list[str]:
        return [sys.executable, str(FAKE_GH_SCRIPT)]

    def cli(self, host: str = "github.com") -> GhCli:
        return GhCli(self.command, host=host)

    def invocations(self) -> list[dict[str, Any]]:
        if not self.log_file.exists():
            return []
        lines = self.log_file.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]
