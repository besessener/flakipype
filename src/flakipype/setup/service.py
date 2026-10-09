from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import ValidationError

from flakipype.config.paths import AppPaths
from flakipype.config.secrets import LLM_API_KEY, SecretStore
from flakipype.config.settings import (
    GitHubSettings,
    LlmSettings,
    Settings,
    SettingsError,
    load_settings,
    save_settings,
)
from flakipype.github.auth import (
    AuthCheckFailed,
    AuthStatus,
    auth_status,
    browser_login_arguments,
    login_with_token,
)
from flakipype.github.binary import GhBinary
from flakipype.github.provider import GhProvider
from flakipype.llm.client import LlmEndpoint
from flakipype.llm.connection import ConnectionResult

GH_NOT_INSTALLED = "gh is not installed yet."


class InvalidSetupError(Exception):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{name}: {message}" for name, message in errors.items()))
        self.errors = errors


class GhMissingError(Exception):
    """An action needs gh, but none is installed."""


@dataclass(frozen=True)
class SetupDraft:
    base_url: str
    model: str
    host: str
    owner: str
    api_key: str = field(default="", repr=False)


@dataclass(frozen=True)
class SetupState:
    settings: Settings
    has_api_key: bool
    problem: str = ""


def _validated[Model](
    build: Callable[[], Model], prefix: str
) -> tuple[Model | None, dict[str, str]]:
    try:
        return build(), {}
    except ValidationError as error:
        errors = {
            ".".join([prefix, *(str(part) for part in item["loc"])]): str(item["msg"]).removeprefix(
                "Value error, "
            )
            for item in error.errors()
        }
        return None, errors


class SetupService:
    def __init__(
        self,
        *,
        paths: AppPaths,
        secrets: SecretStore,
        gh: GhProvider,
        check_llm: Callable[[LlmEndpoint], ConnectionResult],
    ) -> None:
        self._paths = paths
        self._secrets = secrets
        self._gh = gh
        self._check_llm = check_llm

    @property
    def paths(self) -> AppPaths:
        return self._paths

    @property
    def secret_location(self) -> str:
        return self._secrets.location

    def load(self) -> SetupState:
        has_api_key = self._secrets.get(LLM_API_KEY) is not None
        try:
            return SetupState(load_settings(self._paths.config_file), has_api_key)
        except SettingsError as error:
            return SetupState(Settings(), has_api_key, problem=str(error))

    def llm_endpoint(self, draft: SetupDraft) -> LlmEndpoint:
        """Validate only the model part, so it can be tested before GitHub is filled in."""
        llm, errors = self._validated_llm(draft)
        if llm is None or errors:
            raise InvalidSetupError(errors)
        api_key = draft.api_key or self._secrets.get(LLM_API_KEY) or ""
        return LlmEndpoint(llm.base_url, api_key, llm.model)

    def settings_from(self, draft: SetupDraft) -> Settings:
        """Validate the whole draft at once, so the user sees every problem together."""
        llm, errors = self._validated_llm(draft)
        github, github_errors = _validated(
            lambda: GitHubSettings(host=draft.host, owner=draft.owner), "github"
        )
        errors |= github_errors
        if not draft.owner.strip():
            errors["github.owner"] = "is required"
        if llm is None or github is None or errors:
            raise InvalidSetupError(errors)
        return Settings(llm=llm, github=github)

    def _validated_llm(self, draft: SetupDraft) -> tuple[LlmSettings | None, dict[str, str]]:
        model = draft.model.strip()
        llm, errors = _validated(lambda: LlmSettings(base_url=draft.base_url, model=model), "llm")
        if not model:
            errors["llm.model"] = "is required"
        if not draft.api_key and self._secrets.get(LLM_API_KEY) is None:
            errors["llm.api_key"] = "is required"
        return llm, errors

    def check_llm(self, draft: SetupDraft) -> ConnectionResult:
        return self._check_llm(self.llm_endpoint(draft))

    def save(self, draft: SetupDraft) -> Settings:
        settings = self.settings_from(draft)
        if draft.api_key:
            self._secrets.put(LLM_API_KEY, draft.api_key)
        save_settings(settings, self._paths.config_file)
        return settings

    def find_gh(self) -> GhBinary | None:
        return self._gh.find()

    def install_gh(self) -> GhBinary:
        """Raises GhInstallError; an existing gh is kept."""
        found = self._gh.find()
        if found is not None:
            return found
        return self._gh.install()

    def github_auth(self, host: str) -> AuthStatus:
        binary = self._gh.find()
        if binary is None:
            return AuthCheckFailed(GH_NOT_INSTALLED)
        return auth_status(self._gh.cli(binary, host))

    def login_with_token(self, host: str, token: str) -> None:
        login_with_token(self._gh.cli(self._require_gh(), host), token)

    def browser_login(self, host: str) -> int:
        gh = self._gh.cli(self._require_gh(), host)
        return gh.run_interactive(browser_login_arguments(host))

    def _require_gh(self) -> GhBinary:
        binary = self._gh.find()
        if binary is None:
            raise GhMissingError(GH_NOT_INSTALLED)
        return binary
