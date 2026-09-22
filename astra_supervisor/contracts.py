from dataclasses import dataclass
from enum import Enum


class TaskKind(str, Enum):
    REPOSITORY_EDIT = "REPOSITORY_EDIT"
    LOCAL_WORKSPACE = "LOCAL_WORKSPACE"
    REVIEW_ONLY = "REVIEW_ONLY"


class ExecutorName(str, Enum):
    GITHUB = "GITHUB"
    CODEX = "CODEX"
    LOCAL = "LOCAL"
    NONE = "NONE"


@dataclass(frozen=True)
class ExecutorAvailability:
    github: bool = False
    codex: bool = False
    local: bool = False


class NoExecutorAvailable(RuntimeError):
    """Raised when no executor is eligible for the requested task kind."""
