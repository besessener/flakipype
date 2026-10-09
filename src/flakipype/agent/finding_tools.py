"""The read-only tools an investigator gets for one finding, limited to its repository."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, Field

from flakipype.agent.prompts import data_block
from flakipype.agent.tools import RiskLevel, Tool, ToolError
from flakipype.flaky.excerpt import failure_excerpt, log_range
from flakipype.flaky.findings import Evidence, Finding
from flakipype.flaky.model import JobResult, WorkflowRun
from flakipype.github.actions import GitHubApiError
from flakipype.github.contents import Comparison

_MAX_COMMITS = 50
_MAX_FILES = 100
_MAX_DIFF_LINES = 300
_MAX_FILE_LINES = 400


class LogSource(Protocol):
    def job_log(self, repository: str, job_id: int) -> str | None: ...


class ContentsSource(Protocol):
    def compare(self, repository: str, base: str, head: str) -> Comparison: ...

    def file_content(self, repository: str, path: str, ref: str) -> str | None: ...


class JobInput(BaseModel):
    job_id: int


class LogRangeInput(BaseModel):
    job_id: int
    from_line: int = Field(ge=1)
    to_line: int = Field(ge=1)


class HistoryInput(BaseModel):
    limit: int = Field(default=30, ge=1, le=100)


class CompareInput(BaseModel):
    base: str = Field(description="commit sha or branch of the older run")
    head: str = Field(description="commit sha or branch of the newer run")


class FileDiffInput(CompareInput):
    path: str


class ReadFileInput(BaseModel):
    path: str
    ref: str = Field(description="commit sha or branch")
    from_line: int = Field(default=1, ge=1)


class WorkflowInput(BaseModel):
    ref: str = Field(description="commit sha or branch")


@dataclass
class FindingTools:
    finding: Finding
    evidence: Evidence
    logs: LogSource
    contents: ContentsSource
    excerpt_lines: int = 120
    _log_cache: dict[int, str] = field(default_factory=dict)

    @property
    def repository(self) -> str:
        return self.finding.key.repository

    def tools(self) -> list[Tool]:
        read = RiskLevel.READ
        return [
            Tool("failure_excerpt", "Errors of the failed step with context, from a job log.",
                 read, JobInput, self._failure_excerpt),
            Tool("log_range", "Raw numbered lines of a job log, at most 200.",
                 read, LogRangeInput, self._log_range),
            Tool("run_history", "Runs of this workflow, newest first, with failed jobs and errors.",
                 read, HistoryInput, self._run_history),
            Tool("compare_commits", "Commits and changed files between two refs (no diff).",
                 read, CompareInput, self._compare),
            Tool("file_diff", "Unified diff of one file between two refs.",
                 read, FileDiffInput, self._file_diff),
            Tool("read_file", "File content at a ref, numbered, 400 lines from from_line.",
                 read, ReadFileInput, self._read_file),
            Tool("workflow_file", "The workflow file of this finding at a ref.",
                 read, WorkflowInput, self._workflow_file),
        ]  # fmt: skip

    def _known_jobs(self) -> dict[int, tuple[WorkflowRun, JobResult]]:
        runs = {run.run_id: run for run in self._workflow_runs()}
        return {
            job.job_id: (runs[ref.run_id], job)
            for ref, jobs in self.evidence.jobs.items()
            if ref.run_id in runs
            for job in jobs
        }

    def _workflow_runs(self) -> list[WorkflowRun]:
        key = self.finding.key
        runs = [
            run
            for run in self.evidence.runs
            if run.repository == key.repository and run.workflow_path == key.workflow_path
        ]
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    def _log(self, job_id: int) -> tuple[JobResult, str]:
        known = self._known_jobs()
        if job_id not in known:
            message = f"job {job_id} is not a job of this workflow known to the scan"
            raise ToolError(message)
        if job_id not in self._log_cache:
            log = _github(lambda: self.logs.job_log(self.repository, job_id))
            if log is None:
                message = f"the log of job {job_id} is no longer available on GitHub"
                raise ToolError(message)
            self._log_cache[job_id] = log
        return known[job_id][1], self._log_cache[job_id]

    def _failure_excerpt(self, given: JobInput) -> str:
        job, log = self._log(given.job_id)
        excerpt = failure_excerpt(log, self.excerpt_lines)
        return data_block(
            "log", excerpt.text, job=str(job.job_id), job_name=job.name,
            step=excerpt.step_header or job.failed_step,
            lines=f"{excerpt.first_line}-{excerpt.last_line} of {excerpt.total_lines}",
        )  # fmt: skip

    def _log_range(self, given: LogRangeInput) -> str:
        job, log = self._log(given.job_id)
        text = log_range(log, given.from_line, given.to_line)
        return data_block("log", text, job=str(job.job_id), job_name=job.name)

    def _run_history(self, given: HistoryInput) -> str:
        failed_jobs: dict[int, list[str]] = {}
        for ref, jobs in self.evidence.jobs.items():
            for job in jobs:
                if job.failed:
                    failed_jobs.setdefault(ref.run_id, []).append(self._describe_job(job))
        lines = [
            f"{run.created_at:%Y-%m-%d %H:%M} run {run.run_id} attempt {run.attempt} "
            f"{run.event} {run.head_branch} {run.head_sha[:10]}: {run.conclusion or 'running'}"
            + "".join(f"\n    failed {entry}" for entry in failed_jobs.get(run.run_id, []))
            for run in self._workflow_runs()[: given.limit]
        ]
        return data_block(
            "history", "\n".join(lines) or "no runs", workflow=self.finding.key.workflow_path
        )

    def _describe_job(self, job: JobResult) -> str:
        signature = self.evidence.signatures.get(job.job_id)
        error = f" — {signature.category.value}: {signature.message}" if signature else ""
        return f"attempt {job.attempt} job {job.job_id} {job.name} ({job.failed_step}){error}"

    def _compare(self, given: CompareInput) -> str:
        comparison = _github(lambda: self.contents.compare(self.repository, given.base, given.head))
        commits = [
            f"{c.sha[:10]} {c.date:%Y-%m-%d} {c.author}: {c.subject}" if c.date else
            f"{c.sha[:10]} {c.author}: {c.subject}"
            for c in comparison.commits[-_MAX_COMMITS:]
        ]  # fmt: skip
        files = [
            f"{f.status:<9} +{f.additions} -{f.deletions} {f.path}"
            for f in comparison.files[:_MAX_FILES]
        ]
        text = (
            f"{comparison.total_commits} commits (newest {len(commits)} shown):\n"
            + "\n".join(commits)
            + f"\n\n{len(comparison.files)} changed files:\n"
            + "\n".join(files)
        )
        return data_block("commits", text, base=given.base, head=given.head)

    def _file_diff(self, given: FileDiffInput) -> str:
        comparison = _github(lambda: self.contents.compare(self.repository, given.base, given.head))
        match = next((f for f in comparison.files if f.path == given.path), None)
        if match is None:
            message = f"{given.path} did not change between {given.base} and {given.head}"
            raise ToolError(message)
        lines = match.patch.splitlines() or ["(no textual diff, e.g. a binary file)"]
        if len(lines) > _MAX_DIFF_LINES:
            lines = [*lines[:_MAX_DIFF_LINES], f"[… {len(lines) - _MAX_DIFF_LINES} more lines …]"]
        return data_block(
            "diff", "\n".join(lines), path=given.path, base=given.base, head=given.head
        )

    def _read_file(self, given: ReadFileInput) -> str:
        return self._file(given.path, given.ref, given.from_line)

    def _workflow_file(self, given: WorkflowInput) -> str:
        return self._file(self.finding.key.workflow_path, given.ref, 1)

    def _file(self, path: str, ref: str, from_line: int) -> str:
        content = _github(lambda: self.contents.file_content(self.repository, path, ref))
        if content is None:
            message = f"{path} does not exist at {ref}"
            raise ToolError(message)
        lines = content.splitlines()
        shown = lines[from_line - 1 : from_line - 1 + _MAX_FILE_LINES]
        numbered = "\n".join(
            f"{number:>5} {text}" for number, text in enumerate(shown, start=from_line)
        )
        return data_block(
            "file",
            numbered,
            path=path,
            ref=ref,
            lines=f"{from_line}-{from_line + len(shown) - 1} of {len(lines)}",
        )


def _github[Result](call: Callable[[], Result]) -> Result:
    try:
        return call()
    except GitHubApiError as error:
        message = f"GitHub refused: {error}"
        raise ToolError(message) from error
