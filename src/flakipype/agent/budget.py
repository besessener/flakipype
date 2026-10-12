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


class Stop:
    """Asked for when the chat window closes; work ends at its next model round."""

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def requested(self) -> bool:
        return self._event.is_set()

    def request(self) -> None:
        self._event.set()


@dataclass(frozen=True)
class Limits:
    rounds: int = 12
    tokens: int = 200_000
    seconds: float = 300.0


def _never() -> bool:
    return False


class RunBudget:
    """Tokens shared by all investigations of one run; safe across threads."""

    def __init__(self, tokens: int, *, out_of_time: Callable[[], bool] = _never) -> None:
        self._limit = tokens
        self._used = 0
        self._lock = threading.Lock()
        # True once no new investigation may start, e.g. after an unattended run's time limit.
        self.out_of_time = out_of_time

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
    _subject = "one investigation"

    def __init__(
        self,
        limits: Limits,
        run: RunBudget,
        clock: Callable[[], float],
        *,
        stop: Stop | None = None,
    ) -> None:
        self._limits = limits
        self._run = run
        self._clock = clock
        self._stop = stop
        self._started = clock()
        self.rounds = 0
        self.tokens = 0

    def check(self) -> None:
        """Raise before the next model call if any limit is reached or a stop was asked for."""
        if self._stop is not None and self._stop.requested:
            message = "the request to stop"
            raise BudgetExceededError(message)
        if self.rounds >= self._limits.rounds:
            message = f"the limit of {self._limits.rounds} rounds"
            raise BudgetExceededError(message)
        if self.tokens >= self._limits.tokens:
            message = f"the limit of {self._limits.tokens:,} tokens for {self._subject}"
            raise BudgetExceededError(message)
        if self._clock() - self._started >= self._limits.seconds:
            message = f"the time limit of {self._limits.seconds:.0f} seconds"
            raise BudgetExceededError(message)
        if self._run.exhausted:
            message = "the token limit for this run"
            raise BudgetExceededError(message)

    def record(self, usage: TokenUsage) -> None:
        self._count(total_tokens(usage))

    def _count(self, tokens: int) -> None:
        self.rounds += 1
        self.tokens += tokens
        self._run.add(tokens)


class QuestionBudget(InvestigationBudget):
    """A chat question's limits count only what it adds to the conversation it continues.

    Every request sends the whole history again; counting it each round would stop every
    question of a long session. The first request's prompt is that history plus the question.
    """

    _subject = "one question"

    def __init__(
        self,
        limits: Limits,
        run: RunBudget,
        clock: Callable[[], float],
        *,
        stop: Stop | None = None,
    ) -> None:
        super().__init__(limits, run, clock, stop=stop)
        # Every token the API bills, for the session's total.
        self.billed = 0
        self._prefix: int | None = None

    def record(self, usage: TokenUsage) -> None:
        prompt = total_tokens(usage) - usage.output_tokens
        if self._prefix is None:
            self._prefix = prompt
        self.billed += total_tokens(usage)
        self._count(usage.output_tokens + max(0, prompt - self._prefix))
