"""Composition root: the only place that builds real collaborators from the environment."""

import os
import platform
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import keyring

from flakipype.config.paths import AppPaths, app_paths
from flakipype.config.secrets import default_secret_store
from flakipype.config.settings import Settings, SettingsError, load_settings
from flakipype.github.actions import ActionsClient
from flakipype.github.binary import GhInstaller
from flakipype.github.provider import ManagedGh
from flakipype.llm.client import LlmEndpoint, create_client
from flakipype.llm.connection import ConnectionResult, check_connection
from flakipype.scan.service import ScanService
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


@contextmanager
def open_scan() -> Iterator[tuple[ScanService, Settings]]:
    paths = _paths()
    try:
        settings = load_settings(paths.config_file)
    except SettingsError as error:
        message = f"{error}. {RUN_SETUP}"
        raise NotReadyError(message) from error
    gh = _managed_gh(paths)
    binary = gh.find()
    if binary is None:
        message = f"No usable gh found. {RUN_SETUP}"
        raise NotReadyError(message)
    actions = ActionsClient(gh.cli(binary, settings.github.host))
    with ScanCache.open(paths.cache_file) as cache:
        yield ScanService(actions=actions, cache=cache, now=lambda: datetime.now(UTC)), settings
