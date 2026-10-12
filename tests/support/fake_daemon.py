"""systemctl and friends in memory: answers by the start of the command line, records every call."""

from dataclasses import dataclass, field

from flakipype.setup.daemon import CommandResult


@dataclass
class FakeRunner:
    """Every command not answered otherwise succeeds without output."""

    answers: dict[str, CommandResult] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __call__(self, arguments: list[str]) -> CommandResult:
        command = " ".join(arguments)
        self.calls.append(command)
        for start, answer in self.answers.items():
            if command.startswith(start):
                return answer
        return CommandResult(0, "")
