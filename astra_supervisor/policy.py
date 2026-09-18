from .contracts import (
    ExecutorAvailability,
    ExecutorName,
    NoExecutorAvailable,
    TaskKind,
)


def select_executor(task_kind: TaskKind, availability: ExecutorAvailability) -> ExecutorName:
    """Select the safest eligible executor for the authoritative state involved."""
    if not isinstance(task_kind, TaskKind):
        task_kind = TaskKind(task_kind)

    if task_kind is TaskKind.REVIEW_ONLY:
        return ExecutorName.NONE

    if task_kind is TaskKind.REPOSITORY_EDIT:
        if availability.github:
            return ExecutorName.GITHUB
        if availability.codex:
            return ExecutorName.CODEX
        if availability.local:
            return ExecutorName.LOCAL
        raise NoExecutorAvailable("no executor is available for repository-authoritative work")

    if task_kind is TaskKind.LOCAL_WORKSPACE:
        if availability.codex:
            return ExecutorName.CODEX
        if availability.local:
            return ExecutorName.LOCAL
        raise NoExecutorAvailable("no local-state-capable executor is available")

    raise NoExecutorAvailable(f"unsupported task kind: {task_kind}")
