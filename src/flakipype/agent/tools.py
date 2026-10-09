"""Agent tools: a fixed risk level per tool, validated input, and the policy gate."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError


class RiskLevel(StrEnum):
    READ = "read"
    WRITE = "write"
    CRITICAL = "critical"


class Mode(StrEnum):
    ASK = "ask"
    AUTO = "auto"


class ToolError(Exception):
    """The tool could not do what was asked; the message goes back to the model."""


class ToolDeclinedError(ToolError):
    """The person said no to the action."""


@dataclass(frozen=True)
class ActionRequest:
    """What an action will do; built by code from validated input and GitHub's data."""

    title: str
    details: tuple[str, ...]


@dataclass(frozen=True)
class PreparedAction:
    """A checked action that has not run yet: the gate decides between `run` and `declined`."""

    request: ActionRequest
    run: Callable[[], str]
    declined: Callable[[], None]


type ToolOutcome = str | PreparedAction


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    # Declared in code, never chosen by the model.
    risk: RiskLevel
    input_model: type[BaseModel]
    # Reading tools answer with text; all others prepare an action for the gate.
    handler: Callable[[Any], ToolOutcome]

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }

    def invoke(self, arguments: Mapping[str, Any], gate: "PolicyGate") -> str:
        try:
            parsed = self.input_model.model_validate(dict(arguments))
        except ValidationError as error:
            message = f"Invalid input for {self.name}: {error}"
            raise ToolError(message) from error
        outcome = self.handler(parsed)
        if isinstance(outcome, str):
            if self.risk is not RiskLevel.READ:
                message = f"{self.name} changes something and must prepare an action request"
                raise TypeError(message)
            return outcome
        if not gate.permits(self.risk, outcome.request):
            outcome.declined()
            message = f"{self.name}: the user declined. Do not ask for it again in this turn."
            raise ToolDeclinedError(message)
        return outcome.run()


def deny_all(request: ActionRequest) -> bool:
    """Confirmation without a human: nothing beyond reading."""
    del request
    return False


class PolicyGate:
    """Decides before every action; reading is always allowed."""

    def __init__(self, mode: Mode, confirm: Callable[[ActionRequest], bool]) -> None:
        self._mode = mode
        self._confirm = confirm

    def permits(self, risk: RiskLevel, request: ActionRequest) -> bool:
        if risk is RiskLevel.READ:
            return True
        if self._mode is Mode.AUTO:
            return True
        return self._confirm(request)


class Confirmer:
    """Passes confirmations to whoever can ask the person; declines while nobody can."""

    def __init__(self) -> None:
        self.ask: Callable[[ActionRequest], bool] = deny_all

    def __call__(self, request: ActionRequest) -> bool:
        return self.ask(request)
