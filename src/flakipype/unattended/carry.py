"""What a run takes over from the run before: pull requests still being verified."""

from typing import Any

from flakipype.actions.watch import WatchedRun
from flakipype.fix.state import OpenedPull


def carried_over(document: dict[str, Any]) -> tuple[list[OpenedPull], list[WatchedRun]]:
    """Unverified pull requests of a run session and the runs their verifications follow."""
    pulls = [OpenedPull.from_dict(item) for item in document["fix"]["pulls"]]
    open_pulls = [pull for pull in pulls if not pull.verified]
    numbers = {number for pull in open_pulls for number in pull.verification.watched}
    runs = [WatchedRun.from_dict(item) for item in document["actions"]["runs"]]
    return open_pulls, [run for run in runs if run.number in numbers]
