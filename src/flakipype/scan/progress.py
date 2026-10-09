from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class Stage(StrEnum):
    REPOSITORIES = "Listing repositories"
    RUNS = "Reading workflow runs"
    JOBS = "Inspecting failed attempts"
    LOGS = "Reading logs of flaky jobs"


@dataclass(frozen=True)
class Progress:
    stage: Stage
    done: int
    total: int
    detail: str = ""


type ProgressListener = Callable[[Progress], None]


def ignore_progress(progress: Progress) -> None:
    del progress
