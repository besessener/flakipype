"""Composition root: the only place that builds real collaborators from the environment."""

import os
import platform
import shutil
from pathlib import Path

import httpx2
import keyring

from flakipype.config.paths import app_paths
from flakipype.config.secrets import default_secret_store
from flakipype.github.binary import GhInstaller
from flakipype.github.provider import ManagedGh
from flakipype.llm.client import LlmEndpoint, create_client
from flakipype.llm.connection import ConnectionResult, check_connection
from flakipype.setup.service import SetupService

_DOWNLOAD_TIMEOUT_SECONDS = 120


def check_llm_endpoint(endpoint: LlmEndpoint) -> ConnectionResult:
    return check_connection(create_client(endpoint, max_retries=0), endpoint.model)


def build_setup_service() -> SetupService:
    paths = app_paths(os.environ, Path.home())
    http = httpx2.Client(follow_redirects=True, timeout=_DOWNLOAD_TIMEOUT_SECONDS)
    gh_on_path = shutil.which("gh")
    gh = ManagedGh(
        GhInstaller(http, paths.bin_dir),
        on_path=Path(gh_on_path) if gh_on_path else None,
        machine=platform.machine(),
    )
    return SetupService(
        paths=paths,
        secrets=default_secret_store(keyring.get_keyring(), paths.secrets_file),
        gh=gh,
        check_llm=check_llm_endpoint,
    )
