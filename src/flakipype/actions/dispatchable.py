"""What starts a workflow, and whether flakipype may dispatch it: allowed and without input."""

from typing import Any

import yaml

_NOT_DISPATCHABLE = "the workflow does not declare workflow_dispatch"
_DISPATCH = "workflow_dispatch"


def triggers(workflow_text: str) -> set[str]:
    """The events that start the workflow; empty if the file is not a valid workflow."""
    try:
        document: Any = yaml.safe_load(workflow_text)
    except yaml.YAMLError:
        return set()
    if not isinstance(document, dict):
        return set()
    # YAML 1.1 reads the unquoted key `on` as the boolean true.
    events = document.get("on", document.get(True))
    if isinstance(events, str):
        return {events}
    if isinstance(events, list | dict):
        return {str(event) for event in events}
    return set()


def dispatch_problem(workflow_text: str) -> str | None:
    """Why the workflow cannot be dispatched without inputs, or None if it can."""
    try:
        document: Any = yaml.safe_load(workflow_text)
    except yaml.YAMLError:
        return "the workflow file is not valid YAML"
    if not isinstance(document, dict):
        return _NOT_DISPATCHABLE
    events = document.get("on", document.get(True))
    if events == _DISPATCH or (isinstance(events, list) and _DISPATCH in events):
        return None
    if not isinstance(events, dict) or _DISPATCH not in events:
        return _NOT_DISPATCHABLE
    return _missing_inputs(events[_DISPATCH])


def _missing_inputs(dispatch: object) -> str | None:
    inputs = dispatch.get("inputs") if isinstance(dispatch, dict) else None
    if not isinstance(inputs, dict):
        return None
    required = sorted(
        str(name)
        for name, spec in inputs.items()
        if isinstance(spec, dict) and spec.get("required") is True and "default" not in spec
    )
    if not required:
        return None
    return f"the workflow needs inputs flakipype does not send: {', '.join(required)}"
