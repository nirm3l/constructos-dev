from __future__ import annotations

from typing import Any

from plugins.registry import list_workflow_plugins


def is_agent_project_role(role: str | None) -> bool:
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "runner_is_agent_project_role", None)
        if callable(fn) and bool(fn(role=role)):
            return True
    return False


def is_blocker_source_role(role: str | None) -> bool:
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "runner_is_blocker_source_role", None)
        if callable(fn) and bool(fn(role=role)):
            return True
    return False


def is_developer_role(role: str | None) -> bool:
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "runner_is_developer_role", None)
        if callable(fn) and bool(fn(role=role)):
            return True
    return False


def is_qa_role(role: str | None) -> bool:
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "runner_is_qa_role", None)
        if callable(fn) and bool(fn(role=role)):
            return True
    return False


def is_lead_role(role: str | None) -> bool:
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "runner_is_lead_role", None)
        if callable(fn) and bool(fn(role=role)):
            return True
    return False


def lead_role_for_escalation(*, db: Any, workspace_id: str, project_id: str | None) -> str | None:
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "runner_lead_role_for_project", None)
        if not callable(fn):
            continue
        role = str(fn(db=db, workspace_id=workspace_id, project_id=project_id) or "").strip()
        if role:
            return role
    return None


def preflight_error(
    *,
    db: Any,
    workspace_id: str,
    project_id: str | None,
    task_status: str | None,
    assignee_role: str | None,
    has_git_delivery_skill: bool,
    has_repo_context: bool,
) -> str | None:
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "runner_preflight_error", None)
        if not callable(fn):
            continue
        message = str(
            fn(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                task_status=task_status,
                assignee_role=assignee_role,
                has_git_delivery_skill=has_git_delivery_skill,
                has_repo_context=has_repo_context,
            )
            or ""
        ).strip()
        if message:
            return message
    return None


def is_kickoff_instruction(instruction: str | None) -> bool:
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "runner_is_kickoff_instruction", None)
        if callable(fn) and bool(fn(instruction=instruction)):
            return True
    return False


def is_recurring_oversight_task(state: dict | None) -> bool:
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "runner_is_recurring_oversight_task", None)
        if callable(fn) and bool(fn(state=state)):
            return True
    return False


def blocker_escalation_notification(
    *,
    blocked_task_id: str,
    blocked_title: str,
    blocked_role: str,
    blocked_status: str,
    blocked_error: str | None,
    queued_lead_tasks: int,
) -> dict[str, object]:
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "runner_blocker_escalation_notification", None)
        if not callable(fn):
            continue
        raw = fn(
            blocked_task_id=blocked_task_id,
            blocked_title=blocked_title,
            blocked_role=blocked_role,
            blocked_status=blocked_status,
            blocked_error=blocked_error,
            queued_lead_tasks=queued_lead_tasks,
        )
        if isinstance(raw, dict):
            return dict(raw)
    return {
        "message": (
            f"Workflow blocker detected: {blocked_title or blocked_task_id} "
            f"({blocked_role or 'agent'}, status={blocked_status or 'Blocked'}). "
            "Lead escalation run was queued."
        ),
        "dedupe_prefix": "workflow-blocker",
        "kind": "workflow_blocker_escalation",
        "source_event": "agents.runner.blocker_escalation",
    }


def normalize_success_outcome(
    *,
    action: str,
    summary: str,
    comment: str | None,
    instruction: str | None,
    assignee_role: str | None,
    task_state: dict | None,
) -> tuple[str, str, str | None]:
    normalized_action = str(action or "").strip() or "comment"
    normalized_summary = str(summary or "").strip()
    normalized_comment = None if comment is None else str(comment)
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "runner_normalize_success_outcome", None)
        if not callable(fn):
            continue
        raw = fn(
            action=normalized_action,
            summary=normalized_summary,
            comment=normalized_comment,
            instruction=instruction,
            assignee_role=assignee_role,
            task_state=task_state,
        )
        if not isinstance(raw, dict):
            continue
        maybe_action = str(raw.get("action") or "").strip()
        if maybe_action:
            normalized_action = maybe_action
        if "summary" in raw:
            normalized_summary = str(raw.get("summary") or "").strip()
        if "comment" in raw:
            raw_comment = raw.get("comment")
            normalized_comment = None if raw_comment is None else str(raw_comment)
    return normalized_action, normalized_summary, normalized_comment


def success_validation_error(
    *,
    db: Any,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    task_state: dict | None,
    assignee_role: str | None,
    action: str,
    summary: str,
    comment: str | None,
    has_git_delivery_skill: bool,
) -> str | None:
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "runner_success_validation_error", None)
        if not callable(fn):
            continue
        message = str(
            fn(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=task_id,
                task_state=task_state,
                assignee_role=assignee_role,
                action=action,
                summary=summary,
                comment=comment,
                has_git_delivery_skill=has_git_delivery_skill,
            )
            or ""
        ).strip()
        if message:
            return message
    return None
