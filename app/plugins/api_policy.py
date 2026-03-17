from __future__ import annotations

from typing import Any

from plugins.registry import list_workflow_plugins


def maybe_dispatch_execution_kickoff(
    *,
    db: Any,
    user: Any,
    workspace_id: str,
    project_id: str | None,
    intent_flags: dict[str, bool] | None,
    allow_mutations: bool,
    command_id: str | None,
    **context: Any,
) -> dict[str, object] | None:
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "api_maybe_dispatch_execution_kickoff", None)
        if not callable(fn):
            continue
        result = fn(
            db=db,
            user=user,
            workspace_id=workspace_id,
            project_id=project_id,
            intent_flags=intent_flags,
            allow_mutations=allow_mutations,
            command_id=command_id,
            **context,
        )
        if isinstance(result, dict):
            return result
    return None
