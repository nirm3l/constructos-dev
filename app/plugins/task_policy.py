from __future__ import annotations

from plugins.registry import list_workflow_plugins


def should_cleanup_task_worktree(
    *,
    plugin_enabled: bool,
    task_status: str,
    assignee_role: str | None,
) -> bool:
    if not plugin_enabled:
        return False
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "task_should_cleanup_worktree", None)
        if not callable(fn):
            continue
        if bool(
            fn(
                plugin_enabled=plugin_enabled,
                task_status=task_status,
                assignee_role=assignee_role,
            )
        ):
            return True
    return False
