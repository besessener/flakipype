"""An in-memory repository at one commit: files as bytes, records what was read."""

from dataclasses import dataclass, field

from flakipype.github.pulls import FileTree

E2E_TEST = "tests/e2e/scan.spec.ts"
TEST_SOURCE = (
    "test('archives', async () => {\n"
    "  await page.waitForTimeout(500);\n"
    "  await expect(rows).toHaveCount(2);\n"
    "});\n"
)
WORKFLOW = ".github/workflows/e2e.yml"
WORKFLOW_SOURCE = "on:\n  pull_request:\n  workflow_dispatch:\njobs:\n  e2e:\n    runs-on: x\n"


def repository_files() -> dict[str, bytes]:
    return {
        E2E_TEST: TEST_SOURCE.encode(),
        WORKFLOW: WORKFLOW_SOURCE.encode(),
        "README.md": b"# app\r\nline two\r\n",
        "logo.png": b"PNG\x00\x01",
        "latin1.txt": "caf\xe9".encode("latin-1"),
    }


@dataclass
class FakeFiles:
    files: dict[str, bytes] = field(default_factory=repository_files)
    truncated: bool = False
    reads: list[str] = field(default_factory=list)
    error: Exception | None = None

    def file_tree(self, repository: str, commit: str) -> FileTree:
        del repository, commit
        if self.error is not None:
            raise self.error
        return FileTree(tuple(sorted(self.files)), self.truncated)

    def file_bytes(self, repository: str, path: str, commit: str) -> bytes | None:
        del repository, commit
        self.reads.append(path)
        if self.error is not None:
            raise self.error
        return self.files.get(path)
