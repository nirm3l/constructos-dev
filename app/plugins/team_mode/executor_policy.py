from __future__ import annotations

from .semantics import semantic_status_key
from .task_roles import canonicalize_role


def is_task_scoped_context_enabled(*, project_team_mode_enabled: bool, assignee_project_role: str | None) -> bool:
    if not project_team_mode_enabled:
        return False
    role = canonicalize_role(assignee_project_role)
    return role in {"Developer", "QA", "Lead"}


def should_prepare_task_worktree(
    *,
    team_mode_enabled: bool,
    git_delivery_enabled: bool,
    task_status: str,
    actor_project_role: str | None,
    assignee_project_role: str | None,
) -> bool:
    if not team_mode_enabled or not git_delivery_enabled:
        return False
    actor_role = canonicalize_role(actor_project_role)
    assignee_role = canonicalize_role(assignee_project_role)
    if actor_role != "Developer" and assignee_role != "Developer":
        return False
    semantic = semantic_status_key(status=task_status)
    return semantic in {"todo", "active", "blocked"}
