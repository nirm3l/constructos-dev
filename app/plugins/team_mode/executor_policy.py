from __future__ import annotations


def is_task_scoped_context_enabled(*, project_team_mode_enabled: bool, assignee_project_role: str | None) -> bool:
    if not project_team_mode_enabled:
        return False
    role = str(assignee_project_role or "").strip()
    return role in {"DeveloperAgent", "QAAgent", "TeamLeadAgent"}


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
    if str(task_status or "").strip() != "Dev":
        return False
    actor_role = str(actor_project_role or "").strip()
    assignee_role = str(assignee_project_role or "").strip()
    return actor_role == "DeveloperAgent" or assignee_role == "DeveloperAgent"
