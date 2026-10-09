from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from flakipype.agent.budget import Limits
from flakipype.agent.investigator import ModelSettings
from flakipype.agent.masking import Masker
from flakipype.agent.orchestrator import ChatAgent, ChatSettings, ignore_steps, workspace_tools
from flakipype.agent.prompts import CHAT_SYSTEM
from flakipype.agent.tools import Mode, PolicyGate, RiskLevel, Tool, deny_all

from support.fake_anthropic import ScriptedModel, call, message, text

SECRET = "super-secret-value"  # noqa: S105 - a fake secret the masker must hide


@dataclass
class FakeWorkspace:
    calls: list[tuple[object, ...]] = field(default_factory=list)

    def scan(self, days: int | None, repositories: tuple[str, ...]) -> str:
        self.calls.append(("scan", days, repositories))
        return f"Scanned. Token {SECRET}"

    def findings(self) -> str:
        self.calls.append(("findings",))
        return "#1 flaky"

    def investigate(self, numbers: tuple[int, ...], *, fresh: bool) -> str:
        self.calls.append(("investigate", numbers, fresh))
        return "verdicts"

    def verdict(self, number: int) -> str:
        self.calls.append(("verdict", number))
        return "verdict"


class Nothing(BaseModel):
    pass


def chat_agent(
    model: ScriptedModel,
    workspace: FakeWorkspace,
    *,
    limits: Limits | None = None,
    extra: list[Tool] | None = None,
    clock: Callable[[], float] = lambda: 0.0,
) -> ChatAgent:
    return ChatAgent(
        client=model.client(),
        settings=ChatSettings(
            model=ModelSettings(model="m-1"), limits=limits or Limits(), turn_tokens=1_000_000
        ),
        tools=[*workspace_tools(workspace), *(extra or [])],
        gate=PolicyGate(Mode.ASK, deny_all),
        masker=Masker.with_secrets([SECRET]),
        clock=clock,
    )


def test_tools_run_and_the_answer_is_kept_in_the_history() -> None:
    model = ScriptedModel(
        [
            message(
                call("t1", "scan", {"days": 7, "repositories": ["app"]}),
                call("t2", "list_findings", {}),
            ),
            message(call("t3", "investigate", {"findings": [1], "fresh": True})),
            message(call("t4", "show_verdict", {"finding": 1})),
            message(text("Finding 1 is a flaky test.")),
        ]
    )
    workspace = FakeWorkspace()
    agent = chat_agent(model, workspace)
    steps: list[str] = []

    reply = agent.ask(f"Why is it flaky? {SECRET}", steps.append)

    assert reply.completed
    assert reply.text == "Finding 1 is a flaky test."
    assert reply.tokens == 4 * 1_200
    assert workspace.calls == [
        ("scan", 7, ("app",)),
        ("findings",),
        ("investigate", (1,), True),
        ("verdict", 1),
    ]
    assert steps == ["scan", "list_findings", "investigate", "show_verdict"]
    first = model.requests[0]
    assert first["system"][0]["text"] == CHAT_SYSTEM
    assert first["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert SECRET not in first["messages"][0]["content"]
    scanned = model.tool_results(1)["t1"]["content"]
    assert "Scanned." in scanned
    assert SECRET not in scanned
    assert len(agent.history) == 8


def test_the_next_question_continues_the_conversation() -> None:
    model = ScriptedModel([message(text("Hello.")), message(text("Still here."))])
    agent = chat_agent(model, FakeWorkspace())

    agent.ask("Hi")
    agent.ask("And now?")

    assert [m["role"] for m in model.requests[1]["messages"]] == ["user", "assistant", "user"]


def test_restore_replaces_the_history() -> None:
    model = ScriptedModel([message(text("Welcome back."))])
    agent = chat_agent(model, FakeWorkspace())
    earlier = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello."}]

    agent.restore(earlier)
    agent.ask("Again")

    assert model.requests[0]["messages"][:2] == earlier
    assert len(agent.history) == 4


def test_a_limit_ends_the_turn_and_drops_it() -> None:
    model = ScriptedModel([message(call("t1", "list_findings", {}))])
    agent = chat_agent(model, FakeWorkspace(), limits=Limits(rounds=1))

    reply = agent.ask("List them")

    assert not reply.completed
    assert reply.text == "Stopped at the limit of 1 rounds."
    assert reply.tokens == 1_200
    assert agent.history == []


class SlowWorkspace(FakeWorkspace):
    def __init__(self, clock: list[float]) -> None:
        super().__init__()
        self.clock = clock

    def investigate(self, numbers: tuple[int, ...], *, fresh: bool) -> str:
        self.clock[0] += 1_000
        return super().investigate(numbers, fresh=fresh)


def test_time_in_tools_does_not_count_against_the_turn() -> None:
    now = [0.0]
    model = ScriptedModel(
        [message(call("t1", "investigate", {"findings": [1]})), message(text("Done."))]
    )
    agent = chat_agent(model, SlowWorkspace(now), limits=Limits(seconds=60), clock=lambda: now[0])

    assert agent.ask("Investigate 1").completed


def test_a_slow_model_ends_the_turn() -> None:
    model = ScriptedModel([message(call("t1", "list_findings", {}))])
    ticks = iter(range(0, 10**6, 100))
    agent = chat_agent(
        model, FakeWorkspace(), limits=Limits(seconds=60), clock=lambda: float(next(ticks))
    )

    assert agent.ask("List").text == "Stopped at the time limit of 60 seconds."


def test_model_errors_end_the_turn() -> None:
    agent = chat_agent(ScriptedModel([500]), FakeWorkspace())

    reply = agent.ask("Hi", ignore_steps)

    assert not reply.completed
    assert reply.text.startswith("The model could not answer:")
    assert agent.history == []


def test_repeating_the_same_call_ends_the_turn() -> None:
    same = call("t1", "list_findings", {})
    model = ScriptedModel([message(same), message({**same, "id": "t2"})])
    workspace = FakeWorkspace()

    reply = chat_agent(model, workspace).ask("List them")

    assert reply.text == "Stopped: the same tool call repeated."
    assert workspace.calls == [("findings",)]


def test_unknown_gated_and_invalid_calls_are_errors_for_the_model() -> None:
    writes: list[str] = []

    def open_pr(_: Nothing) -> str:
        writes.append("pr")
        return "opened"

    write = Tool("open_pr", "Open a PR.", RiskLevel.WRITE, Nothing, open_pr)
    model = ScriptedModel(
        [
            message(
                call("t1", "push", {}),
                call("t2", "open_pr", {}),
                call("t3", "investigate", {"findings": []}),
            ),
            message(text("I cannot do that.")),
        ]
    )

    reply = chat_agent(model, FakeWorkspace(), extra=[write]).ask("Fix it")

    results = model.tool_results(1)
    assert reply.completed
    assert results["t1"]["content"] == "push is not available."
    assert results["t2"]["content"] == "open_pr is not available."
    assert results["t3"]["is_error"] is True
    assert "Invalid input for investigate" in results["t3"]["content"]
    assert writes == []
