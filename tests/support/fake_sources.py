from dataclasses import dataclass, field

from flakipype.flaky.findings import Evidence, Finding, FindingKind
from flakipype.flaky.model import AttemptRef
from flakipype.flaky.scoring import FlakyKey
from flakipype.github.contents import ChangedFile, Commit, Comparison

from support.builders import START, job, run

APP = "octo-org/app"
LOG = (
    "2026-10-07T09:27:00Z ##[group]Run npm test\n"
    "2026-10-07T09:27:35Z ##[error]Test timed out after 5000ms\n"
    "    at waitForRows (tests/e2e/scan.spec.ts:80:7)\n"
)
KEY = FlakyKey(APP, ".github/workflows/ci.yml", "CI", "test", "Run tests")


@dataclass
class FakeLogs:
    logs: dict[int, str | None] = field(default_factory=lambda: {11: LOG})
    calls: list[int] = field(default_factory=list)

    def job_log(self, repository: str, job_id: int) -> str | None:
        assert repository == APP
        self.calls.append(job_id)
        return self.logs.get(job_id)


@dataclass
class FakeContents:
    files: dict[tuple[str, str], str] = field(default_factory=dict)
    comparison: Comparison = field(
        default_factory=lambda: Comparison(
            total_commits=1,
            commits=[Commit("abcdef1234567", "Raise timeout", "dev", START)],
            files=[ChangedFile("tests/e2e/scan.spec.ts", "modified", 1, 1, "@@ -1 +1 @@\n-a\n+b")],
        )
    )

    def compare(self, repository: str, base: str, head: str) -> Comparison:
        assert (repository, base, head) == (APP, base, head)
        return self.comparison

    def file_content(self, repository: str, path: str, ref: str) -> str | None:
        assert repository == APP
        return self.files.get((path, ref))


def finding(number: int = 1) -> Finding:
    return Finding(
        number=number,
        kind=FindingKind.FLAKY,
        key=KEY,
        facts=("Status: flaky", "Runs with a proven flaky event: 2 of 10 finished runs"),
        job_ids=(11,),
        last_seen=START,
    )


def evidence() -> Evidence:
    runs = [run(1, attempt=2), run(2), run(3, conclusion="failure", sha="3" * 40)]
    jobs = {
        AttemptRef(1, 1): [job(11, run_id=1)],
        AttemptRef(1, 2): [job(12, run_id=1, attempt=2, conclusion="success")],
        AttemptRef(3, 1): [job(31, run_id=3)],
    }
    return Evidence(runs=runs, jobs=jobs, signatures={})
