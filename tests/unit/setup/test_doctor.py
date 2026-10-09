from pathlib import Path

from flakipype.llm.connection import ConnectionFailed, ConnectionProblem
from flakipype.setup.doctor import Check, CheckStatus, run_checks

from support.fake_gh import FakeGh
from support.fake_setup import USER_CALL, SetupWorld, complete_draft, logged_in, setup_world


def statuses(checks: list[Check]) -> dict[str, CheckStatus]:
    return {check.name: check.status for check in checks}


def configured_world(tmp_path: Path, fake_gh: FakeGh) -> SetupWorld:
    world = setup_world(tmp_path, fake_gh)
    world.service.save(complete_draft())
    return world


def test_everything_healthy(tmp_path: Path, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)

    checks = run_checks(configured_world(tmp_path, fake_gh).service)

    assert statuses(checks) == {
        "Configuration": CheckStatus.OK,
        "Model (Anthropic API)": CheckStatus.OK,
        "gh CLI": CheckStatus.OK,
        "GitHub login (github.com)": CheckStatus.OK,
        "Scan target": CheckStatus.OK,
    }
    assert "m-1-20260101" in checks[1].detail
    assert "octocat" in checks[3].detail


def test_unconfigured_machine_points_to_setup(tmp_path: Path, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)

    checks = run_checks(setup_world(tmp_path, fake_gh).service)

    assert checks[0].status is CheckStatus.FAILED
    assert checks[0].next_step == "Run `flakipype setup`."
    assert [check.name for check in checks] == [
        "Configuration",
        "gh CLI",
        "GitHub login (github.com)",
    ]


def test_unreadable_config_stops_early(tmp_path: Path, fake_gh: FakeGh) -> None:
    world = setup_world(tmp_path, fake_gh)
    world.paths.config_dir.mkdir(parents=True)
    world.paths.config_file.write_text("broken = = toml", encoding="utf-8")

    checks = run_checks(world.service)

    assert len(checks) == 1
    assert "Cannot read" in checks[0].detail


def test_failed_model_check_carries_the_next_step(tmp_path: Path, fake_gh: FakeGh) -> None:
    logged_in(fake_gh)
    world = configured_world(tmp_path, fake_gh)
    world.llm.result = ConnectionFailed(ConnectionProblem.AUTHENTICATION, "invalid x-api-key")

    model_check = run_checks(world.service)[1]

    assert model_check.status is CheckStatus.FAILED
    assert model_check.detail == "invalid x-api-key"
    assert model_check.next_step == ConnectionProblem.AUTHENTICATION.next_step


def test_missing_gh_and_login(tmp_path: Path, fake_gh: FakeGh) -> None:
    world = configured_world(tmp_path, fake_gh)
    world.gh.installed = None

    checks = statuses(run_checks(world.service))

    assert checks["gh CLI"] is CheckStatus.FAILED
    assert checks["GitHub login (github.com)"] is CheckStatus.FAILED


def test_not_logged_in(tmp_path: Path, fake_gh: FakeGh) -> None:
    fake_gh.record(USER_CALL, stderr="To get started with GitHub CLI", exit_code=4)

    login = run_checks(configured_world(tmp_path, fake_gh).service)[3]

    assert login.status is CheckStatus.FAILED
    assert login.detail == "Not logged in."


def test_missing_scopes_suggest_a_refresh(tmp_path: Path, fake_gh: FakeGh) -> None:
    output = 'HTTP/2.0 200 OK\nX-Oauth-Scopes: repo\n\n{"login": "octocat"}'
    fake_gh.record(USER_CALL, stdout=output)

    login = run_checks(configured_world(tmp_path, fake_gh).service)[3]

    assert login.status is CheckStatus.FAILED
    assert "read:org, workflow" in login.detail
    assert login.next_step.startswith("gh auth refresh")


def test_fine_grained_token_is_a_warning(tmp_path: Path, fake_gh: FakeGh) -> None:
    fake_gh.record(USER_CALL, stdout='HTTP/2.0 200 OK\n\n{"login": "octocat"}')

    login = run_checks(configured_world(tmp_path, fake_gh).service)[3]

    assert login.status is CheckStatus.WARNING
    assert "Workflows" in login.next_step
