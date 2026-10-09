"""Hard limits: rounds, tokens and time per investigation, tokens per run."""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class BudgetExceededError(Exception):
    """A hard limit was reached; the message says which."""


class TokenUsage(Protocol):
    @property
    def input_tokens(self) -> int: ...

    @property
    def output_tokens(self) -> int: ...

    @property
    def cache_creation_input_tokens(self) -> int | None: ...

    @property
    def cache_read_input_tokens(self) -> int | None: ...


def total_tokens(usage: TokenUsage) -> int:
    return (
        usage.input_tokens
        + usage.output_tokens
        + (usage.cache_creation_input_tokens or 0)
        + (usage.cache_read_input_tokens or 0)
    )


@dataclass(frozen=True)
class Limits:
    rounds: int = 12
    tokens: int = 200_000
    seconds: float = 300.0


class RunBudget:
    """Tokens shared by all investigations of one run; safe across threads."""

    def __init__(self, tokens: int) -> None:
        self._limit = tokens
        self._used = 0
        self._lock = threading.Lock()

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def exhausted(self) -> bool:
        return self.used >= self._limit

    def add(self, tokens: int) -> None:
        with self._lock:
            self._used += tokens


class InvestigationBudget:
    def __init__(self, limits: Limits, run: RunBudget, clock: Callable[[], float]) -> None:
        self._limits = limits
        self._run = run
        self._clock = clock
        self._started = clock()
        self.rounds = 0
        self.tokens = 0

    def check(self) -> None:
        """Raise before the next model call if any limit is reached."""
        if self.rounds >= self._limits.rounds:
            message = f"the limit of {self._limits.rounds} rounds"
            raise BudgetExceededError(message)
        if self.tokens >= self._limits.tokens:
            message = f"the limit of {self._limits.tokens:,} tokens for one investigation"
            raise BudgetExceededError(message)
        if self._clock() - self._started >= self._limits.seconds:
            message = f"the time limit of {self._limits.seconds:.0f} seconds"
            raise BudgetExceededError(message)
        if self._run.exhausted:
            message = "the token limit for this run"
            raise BudgetExceededError(message)

    def record(self, usage: TokenUsage) -> None:
        tokens = total_tokens(usage)
        self.rounds += 1
        self.tokens += tokens
        self._run.add(tokens)
