import pytest

from flakipype.actions.dispatchable import dispatch_problem, triggers

NOT_DISPATCHABLE = "the workflow does not declare workflow_dispatch"


@pytest.mark.parametrize(
    "workflow",
    [
        "on: workflow_dispatch\n",
        "on: [push, workflow_dispatch]\n",
        "on:\n  workflow_dispatch:\n",
        (
            "'on':\n  workflow_dispatch:\n    inputs:\n      level:\n        required: true\n"
            "        default: info\n      note:\n        required: false\n      plain: text\n"
        ),
    ],
)
def test_dispatchable_workflows(workflow: str) -> None:
    assert dispatch_problem(workflow) is None


@pytest.mark.parametrize(
    ("workflow", "problem"),
    [
        ("on: push\n", NOT_DISPATCHABLE),
        ("on: [push]\n", NOT_DISPATCHABLE),
        ("on:\n  push:\n", NOT_DISPATCHABLE),
        ("- just a list\n", NOT_DISPATCHABLE),
        ("on: [unclosed\n", "the workflow file is not valid YAML"),
        (
            (
                "on:\n  workflow_dispatch:\n    inputs:\n      b:\n        required: true\n"
                "      a:\n        required: true\n"
            ),
            "the workflow needs inputs flakipype does not send: a, b",
        ),
    ],
)
def test_workflows_that_cannot_be_dispatched_without_inputs(workflow: str, problem: str) -> None:
    assert dispatch_problem(workflow) == problem


@pytest.mark.parametrize(
    ("workflow", "events"),
    [
        ("on: push\n", {"push"}),
        ("on: [push, pull_request]\n", {"push", "pull_request"}),
        ("'on':\n  pull_request:\n    branches: [main]\n  workflow_dispatch:\n",
         {"pull_request", "workflow_dispatch"}),
        ("on: 3\n", set()),
        ("- just a list\n", set()),
        ("on: [unclosed\n", set()),
    ],
)  # fmt: skip
def test_triggers(workflow: str, events: set[str]) -> None:
    assert triggers(workflow) == events
