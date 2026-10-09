from dataclasses import dataclass
from enum import StrEnum

from flakipype.github.auth import Authenticated, NotAuthenticated, refresh_scopes_command
from flakipype.github.release import MINIMUM_GH_VERSION, format_version
from flakipype.llm.client import endpoint_kind
from flakipype.llm.connection import ConnectionFailed
from flakipype.setup.service import InvalidSetupError, SetupDraft, SetupService

RUN_SETUP = "Run `flakipype setup`."


class CheckStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    FAILED = "failed"


@dataclass(frozen=True)
class Check:
    name: str
    status: CheckStatus
    detail: str
    next_step: str = ""


def run_checks(service: SetupService) -> list[Check]:
    state = service.load()
    settings = state.settings
    if state.problem:
        return [Check("Configuration", CheckStatus.FAILED, state.problem, RUN_SETUP)]
    draft = SetupDraft(
        base_url=settings.llm.base_url,
        model=settings.llm.model,
        host=settings.github.host,
        owner=settings.github.owner,
    )
    try:
        service.settings_from(draft)
    except InvalidSetupError as error:
        detail = f"Incomplete ({error}) in {service.paths.config_file}"
        configuration = Check("Configuration", CheckStatus.FAILED, detail, RUN_SETUP)
        return [configuration, gh_check(service), github_check(service, settings.github.host)]
    configuration = Check("Configuration", CheckStatus.OK, str(service.paths.config_file))
    return [
        configuration,
        llm_check(service, draft),
        gh_check(service),
        github_check(service, settings.github.host),
        Check("Scan target", CheckStatus.OK, f"{settings.github.owner} on {settings.github.host}"),
    ]


def llm_check(service: SetupService, draft: SetupDraft) -> Check:
    result = service.check_llm(draft)
    name = f"Model ({endpoint_kind(draft.base_url)})"
    if isinstance(result, ConnectionFailed):
        return Check(name, CheckStatus.FAILED, result.detail, result.problem.next_step)
    detail = f"{result.model} at {draft.base_url}, key in {service.secret_location}"
    return Check(name, CheckStatus.OK, detail)


def gh_check(service: SetupService) -> Check:
    binary = service.find_gh()
    if binary is None:
        minimum = format_version(MINIMUM_GH_VERSION)
        detail = f"No gh {minimum} or newer found."
        return Check("gh CLI", CheckStatus.FAILED, detail, f"{RUN_SETUP} It downloads gh.")
    return Check("gh CLI", CheckStatus.OK, f"{format_version(binary.version)} at {binary.path}")


def github_check(service: SetupService, host: str) -> Check:
    status = service.github_auth(host)
    name = f"GitHub login ({host})"
    if isinstance(status, NotAuthenticated):
        return Check(name, CheckStatus.FAILED, "Not logged in.", RUN_SETUP)
    if not isinstance(status, Authenticated):
        return Check(name, CheckStatus.FAILED, status.detail, RUN_SETUP)
    if status.scopes is None:
        detail = f"{status.login}, token permissions cannot be read (fine-grained token)."
        hint = "Make sure it grants Actions, Contents, Pull requests and Workflows: read and write."
        return Check(name, CheckStatus.WARNING, detail, hint)
    if status.missing_scopes:
        missing = ", ".join(sorted(status.missing_scopes))
        detail = f"{status.login}, missing scopes: {missing}"
        return Check(
            name, CheckStatus.FAILED, detail, refresh_scopes_command(host, status.missing_scopes)
        )
    return Check(name, CheckStatus.OK, f"{status.login}, scopes {', '.join(sorted(status.scopes))}")
