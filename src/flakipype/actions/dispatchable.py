"""Whether flakipype may dispatch a workflow: it must allow it and need no input."""

from typing import Any

import yaml

_NOT_DISPATCHABLE = "the workflow does not declare workflow_dispatch"
_DISPATCH = "workflow_dispatch"


def dispatch_problem(workflow_text: str) -> str | None:
    """Why the workflow cannot be dispatched without inputs, or None if it can."""
    try:
        document: Any = yaml.safe_load(workflow_text)
    except yaml.YAMLError:
        return "the workflow file is not valid YAML"
    if not isinstance(document, dict):
        return _NOT_DISPATCHABLE
    # YAML 1.1 reads the unquoted key `on` as the boolean true.
    triggers = document.get("on", document.get(True))
    if triggers == _DISPATCH or (isinstance(triggers, list) and _DISPATCH in triggers):
        return None
    if not isinstance(triggers, dict) or _DISPATCH not in triggers:
        return _NOT_DISPATCHABLE
    return _missing_inputs(triggers[_DISPATCH])


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
