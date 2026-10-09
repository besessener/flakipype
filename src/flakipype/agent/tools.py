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


class Answer(StrEnum):
    """The gate's answer to an action request, as recorded in the audit log."""

    CONFIRMED = "confirmed"
    AUTO = "auto"
    DECLINED = "declined"
    NEEDS_PERSON = "not run in auto mode"


_REFUSALS = frozenset({Answer.DECLINED, Answer.NEEDS_PERSON})


class ToolError(Exception):
    """The tool could not do what was asked; the message goes back to the model."""


class ToolDeclinedError(ToolError):
    """The person said no to the action, or auto mode may not run it."""


@dataclass(frozen=True)
class ActionRequest:
    """What an action will do; built by code from validated input and GitHub's data."""

    title: str
    details: tuple[str, ...]
    # Text the model wrote and the change itself: shown apart from the facts, never as them.
    model_text: str = ""
    diff: str = ""
    # Set by code when only a person may allow the action, even in auto mode.
    needs_person: str = ""
    confirm_label: str = "Run"
    decline_label: str = "Don't run"


@dataclass(frozen=True)
class PreparedAction:
    """A checked action that has not run yet: the gate decides between `run` and `declined`."""

    request: ActionRequest
    run: Callable[[Answer], str]
    declined: Callable[[Answer], None]


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
        answer = gate.answer(self.risk, outcome.request)
        if answer in _REFUSALS:
            outcome.declined(answer)
            raise ToolDeclinedError(_refusal(self.name, answer, outcome.request))
        return outcome.run(answer)


def _refusal(name: str, answer: Answer, request: ActionRequest) -> str:
    if answer is Answer.NEEDS_PERSON:
        return (
            f"{name}: not run in auto mode because {request.needs_person}. "
            "The user can review it after switching to /mode ask."
        )
    return f"{name}: the user declined. Do not ask for it again in this turn."


def deny_all(request: ActionRequest) -> bool:
    """Confirmation without a human: nothing beyond reading."""
    del request
    return False


class PolicyGate:
    """Decides before every action; reading is always allowed."""

    def __init__(self, mode: Mode, confirm: Callable[[ActionRequest], bool]) -> None:
        # The chat switches it with /mode; a request that needs a person never runs in auto.
        self.mode = mode
        self._confirm = confirm

    def answer(self, risk: RiskLevel, request: ActionRequest) -> Answer:
        if risk is RiskLevel.READ:
            return Answer.AUTO
        if self.mode is Mode.AUTO:
            return Answer.NEEDS_PERSON if request.needs_person else Answer.AUTO
        return Answer.CONFIRMED if self._confirm(request) else Answer.DECLINED


class Confirmer:
    """Passes confirmations to whoever can ask the person; declines while nobody can."""

    def __init__(self) -> None:
        self.ask: Callable[[ActionRequest], bool] = deny_all

    def __call__(self, request: ActionRequest) -> bool:
        return self.ask(request)
