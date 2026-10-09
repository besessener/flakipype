from pydantic import BaseModel

from flakipype.agent.budget import InvestigationBudget, Limits, RunBudget
from flakipype.agent.finding_tools import FindingTools
from flakipype.agent.investigator import Investigator, ModelSettings, Status
from flakipype.agent.masking import Masker
from flakipype.agent.pipeline import finding_text
from flakipype.agent.tools import Mode, PolicyGate, RiskLevel, Tool, deny_all

from support.fake_anthropic import ScriptedModel, call, message, text, thinking, verdict_input
from support.fake_sources import FakeContents, FakeLogs, evidence, finding

QUOTE = "Test timed out after 5000ms"
EXCERPT = call("toolu_1", "failure_excerpt", {"job_id": 11})


class Nothing(BaseModel):
    pass


def investigator(
    model: ScriptedModel,
    *,
    limits: Limits | None = None,
    extra: list[Tool] | None = None,
    settings: ModelSettings | None = None,
) -> Investigator:
    tools = FindingTools(finding(), evidence(), FakeLogs(), FakeContents()).tools()
    return Investigator(
        client=model.client(),
        settings=settings or ModelSettings(model="m-1"),
        tools=[*tools, *(extra or [])],
        gate=PolicyGate(Mode.ASK, deny_all),
        budget=InvestigationBudget(limits or Limits(), RunBudget(1_000_000), lambda: 0.0),
        masker=Masker.with_secrets(["super-secret-value"]),
    )


def submit(call_id: str, quote: str = QUOTE, tool_call_id: str = "toolu_1") -> dict[str, object]:
    return call(call_id, "submit_verdict", verdict_input(quote, tool_call_id))


def test_tool_calls_then_a_cited_verdict() -> None:
    model = ScriptedModel(
        [message(thinking("look at the log"), EXCERPT), message(submit("toolu_2"))]
    )
    agent = investigator(model)

    outcome = agent.start(finding_text(finding()) + " super-secret-value")

    assert outcome.status is Status.COMPLETED
    assert outcome.verdict is not None
    assert outcome.verdict.evidence[0].quote == QUOTE
    first, second = model.requests
    assert first["thinking"] == {"type": "adaptive"}
    assert first["tools"][-1]["name"] == "submit_verdict"
    assert first["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "super-secret-value" not in first["messages"][0]["content"]
    assert "[masked: configured secret]" in first["messages"][0]["content"]
    assert second["messages"][1]["content"][0]["type"] == "thinking"
    assert QUOTE in model.tool_results(1)["toolu_1"]["content"]
    assert set(agent.results) == {"finding", "toolu_1"}


def test_the_finding_can_be_cited_next_to_tool_results() -> None:
    arguments = verdict_input(QUOTE, "toolu_1")
    scan_quote = {**arguments["evidence"][0], "kind": "scan", "tool_call_id": "finding"}
    arguments["evidence"].append({**scan_quote, "quote": "Runs with a proven flaky event"})
    model = ScriptedModel([message(EXCERPT), message(call("toolu_2", "submit_verdict", arguments))])

    assert investigator(model).start(finding_text(finding())).status is Status.COMPLETED


def test_evidence_from_the_finding_alone_is_sent_back() -> None:
    only_finding = submit("toolu_1", "Runs with a proven flaky event", "finding")
    model = ScriptedModel([message(only_finding), message(EXCERPT), message(submit("toolu_2"))])

    outcome = investigator(model).start(finding_text(finding()))

    assert outcome.status is Status.COMPLETED
    rejection = model.tool_results(1)["toolu_1"]["content"]
    assert "kind 'scan'" in rejection
    assert "cite at least one log, history, commit or file result" in rejection


def test_invented_quotes_are_sent_back_then_fixed() -> None:
    model = ScriptedModel(
        [
            message(EXCERPT),
            message(submit("toolu_2", "an invented line")),
            message(submit("toolu_3")),
        ]
    )

    outcome = investigator(model).start("finding")

    assert outcome.status is Status.COMPLETED
    rejection = model.tool_results(2)["toolu_2"]
    assert rejection["is_error"] is True
    assert "not in the result of toolu_1" in rejection["content"]


def test_repeated_bad_verdicts_end_without_one() -> None:
    bad = {"classification": "maybe"}
    model = ScriptedModel([message(call(f"toolu_{n}", "submit_verdict", bad)) for n in range(3)])

    outcome = investigator(model).start("finding")

    assert outcome.status is Status.NO_VERDICT
    assert "does not match the schema" in outcome.detail


def test_a_model_that_stops_talking_is_nudged_once() -> None:
    model = ScriptedModel([message(text("I think it is flaky.")), message(text("Done."))])

    outcome = investigator(model).start("finding")

    assert outcome.status is Status.NO_VERDICT
    assert model.requests[1]["messages"][-1]["content"].startswith("Continue the investigation")


def test_the_same_call_twice_in_a_row_stops_the_loop() -> None:
    model = ScriptedModel(
        [message(EXCERPT), message(call("toolu_2", "failure_excerpt", {"job_id": 11}))]
    )

    outcome = investigator(model).start("finding")

    assert outcome.status is Status.LOOP


def test_rounds_limit_stops_with_a_reason() -> None:
    model = ScriptedModel([message(EXCERPT), message(call("toolu_2", "run_history", {"limit": 5}))])

    outcome = investigator(model, limits=Limits(rounds=2)).start("finding")

    assert outcome.status is Status.BUDGET
    assert outcome.detail == "Stopped at the limit of 2 rounds."


def test_model_errors_are_reported() -> None:
    outcome = investigator(ScriptedModel([529])).start("finding")

    assert outcome.status is Status.MODEL_ERROR


def test_unknown_tools_failing_tools_and_the_gate_answer_with_errors() -> None:
    write_tool = Tool("rerun", "Rerun a job.", RiskLevel.WRITE, Nothing, lambda _: "done")
    model = ScriptedModel(
        [
            message(
                call("toolu_1", "teleport", {}),
                call("toolu_2", "rerun", {}),
                call("toolu_3", "failure_excerpt", {"job_id": 999}),
            ),
            message(submit("toolu_4", "Runs with a proven flaky event", "finding")),
        ]
    )

    investigator(model, extra=[write_tool]).start(finding_text(finding()))

    results = model.tool_results(1)
    assert results["toolu_1"]["content"] == "There is no tool named teleport."
    assert results["toolu_2"]["content"] == "rerun is not permitted in this mode."
    assert "not a job of this workflow" in results["toolu_3"]["content"]
    assert all(result["is_error"] for result in results.values())


def test_revise_continues_the_conversation_with_the_questions() -> None:
    model = ScriptedModel([message(EXCERPT, submit("toolu_2")), message(submit("toolu_3"))])
    agent = investigator(model, settings=ModelSettings(model="m-1", thinking="enabled"))
    agent.start("finding")

    outcome = agent.revise(["Which commit changed the test?"])

    assert outcome.status is Status.COMPLETED
    results = model.tool_results(1)
    assert QUOTE in results["toolu_1"]["content"]
    assert "Which commit changed the test?" in results["toolu_2"]["content"]
    assert model.requests[0]["thinking"] == {"type": "enabled", "budget_tokens": 8_000}


def test_thinking_can_be_switched_off() -> None:
    model = ScriptedModel([message(submit("toolu_1", "proven flaky", "finding"))])

    investigator(model, settings=ModelSettings(model="m-1", thinking="off")).start(
        finding_text(finding())
    )

    assert "thinking" not in model.requests[0]
