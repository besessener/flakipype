import pytest

from flakipype.actions.targets import check_owner, finding_runs, newest_failed_run, newest_run
from flakipype.agent.tools import ToolError
from flakipype.flaky.findings import Evidence

from support.fake_runs import e2e_evidence, e2e_finding


def test_a_findings_runs_are_those_of_its_jobs_newest_first() -> None:
    runs = finding_runs(e2e_finding(), e2e_evidence())

    assert [run.run_id for run in runs] == [4, 3]


def test_the_newest_failed_run_is_the_default_rerun_target() -> None:
    assert newest_failed_run(e2e_finding(), e2e_evidence(), None).run_id == 4
    assert newest_failed_run(e2e_finding(), e2e_evidence(), 3).run_id == 3


def test_without_a_failing_run_the_error_names_the_alternatives() -> None:
    with pytest.raises(ToolError, match=r"no run that is still failing \(runs: 4, 3\)"):
        newest_failed_run(e2e_finding(), e2e_evidence(newest="success"), None)


def test_only_the_findings_runs_can_be_named() -> None:
    with pytest.raises(ToolError, match="Run 5 is not one of finding #2's runs: 4, 3"):
        newest_run(e2e_finding(), e2e_evidence(), 5)


def test_the_newest_run_of_any_result() -> None:
    assert newest_run(e2e_finding(), e2e_evidence(newest="success"), None).run_id == 4
    assert newest_run(e2e_finding(), e2e_evidence(), 3).run_id == 3
    with pytest.raises(ToolError, match="no runs in this scan"):
        newest_run(e2e_finding(), Evidence(), None)
    with pytest.raises(ToolError, match="runs: none"):
        newest_run(e2e_finding(), Evidence(), 4)


def test_only_the_configured_owner() -> None:
    check_owner("Octo-Org/app", "octo-org")
    with pytest.raises(ToolError, match="does not belong to the configured owner octo-org"):
        check_owner("other/app", "octo-org")
