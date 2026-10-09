"""A chat over the investigation world: real workspace and services, scripted model."""

from datetime import timedelta

from flakipype.agent.budget import Limits
from flakipype.agent.investigator import ModelSettings
from flakipype.agent.masking import Masker
from flakipype.agent.orchestrator import ChatAgent, ChatSettings, workspace_tools
from flakipype.agent.tools import Mode, PolicyGate, deny_all
from flakipype.investigate.chat import ChatService
from flakipype.investigate.service import InvestigationService
from flakipype.investigate.workspace import ChatWorkspace
from flakipype.scan.service import ScanService
from flakipype.store.database import ScanCache

from support.builders import START
from support.fake_actions import FakeActions
from support.fake_anthropic import ScriptedModel
from support.fake_investigation import SCAN, FakeAgent, world

NOW = START.replace(day=9)


def chat_workspace(
    cache: ScanCache, agent: FakeAgent, actions: FakeActions | None = None
) -> ChatWorkspace:
    scan = ScanService(actions=actions or world(), cache=cache, now=lambda: NOW)
    service = InvestigationService(
        scan=scan, cache=cache, investigate=agent, run_tokens=10**6, parallel=1
    )
    return ChatWorkspace(service, SCAN)


def chat_service(
    cache: ScanCache,
    model: ScriptedModel,
    *,
    agent: FakeAgent | None = None,
    actions: FakeActions | None = None,
) -> ChatService:
    workspace = chat_workspace(cache, agent or FakeAgent(), actions)
    minutes = iter(range(10**6))
    chat_agent = ChatAgent(
        client=model.client(),
        settings=ChatSettings(model=ModelSettings(model="m-1"), limits=Limits(), turn_tokens=10**6),
        tools=workspace_tools(workspace),
        gate=PolicyGate(Mode.ASK, deny_all),
        masker=Masker.with_secrets([]),
        clock=lambda: 0.0,
    )
    return ChatService(
        workspace=workspace,
        agent=chat_agent,
        sessions=cache.sessions,
        now=lambda: NOW + timedelta(minutes=next(minutes)),
    )
