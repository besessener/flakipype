"""Composition root: the only place that builds real collaborators from the environment."""

import getpass
import os
import platform
import shutil
import sys
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import httpx2
import keyring

from flakipype.actions.service import ActionService
from flakipype.agent.budget import Limits
from flakipype.agent.fix_pipeline import FixConfig, propose_fix
from flakipype.agent.masking import Masker
from flakipype.agent.messages import ModelSettings
from flakipype.agent.orchestrator import ChatAgent, ChatSettings, workspace_tools
from flakipype.agent.pipeline import AgentConfig, investigate_finding
from flakipype.agent.tools import Confirmer, HeadlessGate, Mode, PolicyGate
from flakipype.cli.readiness import NotReadyError, check_logged_in, check_run_owner
from flakipype.config.paths import AppPaths, app_paths
from flakipype.config.secrets import LLM_API_KEY, SecretStore, SecretStoreError, secret_store
from flakipype.config.settings import (
    FixSettings,
    SecretStoreChoice,
    Settings,
    SettingsError,
    load_settings,
)
from flakipype.fix.delivery import Delivery
from flakipype.fix.service import FixService
from flakipype.fix.verify import Verifier, VerifyGitHub
from flakipype.github.actions import ActionsClient
from flakipype.github.binary import GhInstaller
from flakipype.github.contents import ContentsClient
from flakipype.github.gh import GhCli
from flakipype.github.provider import ManagedGh
from flakipype.github.pulls import PullRequests
from flakipype.github.runs import RunControl
from flakipype.investigate.chat import ChatService
from flakipype.investigate.service import InvestigationService
from flakipype.investigate.workspace import ChatWorkspace
from flakipype.llm.client import (
    ClientSetupError,
    LlmEndpoint,
    ModelClient,
    create_client,
    request_timeout,
)
from flakipype.llm.connection import (
    ConnectionFailed,
    ConnectionProblem,
    ConnectionResult,
    check_connection,
)
from flakipype.scan.service import ScanRequest, ScanService
from flakipype.setup.daemon import Daemon, UnitOptions, installed_executable, run_command
from flakipype.setup.doctor import KEY_IN_A_FILE, RUN_SETUP
from flakipype.setup.service import SetupService
from flakipype.store.database import ScanCache
from flakipype.store.lock import run_lock
from flakipype.unattended.limits import run_actions, run_fix_settings, run_limits_for
from flakipype.unattended.service import RunClock, RunService

_DOWNLOAD_TIMEOUT_SECONDS = 120


def check_llm_endpoint(endpoint: LlmEndpoint) -> ConnectionResult:
    try:
        client = create_client(endpoint, max_retries=0)
    except ClientSetupError as error:
        return ConnectionFailed(ConnectionProblem.ENVIRONMENT, str(error))
    return check_connection(client, endpoint.model)


def _paths() -> AppPaths:
    return app_paths(os.environ, Path.home())


def _managed_gh(paths: AppPaths) -> ManagedGh:
    http = httpx2.Client(follow_redirects=True, timeout=_DOWNLOAD_TIMEOUT_SECONDS)
    gh_on_path = shutil.which("gh")
    return ManagedGh(
        GhInstaller(http, paths.bin_dir),
        on_path=Path(gh_on_path) if gh_on_path else None,
        machine=platform.machine(),
    )


def _secret_store(paths: AppPaths, choice: SecretStoreChoice) -> SecretStore:
    return secret_store(choice, keyring.get_keyring(), paths.secrets_file)


def build_setup_service(choice: SecretStoreChoice | None = None) -> SetupService:
    """The store `choice` names, else the saved one (auto when the configuration is unreadable)."""
    paths = _paths()
    if choice is None:
        try:
            choice = load_settings(paths.config_file).secrets.store
        except SettingsError:
            choice = SecretStoreChoice.AUTO
    return SetupService(
        paths=paths,
        secrets=_secret_store(paths, choice),
        gh=_managed_gh(paths),
        check_llm=check_llm_endpoint,
    )


def build_daemon() -> Daemon:
    return Daemon(unit_dir=_paths().systemd_unit_dir, run=run_command, user=getpass.getuser())


def unit_options(schedule: str, mode: Mode) -> UnitOptions:
    """The units for the running flakipype command; refused when a run could not read the config."""
    _ready_settings(_paths())
    return UnitOptions(
        executable=installed_executable(sys.argv[0], shutil.which),
        schedule=schedule,
        mode=mode.value,
    )


def require_configuration() -> None:
    """The timer only runs a set-up flakipype; previewing its units needs no configuration."""
    config_file = _paths().config_file
    if not config_file.exists():
        message = f"No configuration at {config_file}. {RUN_SETUP}"
        raise NotReadyError(message)


def _ready_settings(paths: AppPaths) -> Settings:
    try:
        return load_settings(paths.config_file)
    except SettingsError as error:
        message = f"{error}. {RUN_SETUP}"
        raise NotReadyError(message) from error


def _gh_cli(paths: AppPaths, host: str) -> GhCli:
    gh = _managed_gh(paths)
    binary = gh.find()
    if binary is None:
        message = f"No usable gh found. {RUN_SETUP}"
        raise NotReadyError(message)
    return gh.cli(binary, host)


def _scan_service(actions: ActionsClient, cache: ScanCache) -> ScanService:
    return ScanService(actions=actions, cache=cache, now=lambda: datetime.now(UTC))


@contextmanager
def open_scan() -> Generator[tuple[ScanService, Settings]]:
    paths = _paths()
    settings = _ready_settings(paths)
    actions = ActionsClient(_gh_cli(paths, settings.github.host))
    with ScanCache.open(paths.cache_file) as cache:
        yield _scan_service(actions, cache), settings


def _agent_config(settings: Settings, api_key: str, gh: GhCli) -> AgentConfig:
    agent = settings.agent
    endpoint = LlmEndpoint(settings.llm.base_url, api_key, settings.llm.model)
    # The client serves investigations and fixes, so a request fits in the shorter time limit.
    shortest = min(agent.max_seconds_per_investigation, settings.fix.max_seconds)
    try:
        sdk = create_client(endpoint, timeout=request_timeout(shortest))
    except ClientSetupError as error:
        message = f"{error}."
        raise NotReadyError(message) from error
    masker = Masker.with_secrets([api_key])
    return AgentConfig(
        client=ModelClient(sdk, masker.mask),
        settings=ModelSettings(
            model=settings.llm.model,
            max_tokens=agent.max_output_tokens,
            thinking=agent.thinking,
            thinking_budget=agent.thinking_budget,
        ),
        limits=Limits(
            rounds=agent.max_rounds,
            tokens=agent.max_tokens_per_investigation,
            seconds=agent.max_seconds_per_investigation,
        ),
        masker=masker,
        logs=ActionsClient(gh),
        contents=ContentsClient(gh),
        clock=time.monotonic,
        excerpt_lines=agent.excerpt_lines,
    )


@dataclass(frozen=True)
class _Agentic:
    settings: Settings
    config: AgentConfig
    service: InvestigationService
    cache: ScanCache
    gh: GhCli


@contextmanager
def _open_agentic() -> Generator[_Agentic]:
    paths = _paths()
    settings = _ready_settings(paths)
    if not settings.llm.model:
        message = f"No model configured. {RUN_SETUP}"
        raise NotReadyError(message)
    secrets = _secret_store(paths, settings.secrets.store)
    try:
        api_key = secrets.get(LLM_API_KEY)
    except SecretStoreError as error:
        message = f"Cannot read the API key from the {secrets.location}: {error}. {KEY_IN_A_FILE}"
        raise NotReadyError(message) from error
    if not api_key:
        message = f"No API key stored. {RUN_SETUP}"
        raise NotReadyError(message)
    gh = _gh_cli(paths, settings.github.host)
    config = _agent_config(settings, api_key, gh)
    with ScanCache.open(paths.cache_file) as cache:
        service = InvestigationService(
            scan=_scan_service(ActionsClient(gh), cache),
            cache=cache,
            investigate=partial(investigate_finding, config),
            run_tokens=settings.agent.max_tokens_per_run,
            parallel=settings.agent.parallel,
        )
        yield _Agentic(settings, config, service, cache, gh)


@contextmanager
def open_investigation() -> Generator[tuple[InvestigationService, Settings]]:
    with _open_agentic() as agentic:
        yield agentic.service, agentic.settings


def _fix_service(
    agentic: _Agentic, actions: ActionService, now: Callable[[], datetime], *, fix: FixSettings
) -> FixService:
    config, pulls = agentic.config, PullRequests(agentic.gh)
    verifier = Verifier(
        github=VerifyGitHub(
            runs=RunControl(agentic.gh), logs=ActionsClient(agentic.gh), comments=pulls
        ),
        actions=actions,
        now=now,
    )
    fix_config = FixConfig(
        client=config.client, settings=config.settings,
        limits=Limits(rounds=fix.max_rounds, tokens=fix.max_tokens, seconds=fix.max_seconds),
        masker=config.masker, logs=config.logs, contents=config.contents, files=pulls,
        clock=time.monotonic, excerpt_lines=config.excerpt_lines, stop=config.stop,
    )  # fmt: skip
    return FixService(
        pulls=pulls, delivery=Delivery(pulls=pulls, verifier=verifier, now=now),
        verifier=verifier, actions=actions, audit=agentic.cache.audit,
        propose=partial(propose_fix, fix_config), settings=fix, now=now,
    )  # fmt: skip


@contextmanager
def open_chat() -> Generator[tuple[ChatService, Settings]]:
    with _open_agentic() as agentic:
        settings = agentic.settings
        request = ScanRequest(
            owner=settings.github.owner,
            host=settings.github.host,
            window_days=settings.scan.window_days,
            max_log_downloads=settings.scan.max_log_downloads,
            min_flaky_runs=settings.scan.min_flaky_runs,
            max_job_reads=settings.scan.max_job_reads,
        )
        now = partial(datetime.now, UTC)
        actions = ActionService(
            runs=RunControl(agentic.gh),
            files=ContentsClient(agentic.gh),
            audit=agentic.cache.audit,
            settings=settings.actions,
            owner=settings.github.owner,
            now=now,
        )
        workspace = ChatWorkspace(
            agentic.service,
            request,
            actions=actions,
            fixes=_fix_service(agentic, actions, now, fix=settings.fix),
        )
        confirmer = Confirmer()
        gate = PolicyGate(Mode.ASK, confirmer)
        agent = ChatAgent(
            client=agentic.config.client,
            settings=ChatSettings(
                model=agentic.config.settings,
                limits=agentic.config.limits,
                turn_tokens=settings.agent.max_tokens_per_investigation,
                stop=agentic.config.stop,
            ),
            tools=workspace_tools(workspace),
            gate=gate,
            clock=time.monotonic,
        )
        chat = ChatService(
            workspace=workspace,
            agent=agent,
            gate=gate,
            sessions=agentic.cache.sessions,
            confirmer=confirmer,
            now=now,
        )
        yield chat, settings


@contextmanager
def open_run(mode: Mode, request_for: Callable[[Settings], ScanRequest]) -> Generator[RunService]:
    """Raises RunLockedError while another run holds the lock, before anything else happens."""
    with run_lock(_paths().run_lock_file), _open_agentic() as agentic:
        settings, cache = agentic.settings, agentic.cache
        request = request_for(settings)
        check_run_owner(request.owner, settings.github.owner)
        check_logged_in(agentic.gh, settings.github.host)
        now = partial(datetime.now, UTC)
        limits = run_limits_for(settings, cache, now())
        actions = run_actions(
            runs=RunControl(agentic.gh), files=ContentsClient(agentic.gh), audit=cache.audit,
            settings=settings, limits=limits, now=now,
        )  # fmt: skip
        workspace = ChatWorkspace(
            agentic.service,
            request,
            actions=actions,
            fixes=_fix_service(agentic, actions, now, fix=run_fix_settings(settings, limits)),
        )
        yield RunService(
            workspace=workspace, gate=HeadlessGate(mode), cache=cache, limits=limits,
            clock=RunClock(now=now, sleep=time.sleep),
        )  # fmt: skip
