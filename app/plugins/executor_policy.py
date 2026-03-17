from __future__ import annotations

from plugins.registry import list_workflow_plugins


def workflow_plugin_skill_keys() -> set[str]:
    keys: set[str] = set()
    for plugin in list_workflow_plugins():
        key = str(getattr(plugin, "key", "")).strip().lower()
        if key:
            keys.add(key)
    return keys


def is_task_scoped_context_enabled(
    *,
    project_plugin_enabled: bool,
    assignee_project_role: str | None,
) -> bool:
    if not project_plugin_enabled:
        return False
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "executor_is_task_scoped_context_enabled", None)
        if not callable(fn):
            continue
        if bool(fn(project_plugin_enabled=project_plugin_enabled, assignee_project_role=assignee_project_role)):
            return True
    return False


def should_prepare_task_worktree(
    *,
    plugin_enabled: bool,
    git_delivery_enabled: bool,
    task_status: str,
    actor_project_role: str | None,
    assignee_project_role: str | None,
) -> bool:
    if git_delivery_enabled and not plugin_enabled:
        # Standalone Git Delivery uses a single project workspace on main.
        return False

    if not plugin_enabled or not git_delivery_enabled:
        return False
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "executor_should_prepare_task_worktree", None)
        if not callable(fn):
            continue
        if bool(
            fn(
                plugin_enabled=plugin_enabled,
                git_delivery_enabled=git_delivery_enabled,
                task_status=task_status,
                actor_project_role=actor_project_role,
                assignee_project_role=assignee_project_role,
            )
        ):
            return True
    return False
