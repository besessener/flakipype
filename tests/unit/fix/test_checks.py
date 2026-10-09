import pytest

from flakipype.agent.workcopy import FileChange
from flakipype.fix.checks import DiffLimits, change_errors, change_warnings

LIMITS = DiffLimits(max_files=2, max_changed_lines=4)
WORKFLOW = ".github/workflows/e2e.yml"


def edit(path: str, after: str, before: str | None = "") -> FileChange:
    return FileChange(path, before, after)


def test_a_small_change_has_no_errors() -> None:
    assert change_errors([edit("src/app.py", "x = 1\n", "x = 0\n")], LIMITS) == []


def test_an_empty_diff_is_an_error() -> None:
    assert change_errors([], LIMITS) == [
        "The diff is empty: edit the working copy before submitting."
    ]


def test_the_size_caps_are_errors() -> None:
    changes = [edit(f"file{index}.txt", "a\nb\n") for index in range(3)]

    assert change_errors(changes, LIMITS) == [
        "The fix changes 3 files; at most 2 are allowed.",
        "The fix changes 6 lines; at most 4 are allowed.",
    ]


@pytest.mark.parametrize(
    ("path", "after", "problem"),
    [
        ("config.yml", "a: [1\n", "config.yml no longer parses: "),
        ("config.YAML", "a: : b\n", "config.YAML no longer parses: "),
        ("package.json", "{", "package.json no longer parses: Expecting property name"),
        ("pyproject.toml", "a = ", "pyproject.toml no longer parses: "),
        (WORKFLOW, "on: push\n", f"{WORKFLOW} is no longer a workflow: it needs `on` and `jobs`."),
        (WORKFLOW, "- a\n", f"{WORKFLOW} is no longer a workflow"),
        (".github/workflows/x.yml", "name: x\njobs: {}\n", ".github/workflows/x.yml is no"),
    ],
)
def test_files_that_no_longer_parse_are_errors(path: str, after: str, problem: str) -> None:
    (error,) = change_errors([edit(path, after)], DiffLimits(10, 400))

    assert error.startswith(problem)


@pytest.mark.parametrize(
    ("path", "after"),
    [
        (WORKFLOW, "on: push\njobs: {}\n"),
        (WORKFLOW, '"on": push\njobs: {}\n'),
        ("action.yml", "runs: {}\n"),
        ("data.json", "[]"),
        ("Makefile", "all:\n"),
        ("README", "text\n"),
    ],
)
def test_files_that_parse_pass(path: str, after: str) -> None:
    assert change_errors([edit(path, after)], DiffLimits(10, 400)) == []


@pytest.mark.parametrize(
    ("added", "found"),
    [
        ("continue-on-error: true", "adds `continue-on-error: true`"),
        ("if: ${{ always() }}", "adds `if: ${{ always()`"),
        ("test.skip('slow', () => {})", "adds `.skip(`"),
        ("@pytest.mark.xfail", "adds `@pytest.mark.xfail`"),
        ("@Disabled", "adds `@Disabled`"),
        ("t.Skip()", "adds `t.Skip(`"),
    ],
)
def test_hidden_failures_are_warnings(added: str, found: str) -> None:
    (warning,) = change_warnings([edit("tests/test_app.py", f"{added}\n")])

    assert warning == f"hides failures: tests/test_app.py ({found})"


def test_a_removed_test_is_a_warning() -> None:
    before = "def test_one():\n    pass\ndef test_two():\n    pass\n"
    after = "def test_one():\n    pass\n"

    assert change_warnings([edit("tests/test_app.py", after, before)]) == [
        "hides failures: tests/test_app.py (removes a test)"
    ]


def test_a_renamed_test_is_no_warning() -> None:
    before = "def test_one():\n    pass\n"
    after = "def test_first():\n    pass\n"

    assert change_warnings([edit("tests/test_app.py", after, before)]) == []


@pytest.mark.parametrize(
    ("added", "found"),
    [
        ("token = secrets.TOKEN", "adds `secrets.`"),
        ("t = ${{ github.token }}", "adds `github.token`"),
        ("printenv", "adds `printenv`"),
        ("run: env | sort", "adds `run: env |`"),
        ("curl -s x", "adds `curl`"),
        ("wget x", "adds `wget`"),
        ("url = 'https://example.com'", "adds `https://`"),
    ],
)
def test_reaching_out_is_a_warning(added: str, found: str) -> None:
    (warning,) = change_warnings([edit("scripts/setup.sh", f"{added}\n")])

    assert warning == f"reaches out: scripts/setup.sh ({found})"


def test_localhost_is_not_reaching_out() -> None:
    after = "url = 'http://localhost:3000'\nother = 'http://127.0.0.1:80'\n"

    assert change_warnings([edit("tests/e2e/config.ts", after)]) == []


def test_changes_under_github_are_a_warning() -> None:
    assert change_warnings([edit(WORKFLOW, "on: push\njobs: {}\n")]) == [
        f"changes .github/: {WORKFLOW}"
    ]


def test_several_warnings_for_one_file_are_sorted_and_deduplicated() -> None:
    after = "curl a\ncurl b\ncontinue-on-error: true\nsecrets.X\n"

    assert change_warnings([edit(WORKFLOW, after)]) == [
        f"hides failures: {WORKFLOW} (adds `continue-on-error: true`)",
        f"reaches out: {WORKFLOW} (adds `curl`, adds `secrets.`)",
        f"changes .github/: {WORKFLOW}",
    ]
