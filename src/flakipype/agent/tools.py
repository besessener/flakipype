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


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    # Declared in code, never chosen by the model.
    risk: RiskLevel
    input_model: type[BaseModel]
    handler: Callable[[Any], str]

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }

    def invoke(self, arguments: Mapping[str, Any]) -> str:
        try:
            parsed = self.input_model.model_validate(dict(arguments))
        except ValidationError as error:
            message = f"Invalid input for {self.name}: {error}"
            raise ToolError(message) from error
        return self.handler(parsed)


class PolicyGate:
    """Decides before every tool call; reading is always allowed."""

    def __init__(self, mode: Mode, confirm: Callable[[Tool], bool]) -> None:
        self._mode = mode
        self._confirm = confirm

    def permits(self, tool: Tool) -> bool:
        if tool.risk is RiskLevel.READ:
            return True
        if self._mode is Mode.AUTO:
            return True
        return self._confirm(tool)


def deny_all(tool: Tool) -> bool:
    """Confirmation for headless runs without a human: nothing beyond reading."""
    del tool
    return False
