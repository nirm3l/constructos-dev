from __future__ import annotations

from typing import Any, Callable

from plugins.registry import list_workflow_plugins, plugin_by_key


def project_has_plugin_enabled(
    *,
    plugin_key: str,
    db: Any,
    workspace_id: str,
    project_id: str,
) -> bool:
    plugin = plugin_by_key(plugin_key)
    if plugin is None:
        return False
    fn = getattr(plugin, "service_project_has_enabled", None)
    if not callable(fn):
        return False
    return bool(
        fn(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
    )


def open_plugin_developer_tasks(
    *,
    plugin_key: str,
    db: Any,
    project_id: str,
) -> list[dict[str, str]]:
    plugin = plugin_by_key(plugin_key)
    if plugin is None:
        return []
    fn = getattr(plugin, "service_open_developer_tasks", None)
    if not callable(fn):
        return []
    rows = fn(db=db, project_id=project_id)
    return list(rows or [])


def enforce_plugin_done_transition(
    *,
    plugin_key: str,
    db: Any,
    state: Any,
    assignee_role: str,
    verify_delivery_workflow_fn: Callable[..., dict],
    auth_token: str | None,
) -> None:
    plugin = plugin_by_key(plugin_key)
    if plugin is None:
        return
    fn = getattr(plugin, "service_enforce_done_transition", None)
    if not callable(fn):
        return
    fn(
        db=db,
        state=state,
        assignee_role=assignee_role,
        verify_delivery_workflow_fn=verify_delivery_workflow_fn,
        auth_token=auth_token,
    )


def verify_plugin_workflow(
    *,
    plugin_key: str,
    project_id: str,
    auth_token: str | None,
    workspace_id: str | None,
    expected_event_storming_enabled: bool | None,
    verify_workflow_core: Callable[..., dict],
) -> dict | None:
    plugin = plugin_by_key(plugin_key)
    if plugin is None:
        return None
    fn = getattr(plugin, "service_verify_workflow", None)
    if not callable(fn):
        return None
    result = fn(
        project_id=project_id,
        auth_token=auth_token,
        workspace_id=workspace_id,
        expected_event_storming_enabled=expected_event_storming_enabled,
        verify_workflow_core=verify_workflow_core,
    )
    return result if isinstance(result, dict) else None


def ensure_plugin_project_contract(
    *,
    plugin_key: str,
    project_id: str | None,
    project_ref: str | None,
    workspace_id: str | None,
    auth_token: str | None,
    expected_event_storming_enabled: bool | None,
    command_id: str | None,
    ensure_project_contract_core: Callable[..., dict],
) -> dict | None:
    plugin = plugin_by_key(plugin_key)
    if plugin is None:
        return None
    fn = getattr(plugin, "service_ensure_project_contract", None)
    if not callable(fn):
        return None
    result = fn(
        project_id=project_id,
        project_ref=project_ref,
        workspace_id=workspace_id,
        auth_token=auth_token,
        expected_event_storming_enabled=expected_event_storming_enabled,
        command_id=command_id,
        ensure_project_contract_core=ensure_project_contract_core,
    )
    return result if isinstance(result, dict) else None


def is_delivery_workflow_active(
    *,
    skill_keys: set[str],
    gate_policy_source: str,
) -> bool:
    normalized_skill_keys = {
        str(item or "").strip().lower() for item in (skill_keys or set()) if str(item or "").strip()
    }
    return bool(
        is_delivery_skill_enabled(skill_keys=normalized_skill_keys)
        or str(gate_policy_source or "").strip() != "default"
    )


def is_delivery_skill_enabled(*, skill_keys: set[str]) -> bool:
    normalized_skill_keys = {
        str(item or "").strip().lower() for item in (skill_keys or set()) if str(item or "").strip()
    }
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "service_is_delivery_active", None)
        if not callable(fn):
            continue
        if bool(fn(skill_keys=normalized_skill_keys)):
            return True
    return False
