import pytest

from flakipype.agent.workcopy import FileChange
from flakipype.fix.checks import DiffLimits, change_errors, change_warnings, executable_paths

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


def test_a_masked_placeholder_written_back_is_an_error() -> None:
    before = "token = [masked: secret]\nx = 1\n"
    kept = edit("tests/test_login.py", "token = [masked: secret]\nx = 2\n", before)
    added = edit("tests/test_login.py", "token = [masked: secret]\nx = 1\n", "token = t()\n")

    assert change_errors([kept], LIMITS) == []
    (error,) = change_errors([added], LIMITS)
    assert error.startswith("tests/test_login.py adds `[masked: ...]`: masked lines hide")


@pytest.mark.parametrize(
    ("path", "after", "problem"),
    [
        ("config.yml", "a: [1\n", "config.yml no longer parses: "),
        ("config.YAML", "a: : b\n", "config.YAML no longer parses: "),
        ("package.json", "{", "package.json no longer parses: Expecting property name"),
        ("pyproject.toml", "a = ", "pyproject.toml no longer parses: "),
        ("config.yml", "a: !!bool on1\n", "config.yml no longer parses: 'on1'"),
        ("config.yml", "a: !!timestamp never\n", "config.yml no longer parses: "),
        ("config.yml", "[" * 600, "config.yml no longer parses: it is nested too deeply"),
        ("data.json", "[" * 100_000, "data.json no longer parses: "),
        ("pyproject.toml", "a = " + "[" * 1_000, "pyproject.toml no longer parses: it is nested"),
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
    ("path", "before", "after"),
    [
        ("tsconfig.json", '{\n  // c\n  "a": false\n}', '{\n  // c\n  "a": true\n}'),
        ("deploy/app.yaml", "a: [1\nb: 1\n", "a: [1\nb: 2\n"),
        ("pyproject.toml", "a = \nb = 1\n", "a = \nb = 2\n"),
    ],
)
def test_an_edit_to_a_file_that_did_not_parse_before_is_no_error(
    path: str, before: str, after: str
) -> None:
    assert change_errors([edit(path, after, before)], DiffLimits(10, 400)) == []


@pytest.mark.parametrize(
    ("path", "before", "after"),
    [
        ("appsettings.json", '\ufeff{"timeout": 5}', '\ufeff{"timeout": 30}'),
        ("db.yaml", "kind: Service\n---\nkind: Deployment\nx: 1\n", "kind: Service\n---\nx: 10\n"),
        ("template.yaml", "Name: !Sub '${A}-q'\nT: 5\n", "Name: !Sub '${A}-q'\nT: 30\n"),
        ("mkdocs.yml", "f: !!python/name:m.f\nx: [a, b]\n", "f: !!python/name:m.f\nx: [b]\n"),
        ("k.yml", "a: !Ref {b: 1}\nc: !GetAZs [x]\n", "a: !Ref {b: 2}\nc: !GetAZs [x]\n"),
        (".github/workflows/matrix.json", '{"node": [18, 20]}', '{"node": [20, 22]}'),
        (".github/workflows/config/labels.yml", "a: 1\n", "a: 2\n"),
    ],
)
def test_valid_files_that_are_not_strict_json_or_one_document_pass(
    path: str, before: str, after: str
) -> None:
    assert change_errors([edit(path, after, before)], DiffLimits(10, 400)) == []


@pytest.mark.parametrize(
    ("path", "before", "after", "problem"),
    [
        ("package.json", '{"a": 1}', '{"a": 1,}', "package.json no longer parses: "),
        ("new.json", None, "{", "new.json no longer parses: "),
        ("db.yaml", "a: 1\n---\nb: 2\n", "a: 1\n---\nb: [\n", "db.yaml no longer parses: "),
        (WORKFLOW, "on: push\njobs: {}\n", "on: push\njobs: {}\n---\na: 1\n", f"{WORKFLOW} is no"),
        (
            ".github/workflows/E2E.YML",
            "on: push\njobs: {}\n",
            "on: push\n",
            ".github/workflows/E2E",
        ),
    ],
)
def test_an_edit_that_breaks_a_file_is_still_an_error(
    path: str, before: str | None, after: str, problem: str
) -> None:
    (error,) = change_errors([edit(path, after, before)], DiffLimits(10, 400))

    assert error.startswith(problem)


@pytest.mark.parametrize(
    ("added", "found"),
    [
        ("continue-on-error: true", "adds `continue-on-error: true`"),
        ("if: ${{ always() }}", "adds `if: ${{ always()`"),
        ("test.skip('slow', () => {})", "adds `test.skip(`"),
        ("  it.only('x', () => {})", "adds `it.only(`"),
        ("test.describe.skip('suite', () => {})", "adds `test.describe.skip(`"),
        ("this.skip()", "adds `this.skip(`"),
        ("@pytest.mark.xfail", "adds `pytest.mark.xfail`"),
        ("@pytest.mark.skipif(True, reason='x')", "adds `pytest.mark.skip`"),
        ("pytestmark = [pytest.mark.xfail(strict=False)]", "adds `pytest.mark.xfail`"),
        ("pytestmark = pytest.mark.skip", "adds `pytest.mark.skip`"),
        ("pytest.param(1, marks=pytest.mark.xfail)", "adds `pytest.mark.xfail`"),
        ("pytest.skip('flaky')", "adds `pytest.skip(`"),
        ("pytest.xfail('flaky')", "adds `pytest.xfail(`"),
        ("self.skipTest('flaky')", "adds `.skipTest(`"),
        ("raise unittest.SkipTest('flaky')", "adds `SkipTest`"),
        ("@unittest.skip('flaky')", "adds `@unittest.skip`"),
        ("@Disabled", "adds `@Disabled`"),
        ("t.Skip()", "adds `t.Skip(`"),
    ],
)
def test_hidden_failures_are_warnings(added: str, found: str) -> None:
    (warning,) = change_warnings([edit("tests/test_app.py", f"{added}\n")])

    assert warning == f"hides failures: tests/test_app.py ({found})"


@pytest.mark.parametrize("removed", ["def test_two():", "async def test_two():"])
def test_a_removed_test_is_a_warning(removed: str) -> None:
    before = f"def test_one():\n    pass\n{removed}\n    pass\n"
    after = "def test_one():\n    pass\n"

    assert change_warnings([edit("tests/test_app.py", after, before)]) == [
        "hides failures: tests/test_app.py (removes a test)"
    ]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("test('uploads', async t => {", "test.serial('uploads', async t => {"),
        ("it('uploads', () => {", "it.sequential('uploads', () => {"),
        ("def test_uploads():", "async def test_uploads():"),
    ],
)
def test_a_test_changed_to_its_serial_or_async_form_is_no_warning(before: str, after: str) -> None:
    change = edit("tests/test_app.py", f"{after}\n    pass\n", f"{before}\n    pass\n")

    assert change_warnings([change]) == []


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("User.find(f).skip(n).limit(s);", "User.find(f).sort({ _id: 1 }).skip(n).limit(s);"),
        ('Item.objects.only("id")', 'Item.objects.only("id").order_by("id")'),
        ("let rest = lines.iter().skip(1);", "let rest = lines.iter().skip(2);"),
        ("test.skip('slow', () => {})", "test.skip('slow', async () => {})"),
    ],
)
def test_an_edited_line_that_already_had_the_call_is_no_warning(before: str, after: str) -> None:
    assert change_warnings([edit("src/users.js", f"{after}\n", f"{before}\n")]) == []


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


@pytest.mark.parametrize(
    ("added", "found"),
    [
        ("u = 'http://localhost@evil.example/'", "adds `http://localhost@`"),
        ("u = 'http://localhost:1@evil.example/'", "adds `http://localhost:1@`"),
        ("u = 'https://localhost.evil.example/'", "adds `https://`"),
        ("u = 'http://127.0.0.1.nip.io/'", "adds `http://`"),
        ("u = 'HTTPS://example.com'", "adds `HTTPS://`"),
    ],
)
def test_a_host_that_only_starts_like_localhost_is_reaching_out(added: str, found: str) -> None:
    (warning,) = change_warnings([edit("tests/conftest.py", f"{added}\n")])

    assert warning == f"reaches out: tests/conftest.py ({found})"


def test_localhost_is_not_reaching_out() -> None:
    after = (
        "url = 'http://localhost:3000'\nother = 'http://127.0.0.1:80/health'\n"
        'v6 = "http://[::1]:8080"\nbare = http://localhost\n'
    )

    assert change_warnings([edit("tests/e2e/config.ts", after)]) == []


@pytest.mark.parametrize(
    "path", [WORKFLOW, ".github/actions/setup/action.yml", ".github/dependabot.yml"]
)
def test_changes_under_github_are_a_warning(path: str) -> None:
    assert change_warnings([edit(path, "on: push\njobs: {}\n")]) == [f"changes .github/: {path}"]


def test_several_warnings_for_one_file_are_sorted_and_deduplicated() -> None:
    after = "curl a\ncurl b\ncontinue-on-error: true\nsecrets.X\n"

    assert change_warnings([edit(WORKFLOW, after)]) == [
        f"hides failures: {WORKFLOW} (adds `continue-on-error: true`)",
        f"reaches out: {WORKFLOW} (adds `curl`, adds `secrets.`)",
        f"changes .github/: {WORKFLOW}",
    ]


@pytest.mark.parametrize(
    "path",
    ["README.md", "docs/guide/flaky.MD", "CHANGES.rst", "docs/setup.adoc", "notes.markdown"],
)
def test_plain_documentation_does_not_run_as_code(path: str) -> None:
    assert executable_paths([edit(path, "Wait for the rows, not for a fixed time.\n")]) == []


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_scan.py", "conftest.py", "Makefile", "action.yml", "package.json",
        "pyproject.toml", "requirements.txt", "notes.txt", "pytest.ini", "scripts/build",
        "README", "docs/index.html", "CLAUDE.md", "docs/AGENTS.md", ".github/README.md",
        ".claude/notes.md", "tests/fixtures/expected.md", "spec/data/README.md",
    ],
)  # fmt: skip
def test_everything_else_counts_as_code(path: str) -> None:
    assert executable_paths([edit(path, "Wait for the rows.\n")]) == [path]


@pytest.mark.parametrize(
    "after",
    [
        ">>> wait_for_rows()\n",
        "```python\nimport os\n```\n",
        "~~~\nmake test\n~~~\n",
        ".. doctest::\n\n   x\n",
        "Intro\n  .. testcode::\n",
    ],
)
def test_documentation_that_tools_can_run_counts_as_code(after: str) -> None:
    assert executable_paths([edit("docs/guide.md", after, "Old text.\n")]) == ["docs/guide.md"]
