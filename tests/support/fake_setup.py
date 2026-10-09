from dataclasses import dataclass, field
from pathlib import Path

from flakipype.config.paths import AppPaths
from flakipype.config.secrets import FileSecretStore
from flakipype.github.binary import GhBinary, GhInstallError
from flakipype.github.gh import GhCli
from flakipype.llm.client import LlmEndpoint
from flakipype.llm.connection import ConnectionOk, ConnectionResult
from flakipype.setup.service import SetupDraft, SetupService

from support.fake_gh import FakeGh, gh_fixture

INSTALLED_GH = GhBinary(path=Path("/opt/gh/bin/gh"), version=(2, 102, 0))
USER_CALL = ["api", "user", "--include"]


@dataclass
class FakeGhProvider:
    fake_gh: FakeGh
    installed: GhBinary | None = INSTALLED_GH
    install_error: str = ""
    install_count: int = 0

    def find(self) -> GhBinary | None:
        return self.installed

    def install(self) -> GhBinary:
        self.install_count += 1
        if self.install_error:
            raise GhInstallError(self.install_error)
        self.installed = INSTALLED_GH
        return INSTALLED_GH

    def cli(self, binary: GhBinary, host: str) -> GhCli:
        assert binary == self.installed
        return self.fake_gh.cli(host)


@dataclass
class FakeLlm:
    result: ConnectionResult = field(default_factory=lambda: ConnectionOk(model="m-1-20260101"))
    endpoints: list[LlmEndpoint] = field(default_factory=list)

    def __call__(self, endpoint: LlmEndpoint) -> ConnectionResult:
        self.endpoints.append(endpoint)
        return self.result


@dataclass
class SetupWorld:
    service: SetupService
    paths: AppPaths
    secrets: FileSecretStore
    gh: FakeGhProvider
    llm: FakeLlm


def setup_world(tmp_path: Path, fake_gh: FakeGh) -> SetupWorld:
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    secrets = FileSecretStore(paths.secrets_file)
    gh = FakeGhProvider(fake_gh)
    llm = FakeLlm()
    service = SetupService(paths=paths, secrets=secrets, gh=gh, check_llm=llm)
    return SetupWorld(service=service, paths=paths, secrets=secrets, gh=gh, llm=llm)


def logged_in(fake_gh: FakeGh) -> None:
    fake_gh.record(USER_CALL, stdout=gh_fixture("api-user-include.txt"))


def complete_draft(api_key: str = "key-1") -> SetupDraft:
    return SetupDraft(
        base_url="https://api.anthropic.com",
        model="m-1",
        host="github.com",
        owner="octo-org",
        api_key=api_key,
    )
