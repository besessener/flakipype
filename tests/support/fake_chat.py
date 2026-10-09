"""A chat over the investigation world: real workspace and services, scripted model."""

from dataclasses import dataclass, field
from datetime import timedelta

from flakipype.actions.service import ActionService
from flakipype.agent.budget import Limits
from flakipype.agent.investigator import ModelSettings
from flakipype.agent.masking import Masker
from flakipype.agent.orchestrator import ChatAgent, ChatSettings, workspace_tools
from flakipype.agent.tools import Confirmer, Mode, PolicyGate
from flakipype.config.settings import ActionSettings, FixSettings
from flakipype.fix.delivery import Delivery
from flakipype.fix.service import FixService
from flakipype.fix.verify import Verifier, VerifyGitHub
from flakipype.investigate.chat import ChatService
from flakipype.investigate.service import InvestigationService
from flakipype.investigate.workspace import ChatWorkspace
from flakipype.scan.service import ScanService
from flakipype.store.database import ScanCache

from support.builders import START
from support.fake_actions import FakeActions
from support.fake_anthropic import ScriptedModel
from support.fake_fix import FakeFixer, FakePullRequests
from support.fake_investigation import SCAN, FakeAgent, world
from support.fake_runs import FakeRuns

NOW = START.replace(day=9)


@dataclass
class FixFakes:
    """GitHub's pull requests and the fixer, for the chat's fixes."""

    github: FakePullRequests = field(default_factory=FakePullRequests)
    fixer: FakeFixer = field(default_factory=FakeFixer)
    settings: FixSettings = field(default_factory=FixSettings)


def chat_workspace(
    cache: ScanCache,
    agent: FakeAgent,
    actions: FakeActions | None = None,
    runs: FakeRuns | None = None,
    fixes: FixFakes | None = None,
) -> ChatWorkspace:
    github = actions or world()
    scan = ScanService(actions=github, cache=cache, now=lambda: NOW)
    service = InvestigationService(
        scan=scan, cache=cache, investigate=agent, run_tokens=10**6, parallel=1
    )
    started = runs or FakeRuns()
    action_service = ActionService(
        runs=started, files=started, audit=cache.audit, settings=ActionSettings(),
        owner=SCAN.owner, now=lambda: NOW,
    )  # fmt: skip
    fakes = fixes or FixFakes()
    verifier = Verifier(
        github=VerifyGitHub(runs=fakes.github, logs=github, comments=fakes.github),
        actions=action_service,
        now=lambda: NOW,
    )
    delivery = Delivery(pulls=fakes.github, verifier=verifier, now=lambda: NOW)
    fix_service = FixService(
        pulls=fakes.github, delivery=delivery, verifier=verifier, actions=action_service,
        audit=cache.audit, propose=fakes.fixer, settings=fakes.settings, now=lambda: NOW,
    )  # fmt: skip
    return ChatWorkspace(service, SCAN, actions=action_service, fixes=fix_service)


def chat_service(
    cache: ScanCache,
    model: ScriptedModel,
    *,
    agent: FakeAgent | None = None,
    actions: FakeActions | None = None,
    runs: FakeRuns | None = None,
    fixes: FixFakes | None = None,
    confirmer: Confirmer | None = None,
) -> ChatService:
    workspace = chat_workspace(cache, agent or FakeAgent(), actions, runs, fixes)
    confirm = confirmer or Confirmer()
    gate = PolicyGate(Mode.ASK, confirm)
    minutes = iter(range(10**6))
    chat_agent = ChatAgent(
        client=model.client(),
        settings=ChatSettings(model=ModelSettings(model="m-1"), limits=Limits(), turn_tokens=10**6),
        tools=workspace_tools(workspace),
        gate=gate,
        masker=Masker.with_secrets([]),
        clock=lambda: 0.0,
    )
    return ChatService(
        workspace=workspace,
        agent=chat_agent,
        gate=gate,
        sessions=cache.sessions,
        confirmer=confirm,
        now=lambda: NOW + timedelta(minutes=next(minutes)),
    )
