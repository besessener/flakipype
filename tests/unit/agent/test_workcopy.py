import pytest

from flakipype.agent.fix_tools import FixTools
from flakipype.agent.tools import Mode, PolicyGate, ToolError, deny_all
from flakipype.agent.workcopy import FileChange, WorkingCopy, normal_path, unified_diff
from flakipype.github.actions import GitHubApiError

from support.fake_files import E2E_TEST, FakeFiles

GATE = PolicyGate(Mode.ASK, deny_all)


def working_copy(files: FakeFiles | None = None) -> WorkingCopy:
    return WorkingCopy(files or FakeFiles(), "octo-org/app", "3f2a9c1")


def tools(copy: WorkingCopy) -> dict[str, object]:
    return {tool.name: tool for tool in FixTools(copy).tools()}


def use(copy: WorkingCopy, name: str, **arguments: object) -> str:
    (tool,) = [tool for tool in FixTools(copy).tools() if tool.name == name]
    return tool.invoke(arguments, GATE)


@pytest.mark.parametrize(
    ("given", "normal"),
    [("src/a.py", "src/a.py"), ("./src//a.py", "src/a.py"), ("src\\a.py", "src/a.py")],
)
def test_paths_are_normalised(given: str, normal: str) -> None:
    assert normal_path(given) == normal


@pytest.mark.parametrize("given", ["", "/etc/passwd", "../x", "a/../../x", ".git/config", " . "])
def test_paths_outside_the_repository_are_refused(given: str) -> None:
    with pytest.raises(ToolError, match="not a file path inside the repository"):
        normal_path(given)


def test_replace_edits_one_unique_occurrence() -> None:
    copy = working_copy()

    copy.replace(E2E_TEST, "  await page.waitForTimeout(500);\n", "")

    (change,) = copy.changes()
    assert change.path == E2E_TEST
    assert change.removed == ["  await page.waitForTimeout(500);"]
    assert change.added == []
    assert "waitForTimeout" not in (copy.read(E2E_TEST) or "")


@pytest.mark.parametrize(("old", "reason"), [("nowhere", "not found"), ("await", "found 2 times")])
def test_ambiguous_or_missing_text_is_refused(old: str, reason: str) -> None:
    with pytest.raises(ToolError, match=reason):
        working_copy().replace(E2E_TEST, old, "x")


def test_edits_keep_the_files_line_endings() -> None:
    copy = working_copy()

    copy.replace("README.md", "line two\n", "line 2\nline 3\n")
    copy.write("NEW.md", "a\r\nb\n")

    assert copy.read("README.md") == "# app\r\nline 2\r\nline 3\r\n"
    assert copy.read("NEW.md") == "a\nb\n"
    new, readme = sorted(copy.changes(), key=lambda change: change.path)
    assert (readme.added, readme.removed) == (["line 2", "line 3"], ["line two"])
    assert new.before is None
    assert new.diff_lines()[:2] == ["--- /dev/null", "+++ b/NEW.md"]


def test_unchanged_edits_are_no_changes() -> None:
    copy = working_copy()
    original = copy.read(E2E_TEST) or ""

    copy.write(E2E_TEST, original)

    assert copy.changes() == []


@pytest.mark.parametrize(("path", "reason"), [("logo.png", "binary"), ("latin1.txt", "UTF-8")])
def test_binary_and_non_utf8_files_cannot_be_edited(path: str, reason: str) -> None:
    with pytest.raises(ToolError, match=reason):
        working_copy().read(path)


def test_replacing_in_a_missing_file_points_to_write_file() -> None:
    with pytest.raises(ToolError, match="write_file creates new files"):
        working_copy().replace("missing.txt", "a", "b")


def test_github_errors_become_tool_errors() -> None:
    copy = working_copy(FakeFiles(error=GitHubApiError("boom")))

    with pytest.raises(ToolError, match="GitHub refused: boom"):
        copy.read(E2E_TEST)
    with pytest.raises(ToolError, match="GitHub refused: boom"):
        copy.tree()


def test_an_earlier_proposal_is_the_starting_point() -> None:
    earlier = FileChange(E2E_TEST, "old\n", "new\n")
    files = FakeFiles()
    copy = working_copy(files)

    copy.apply([earlier])

    assert copy.read(E2E_TEST) == "new\n"
    assert copy.changes() == [earlier]
    assert files.reads == []
    assert unified_diff([earlier]).splitlines()[-2:] == ["-old", "+new"]


def test_list_files_shows_directories_and_new_files() -> None:
    files = FakeFiles(truncated=True)
    copy = working_copy(files)
    copy.write("tests/e2e/helpers.ts", "x\n")

    root = use(copy, "list_files")
    e2e = use(copy, "list_files", path="tests/e2e")

    assert ".github/\n" in root
    assert "README.md" in root
    assert "[GitHub listed only part of this large repository]" in root
    assert "helpers.ts\nscan.spec.ts" in e2e
    with pytest.raises(ToolError, match="not a directory"):
        use(copy, "list_files", path="nowhere")


def test_list_files_caps_long_listings() -> None:
    files = FakeFiles(files={f"f{index:03}.txt": b"" for index in range(310)})

    listed = use(working_copy(files), "list_files", path=".")

    assert "f299.txt\n[… 10 more …]" in listed


def test_read_file_shows_the_edited_version_numbered() -> None:
    copy = working_copy()
    use(copy, "replace_in_file", path=E2E_TEST, old="(500)", new="(0)")

    text = use(copy, "read_file", path=E2E_TEST, from_line=2, to_line=2)

    assert "    2   await page.waitForTimeout(0);" in text
    assert 'ref="working copy"' in text
    assert 'lines="2-2 of 4"' in text
    with pytest.raises(ToolError, match="does not exist in the working copy"):
        use(copy, "read_file", path="missing.txt")


def test_edit_tools_report_the_size_and_show_the_diff() -> None:
    copy = working_copy()

    assert use(copy, "show_diff").count("no changes yet") == 1
    replaced = use(copy, "replace_in_file", path=E2E_TEST, old="(500)", new="(0)")
    written = use(copy, "write_file", path="NOTES.md", content="one\n")

    assert replaced.endswith("now changes 1 files, 2 lines.")
    assert written == "Wrote NOTES.md. The working copy now changes 2 files, 3 lines."
    assert "+  await page.waitForTimeout(0);" in use(copy, "show_diff")
    assert set(tools(copy)) == {
        "list_files", "read_file", "replace_in_file", "write_file", "show_diff",
    }  # fmt: skip
