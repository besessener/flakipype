"""What an action may point at: only runs and workflows of the current scan's findings."""

from flakipype.agent.tools import ToolError
from flakipype.flaky.findings import Evidence, Finding
from flakipype.flaky.model import WorkflowRun


def finding_runs(finding: Finding, evidence: Evidence) -> list[WorkflowRun]:
    """The runs the finding's jobs belong to, newest first."""
    wanted = set(finding.job_ids)
    run_ids = {
        job.run_id for jobs in evidence.jobs.values() for job in jobs if job.job_id in wanted
    }
    runs = [run for run in evidence.runs if run.run_id in run_ids]
    return sorted(runs, key=lambda run: run.created_at, reverse=True)


def newest_failed_run(finding: Finding, evidence: Evidence, run_id: int | None) -> WorkflowRun:
    runs = finding_runs(finding, evidence)
    if run_id is not None:
        return _named_run(finding, runs, run_id)
    failed = [run for run in runs if run.failed]
    if not failed:
        message = (
            f"Finding #{finding.number} has no run that is still failing "
            f"(runs: {_ids(runs)}); rerun_run reruns a passed one, dispatch starts a new one."
        )
        raise ToolError(message)
    return failed[0]


def newest_run(finding: Finding, evidence: Evidence, run_id: int | None) -> WorkflowRun:
    runs = finding_runs(finding, evidence)
    if run_id is not None:
        return _named_run(finding, runs, run_id)
    if not runs:
        message = f"Finding #{finding.number} has no runs in this scan."
        raise ToolError(message)
    return runs[0]


def check_owner(repository: str, owner: str) -> None:
    if repository.split("/", 1)[0].lower() != owner.lower():
        message = f"{repository} does not belong to the configured owner {owner}."
        raise ToolError(message)


def _named_run(finding: Finding, runs: list[WorkflowRun], run_id: int) -> WorkflowRun:
    for run in runs:
        if run.run_id == run_id:
            return run
    message = f"Run {run_id} is not one of finding #{finding.number}'s runs: {_ids(runs)}."
    raise ToolError(message)


def _ids(runs: list[WorkflowRun]) -> str:
    return ", ".join(str(run.run_id) for run in runs) or "none"
