from dataclasses import replace

import pytest

from flakipype.agent.verdict import Verdict
from flakipype.agent.workcopy import FileChange
from flakipype.fix.texts import (
    PullRequestFacts,
    Rate,
    VerificationFacts,
    branch_name,
    commit_body,
    failure_rate,
    finding_marker,
    pull_request_body,
    rate_text,
    verification_text,
)
from flakipype.flaky.findings import Evidence

from support.builders import run
from support.fake_anthropic import verdict_input
from support.fake_runs import E2E, e2e_evidence, e2e_finding

CHANGE = FileChange("tests/e2e/scan.spec.ts", "wait(500)\n", "waitForRows()\n")
RATE = Rate(failed=4, total=31, branch="main")


def test_the_branch_name_comes_from_the_workflow_and_the_diff() -> None:
    name = branch_name(e2e_finding(), [CHANGE])
    other = branch_name(e2e_finding(), [replace(CHANGE, after="other()\n")])

    assert name.startswith("flakipype/fix-e2e-")
    assert len(name) == len("flakipype/fix-e2e-") + 6
    assert name != other


def test_a_workflow_name_without_letters_still_gives_a_branch_name() -> None:
    finding = e2e_finding()
    odd = replace(finding, key=replace(finding.key, workflow_path=".github/workflows/__.yml"))

    assert branch_name(odd, [CHANGE]).startswith("flakipype/fix-workflow-")


def test_the_marker_is_stable_and_hides_the_identity() -> None:
    marker = finding_marker(e2e_finding())

    assert marker == finding_marker(e2e_finding(number=7))
    assert marker.startswith("<!-- flakipype:finding=")
    assert "octo-org" not in marker
    assert marker != finding_marker(e2e_finding(repository="octo-org/other"))


def test_the_failure_rate_on_the_default_branch() -> None:
    assert failure_rate(e2e_finding(), e2e_evidence(), "main") == Rate(2, 3, "main")


def test_the_failure_rate_falls_back_to_all_branches() -> None:
    evidence = e2e_evidence()
    unfinished = run(6, conclusion=None, workflow=E2E, name="E2E")
    other_workflow = run(7, name="CI")
    evidence = Evidence([*evidence.runs, unfinished, other_workflow], evidence.jobs)

    assert failure_rate(e2e_finding(), evidence, "develop") == Rate(2, 3, "all branches")


def test_rate_texts() -> None:
    assert rate_text(RATE, "E2E") == "On main, E2E failed 4 of 31 runs (13%)"
    assert rate_text(Rate(1, 3, "all branches"), "E2E") == (
        "On all branches, E2E failed 1 of 3 runs (33%)"
    )
    assert rate_text(Rate(0, 0, "main"), "E2E") == ""


def test_the_chance_of_passes_without_a_fix() -> None:
    assert RATE.chance_of_passes(3) == pytest.approx((27 / 31) ** 3)


def facts(rate: Rate = RATE, warnings: tuple[str, ...] = ()) -> PullRequestFacts:
    verdict = Verdict.model_validate(verdict_input("timed out", "toolu_9"))
    return PullRequestFacts(e2e_finding(), verdict, rate, warnings, verify_runs=3)


def test_the_pull_request_body() -> None:
    body = pull_request_body(facts(), "Waits for the rows.")

    assert body.startswith(finding_marker(e2e_finding()) + "\n## Flaky: e2e in octo-org/app\n")
    assert "**Scan facts:** On main, E2E failed 4 of 31 runs (13%) in the scanned window." in body
    assert "- Status: flaky" in body
    assert (
        "**Verdict** (model's assessment, reviewed): flaky_test, high confidence. "
        "The E2E test waits on a fixed timeout."
    ) in body
    assert "### The change (written by the model)\n\nWaits for the rows.\n" in body
    assert "### Warnings\n\nnone\n" in body
    assert "Pending: flakipype reruns E2E on this branch 3 times." in body
    assert body.endswith("Opened by flakipype as a draft. Merging is up to you.\n")


def test_the_pull_request_body_without_a_rate_and_with_warnings() -> None:
    body = pull_request_body(facts(Rate(0, 0, "main"), ("changes .github/: x",)), "Text.")

    assert "**Scan facts:** see below." in body
    assert "### Warnings\n\n- changes .github/: x\n" in body


def test_the_commit_body_has_the_trailer() -> None:
    assert commit_body("Waits.") == "Waits.\n\nGenerated-by: flakipype"


def verification(results: tuple[str, ...], rate: Rate = RATE, stopped: str = "") -> str:
    return verification_text(VerificationFacts("E2E", results, 3, rate, stopped))


def test_all_runs_passed_with_the_chance() -> None:
    assert verification(("passed",) * 3) == (
        "flakipype verification: E2E passed 3 of 3 runs on this branch.\n"
        "On main, E2E failed 4 of 31 runs (13%) in the scanned window.\n"
        "Three passes in a row would also happen by chance 66% of the time without a fix, "
        "so this is a first signal, not proof."
    )


def test_one_pass_and_many_passes_are_named() -> None:
    assert "One pass would also happen by chance 87%" in verification(("passed",))
    assert "\n6 passes in a row would" in verification(("passed",) * 6)


def test_failures_are_listed_without_a_chance() -> None:
    assert verification(("passed", "failed with another error: x", "passed")) == (
        "flakipype verification: E2E passed 2 of 3 runs on this branch.\n"
        "Run 2 failed with another error: x.\n"
        "On main, E2E failed 4 of 31 runs (13%) in the scanned window."
    )


def test_a_verification_that_stopped_early() -> None:
    text = verification(("passed",), stopped="the action budget of this session is used up")

    assert "Stopped after 1 of 3 runs: the action budget of this session is used up." in text


def test_a_verification_without_a_rate() -> None:
    assert verification(("passed",) * 3, Rate(0, 0, "main")) == (
        "flakipype verification: E2E passed 3 of 3 runs on this branch."
    )
