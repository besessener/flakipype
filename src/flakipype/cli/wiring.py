"""Composition root: the only place that builds real collaborators from the environment."""

import os
import platform
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import httpx2
import keyring

from flakipype.actions.service import ActionService
from flakipype.agent.budget import Limits
from flakipype.agent.investigator import ModelSettings
from flakipype.agent.masking import Masker
from flakipype.agent.orchestrator import ChatAgent, ChatSettings, workspace_tools
from flakipype.agent.pipeline import AgentConfig, investigate_finding
from flakipype.agent.tools import Confirmer, Mode, PolicyGate
from flakipype.config.paths import AppPaths, app_paths
from flakipype.config.secrets import LLM_API_KEY, default_secret_store
from flakipype.config.settings import Settings, SettingsError, load_settings
from flakipype.github.actions import ActionsClient
from flakipype.github.binary import GhInstaller
from flakipype.github.contents import ContentsClient
from flakipype.github.gh import GhCli
from flakipype.github.provider import ManagedGh
from flakipype.github.runs import RunControl
from flakipype.investigate.chat import ChatService
from flakipype.investigate.service import InvestigationService
from flakipype.investigate.workspace import ChatWorkspace
from flakipype.llm.client import LlmEndpoint, create_client
from flakipype.llm.connection import ConnectionResult, check_connection
from flakipype.scan.service import ScanRequest, ScanService
from flakipype.setup.doctor import RUN_SETUP
from flakipype.setup.service import SetupService
from flakipype.store.database import ScanCache

_DOWNLOAD_TIMEOUT_SECONDS = 120


def check_llm_endpoint(endpoint: LlmEndpoint) -> ConnectionResult:
    return check_connection(create_client(endpoint, max_retries=0), endpoint.model)


class NotReadyError(Exception):
    """flakipype is not set up far enough for this command; the message says what to do."""


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


def build_setup_service() -> SetupService:
    paths = _paths()
    return SetupService(
        paths=paths,
        secrets=default_secret_store(keyring.get_keyring(), paths.secrets_file),
        gh=_managed_gh(paths),
        check_llm=check_llm_endpoint,
    )


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
def open_scan() -> Iterator[tuple[ScanService, Settings]]:
    paths = _paths()
    settings = _ready_settings(paths)
    actions = ActionsClient(_gh_cli(paths, settings.github.host))
    with ScanCache.open(paths.cache_file) as cache:
        yield _scan_service(actions, cache), settings


def _agent_config(settings: Settings, api_key: str, gh: GhCli) -> AgentConfig:
    agent = settings.agent
    endpoint = LlmEndpoint(settings.llm.base_url, api_key, settings.llm.model)
    return AgentConfig(
        client=create_client(endpoint),
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
        masker=Masker.with_secrets([api_key]),
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
def _open_agentic() -> Iterator[_Agentic]:
    paths = _paths()
    settings = _ready_settings(paths)
    if not settings.llm.model:
        message = f"No model configured. {RUN_SETUP}"
        raise NotReadyError(message)
    secrets = default_secret_store(keyring.get_keyring(), paths.secrets_file)
    api_key = secrets.get(LLM_API_KEY)
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
def open_investigation() -> Iterator[tuple[InvestigationService, Settings]]:
    with _open_agentic() as agentic:
        yield agentic.service, agentic.settings


@contextmanager
def open_chat() -> Iterator[tuple[ChatService, Settings]]:
    with _open_agentic() as agentic:
        settings = agentic.settings
        request = ScanRequest(
            owner=settings.github.owner,
            host=settings.github.host,
            window_days=settings.scan.window_days,
            max_log_downloads=settings.scan.max_log_downloads,
            min_flaky_runs=settings.scan.min_flaky_runs,
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
        workspace = ChatWorkspace(agentic.service, request, actions=actions)
        confirmer = Confirmer()
        agent = ChatAgent(
            client=agentic.config.client,
            settings=ChatSettings(
                model=agentic.config.settings,
                limits=agentic.config.limits,
                turn_tokens=settings.agent.max_tokens_per_investigation,
            ),
            tools=workspace_tools(workspace),
            gate=PolicyGate(Mode.ASK, confirmer),
            masker=agentic.config.masker,
            clock=time.monotonic,
        )
        chat = ChatService(
            workspace=workspace,
            agent=agent,
            sessions=agentic.cache.sessions,
            confirmer=confirmer,
            now=now,
        )
        yield chat, settings
