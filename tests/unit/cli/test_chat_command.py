from collections.abc import Iterator
from contextlib import contextmanager
from typing import ClassVar

import click
import pytest
from typer.testing import CliRunner

from flakipype.cli import app, chat_command, wiring
from flakipype.config.settings import GitHubSettings, Settings
from flakipype.github.actions import GitHubApiError
from flakipype.investigate.chat import ChatService
from flakipype.store.database import ScanCache

from support.fake_anthropic import ScriptedModel
from support.fake_chat import chat_service

runner = CliRunner()


class RecordingApp:
    opened: ClassVar[list[tuple[ChatService, str]]] = []

    def __init__(self, service: ChatService, subtitle: str) -> None:
        self.opened.append((service, subtitle))

    def run(self) -> None:
        return None


def in_terminal(monkeypatch: pytest.MonkeyPatch, error: Exception | None = None) -> None:
    @contextmanager
    def open_chat() -> Iterator[tuple[ChatService, Settings]]:
        if error is not None:
            raise error
        with ScanCache.in_memory() as cache:
            yield (
                chat_service(cache, ScriptedModel([])),
                Settings(github=GitHubSettings(owner="octo-org")),
            )

    RecordingApp.opened = []
    monkeypatch.setattr(chat_command, "is_interactive_terminal", lambda: True)
    monkeypatch.setattr(chat_command, "ChatApp", RecordingApp)
    monkeypatch.setattr(wiring, "open_chat", open_chat)


def test_without_a_command_the_chat_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    in_terminal(monkeypatch)

    result = runner.invoke(app, [])

    assert result.exit_code == 0, result.output
    ((_, subtitle),) = RecordingApp.opened
    assert subtitle == "octo-org on github.com"


@pytest.mark.parametrize(
    ("error", "code", "shown"),
    [
        (wiring.NotReadyError("No API key stored."), 2, "Not ready: No API key stored."),
        (GitHubApiError("gh: Not Found (HTTP 404)", 404), 1, "GitHub: gh: Not Found"),
    ],
)
def test_problems_before_the_chat_opens(
    monkeypatch: pytest.MonkeyPatch, error: Exception, code: int, shown: str
) -> None:
    in_terminal(monkeypatch, error)

    result = runner.invoke(app, [])

    assert result.exit_code == code
    assert shown in click.unstyle(result.output)
    assert RecordingApp.opened == []
