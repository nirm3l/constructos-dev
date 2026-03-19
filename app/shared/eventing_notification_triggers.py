from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from features.projects.domain import (
    EVENT_MEMBER_REMOVED as PROJECT_EVENT_MEMBER_REMOVED,
    EVENT_MEMBER_UPSERTED as PROJECT_EVENT_MEMBER_UPSERTED,
)
from features.tasks.domain import (
    EVENT_AUTOMATION_FAILED as TASK_EVENT_AUTOMATION_FAILED,
    EVENT_COMPLETED as TASK_EVENT_COMPLETED,
    EVENT_CREATED as TASK_EVENT_CREATED,
    EVENT_REOPENED as TASK_EVENT_REOPENED,
    EVENT_REORDERED as TASK_EVENT_REORDERED,
    EVENT_SCHEDULE_FAILED as TASK_EVENT_SCHEDULE_FAILED,
    EVENT_UPDATED as TASK_EVENT_UPDATED,
)

from .contracts import EventEnvelope
from .eventing_rebuild import rebuild_state
from .models import Project, Task, TaskWatcher
from .settings import AGENT_SYSTEM_USER_ID, CLAUDE_SYSTEM_USER_ID
from .typed_notifications import (
    NOTIFICATION_TYPE_PROJECT_MEMBERSHIP_CHANGED,
    NOTIFICATION_TYPE_TASK_ASSIGNED_TO_ME,
    NOTIFICATION_TYPE_TASK_AUTOMATION_FAILED,
    NOTIFICATION_TYPE_TASK_SCHEDULE_FAILED,
    NOTIFICATION_TYPE_WATCHED_TASK_STATUS_CHANGED,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    append_notification_created_event,
    filter_enabled_user_ids,
    normalize_optional_id,
)


def _task_state_snapshot(db: Session, task_id: str) -> dict[str, Any]:
    row = db.get(Task, task_id)
    if row is not None:
        return {
            "id": row.id,
            "workspace_id": row.workspace_id,
            "project_id": row.project_id,
            "title": row.title,
            "status": row.status,
            "assignee_id": row.assignee_id,
            "assigned_agent_code": row.assigned_agent_code,
            "scheduled_at_utc": row.scheduled_at_utc.isoformat() if row.scheduled_at_utc else None,
        }
    state, _ = rebuild_state(db, "Task", task_id)
    if isinstance(state, dict):
        return dict(state)
    return {}


def prepare_event_payload_for_notification_triggers(
    db: Session,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized_payload = dict(payload or {})
    if aggregate_type != "Task":
        return normalized_payload

    previous = _task_state_snapshot(db, aggregate_id)
    previous_status = previous.get("status")

    if event_type == TASK_EVENT_UPDATED:
        if "status" in normalized_payload:
            if "from_status" not in normalized_payload:
                normalized_payload["from_status"] = previous_status
            if "to_status" not in normalized_payload:
                normalized_payload["to_status"] = normalized_payload.get("status")
        if "assignee_id" in normalized_payload and "previous_assignee_id" not in normalized_payload:
            normalized_payload["previous_assignee_id"] = previous.get("assignee_id")
    elif event_type == TASK_EVENT_REORDERED and "status" in normalized_payload:
        if "from_status" not in normalized_payload:
            normalized_payload["from_status"] = previous_status
        if "to_status" not in normalized_payload:
            normalized_payload["to_status"] = normalized_payload.get("status")
    elif event_type == TASK_EVENT_COMPLETED:
        if "from_status" not in normalized_payload:
            normalized_payload["from_status"] = previous_status
        if "to_status" not in normalized_payload:
            normalized_payload["to_status"] = "Done"
    elif event_type == TASK_EVENT_REOPENED:
        if "from_status" not in normalized_payload:
            normalized_payload["from_status"] = previous_status
        if "to_status" not in normalized_payload:
            normalized_payload["to_status"] = normalized_payload.get("status") or "To Do"
    return normalized_payload


def _short_error(text: str, limit: int = 120) -> str:
    value = " ".join(str(text or "").split())
    if not value:
        return "Unknown error"
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 3)] + "..."


def _hash_error(text: str) -> str:
    normalized = " ".join(str(text or "").split()).lower()
    if not normalized:
        normalized = "unknown-error"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _hour_bucket(iso_timestamp: str | None) -> str:
    if not iso_timestamp:
        dt = datetime.now(timezone.utc)
    else:
        try:
            dt = datetime.fromisoformat(str(iso_timestamp))
        except Exception:
            dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%d%H")


def _collect_task_watcher_ids(db: Session, task_id: str, *, exclude_user_id: str | None = None) -> list[str]:
    rows = db.execute(
        select(TaskWatcher.user_id).where(TaskWatcher.task_id == task_id)
    ).scalars().all()
    excluded = normalize_optional_id(exclude_user_id)
    out: list[str] = []
    seen: set[str] = set()
    for raw in rows:
        user_id = normalize_optional_id(raw)
        if not user_id:
            continue
        if excluded and user_id == excluded:
            continue
        if user_id in seen:
            continue
        seen.add(user_id)
        out.append(user_id)
    return out


def _emit_task_assigned_to_me(
    db: Session,
    env: EventEnvelope,
    *,
    append_event_fn: Callable[..., Any],
    task_state: dict[str, Any],
) -> None:
    payload = dict(env.payload or {})
    metadata = dict(env.metadata or {})
    actor_id = normalize_optional_id(metadata.get("actor_id"))
    task_id = normalize_optional_id(env.aggregate_id) or normalize_optional_id(payload.get("task_id")) or normalize_optional_id(metadata.get("task_id"))
    if not task_id:
        return

    previous_assignee_token = "none"
    if env.event_type == TASK_EVENT_CREATED:
        assignee_id = normalize_optional_id(payload.get("assignee_id") or task_state.get("assignee_id"))
        previous_assignee_id = None
    else:
        if "assignee_id" not in payload:
            return
        assignee_id = normalize_optional_id(payload.get("assignee_id"))
        previous_assignee_id = normalize_optional_id(payload.get("previous_assignee_id"))
        if assignee_id == previous_assignee_id:
            return
    if previous_assignee_id:
        previous_assignee_token = previous_assignee_id

    if not assignee_id:
        return
    effective_assigned_agent_code = normalize_optional_id(
        payload.get("assigned_agent_code") if "assigned_agent_code" in payload else task_state.get("assigned_agent_code")
    )
    if effective_assigned_agent_code:
        return
    if actor_id and assignee_id == actor_id:
        return
    if assignee_id not in filter_enabled_user_ids(db, [assignee_id]):
        return

    workspace_id = normalize_optional_id(payload.get("workspace_id")) or normalize_optional_id(metadata.get("workspace_id")) or normalize_optional_id(task_state.get("workspace_id"))
    project_id = normalize_optional_id(payload.get("project_id")) or normalize_optional_id(metadata.get("project_id")) or normalize_optional_id(task_state.get("project_id"))
    title = str(task_state.get("title") or payload.get("title") or "Task").strip() or "Task"
    status = str(task_state.get("status") or payload.get("status") or "").strip() or None
    dedupe_key = f"task-assigned:{task_id}:{previous_assignee_token}:{assignee_id}"
    append_notification_created_event(
        db,
        append_event_fn=append_event_fn,
        user_id=assignee_id,
        actor_id=actor_id,
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        message=f'You were assigned to "{title}".',
        notification_type=NOTIFICATION_TYPE_TASK_ASSIGNED_TO_ME,
        severity=SEVERITY_INFO,
        dedupe_key=dedupe_key,
        payload={
            "task_id": task_id,
            "project_id": project_id,
            "assignee_id": assignee_id,
            "title": title,
            "status": status,
        },
        source_event=env.event_type,
    )


def _emit_watched_task_status_changed(
    db: Session,
    env: EventEnvelope,
    *,
    append_event_fn: Callable[..., Any],
    task_state: dict[str, Any],
) -> None:
    payload = dict(env.payload or {})
    metadata = dict(env.metadata or {})
    if env.event_type != TASK_EVENT_UPDATED or "status" not in payload:
        return

    to_status = str(payload.get("status") or "").strip()
    if not to_status:
        return
    from_status = str(payload.get("from_status") or "").strip() or None
    if from_status and from_status == to_status:
        return

    task_id = normalize_optional_id(env.aggregate_id) or normalize_optional_id(payload.get("task_id")) or normalize_optional_id(metadata.get("task_id"))
    if not task_id:
        return
    actor_id = normalize_optional_id(metadata.get("actor_id"))
    watcher_ids = _collect_task_watcher_ids(db, task_id, exclude_user_id=actor_id)
    if not watcher_ids:
        return
    target_user_ids = filter_enabled_user_ids(db, watcher_ids)
    if not target_user_ids:
        return

    workspace_id = normalize_optional_id(payload.get("workspace_id")) or normalize_optional_id(metadata.get("workspace_id")) or normalize_optional_id(task_state.get("workspace_id"))
    project_id = normalize_optional_id(payload.get("project_id")) or normalize_optional_id(metadata.get("project_id")) or normalize_optional_id(task_state.get("project_id"))
    title = str(task_state.get("title") or payload.get("title") or "Task").strip() or "Task"
    for watcher_id in target_user_ids:
        dedupe_key = f"watch-status:{task_id}:{watcher_id}:{to_status}:{env.version}"
        if from_status:
            message = f'Task "{title}" status changed from {from_status} to {to_status}.'
        else:
            message = f'Task "{title}" status changed to {to_status}.'
        append_notification_created_event(
            db,
            append_event_fn=append_event_fn,
            user_id=watcher_id,
            actor_id=actor_id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=task_id,
            message=message,
            notification_type=NOTIFICATION_TYPE_WATCHED_TASK_STATUS_CHANGED,
            severity=SEVERITY_INFO,
            dedupe_key=dedupe_key,
            payload={
                "task_id": task_id,
                "project_id": project_id,
                "from_status": from_status,
                "to_status": to_status,
                "title": title,
            },
            source_event=env.event_type,
        )


def _collect_task_failure_recipients(
    db: Session,
    *,
    task_id: str,
    assignee_id: str | None,
    actor_id: str | None,
) -> list[str]:
    raw_ids: list[str] = []
    normalized_assignee = normalize_optional_id(assignee_id)
    if normalized_assignee:
        raw_ids.append(normalized_assignee)
    raw_ids.extend(_collect_task_watcher_ids(db, task_id))
    deduped = list(dict.fromkeys(uid for uid in raw_ids if uid))
    filtered = [uid for uid in deduped if not actor_id or uid != actor_id]
    return filter_enabled_user_ids(db, filtered)


def _emit_task_failure_notification(
    db: Session,
    env: EventEnvelope,
    *,
    append_event_fn: Callable[..., Any],
    task_state: dict[str, Any],
    notification_type: str,
    dedupe_prefix: str,
) -> None:
    payload = dict(env.payload or {})
    metadata = dict(env.metadata or {})
    actor_id = normalize_optional_id(metadata.get("actor_id"))
    task_id = normalize_optional_id(env.aggregate_id) or normalize_optional_id(payload.get("task_id")) or normalize_optional_id(metadata.get("task_id"))
    if not task_id:
        return

    workspace_id = normalize_optional_id(payload.get("workspace_id")) or normalize_optional_id(metadata.get("workspace_id")) or normalize_optional_id(task_state.get("workspace_id"))
    project_id = normalize_optional_id(payload.get("project_id")) or normalize_optional_id(metadata.get("project_id")) or normalize_optional_id(task_state.get("project_id"))
    assignee_id = normalize_optional_id(task_state.get("assignee_id") or payload.get("assignee_id"))
    recipients = _collect_task_failure_recipients(
        db,
        task_id=task_id,
        assignee_id=assignee_id,
        actor_id=actor_id,
    )
    if not recipients:
        return

    title = str(task_state.get("title") or payload.get("title") or "Task").strip() or "Task"
    error = str(payload.get("error") or task_state.get("last_schedule_error") or task_state.get("last_automation_error") or "Unknown error").strip()
    summary = str(payload.get("summary") or "").strip() or None
    failed_at = str(payload.get("failed_at") or datetime.now(timezone.utc).isoformat())
    error_hash = _hash_error(error)
    hour_bucket = _hour_bucket(failed_at)
    dedupe_key = f"{dedupe_prefix}:{task_id}:{error_hash}:{hour_bucket}"

    for target_user_id in recipients:
        if notification_type == NOTIFICATION_TYPE_TASK_AUTOMATION_FAILED:
            message = f'Automation failed for "{title}": {_short_error(error)}'
        else:
            message = f'Scheduled run failed for "{title}": {_short_error(error)}'
        append_notification_created_event(
            db,
            append_event_fn=append_event_fn,
            user_id=target_user_id,
            actor_id=actor_id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=task_id,
            message=message,
            notification_type=notification_type,
            severity=SEVERITY_WARNING,
            dedupe_key=dedupe_key,
            payload={
                "task_id": task_id,
                "project_id": project_id,
                "error": error,
                "summary": summary,
                "failed_at": failed_at,
                "scheduled_at_utc": task_state.get("scheduled_at_utc"),
            },
            source_event=env.event_type,
        )


def _emit_project_membership_changed(
    db: Session,
    env: EventEnvelope,
    *,
    append_event_fn: Callable[..., Any],
) -> None:
    payload = dict(env.payload or {})
    metadata = dict(env.metadata or {})
    target_user_id = normalize_optional_id(payload.get("user_id"))
    if not target_user_id:
        return
    if target_user_id not in filter_enabled_user_ids(db, [target_user_id]):
        return

    actor_id = normalize_optional_id(metadata.get("actor_id"))
    project_id = normalize_optional_id(payload.get("project_id")) or normalize_optional_id(metadata.get("project_id")) or normalize_optional_id(env.aggregate_id)
    workspace_id = normalize_optional_id(payload.get("workspace_id")) or normalize_optional_id(metadata.get("workspace_id"))
    role = str(payload.get("role") or "").strip() or None
    action = "removed" if env.event_type == PROJECT_EVENT_MEMBER_REMOVED else "upserted"
    if action == "upserted" and actor_id and actor_id == target_user_id:
        return
    if action == "upserted" and actor_id in {AGENT_SYSTEM_USER_ID, CLAUDE_SYSTEM_USER_ID} and project_id:
        project_row = db.get(Project, project_id)
        if project_row is not None and isinstance(project_row.created_at, datetime):
            age_seconds = (datetime.now(timezone.utc) - project_row.created_at.astimezone(timezone.utc)).total_seconds()
            if age_seconds <= 60:
                return
    role_for_key = role or "none"
    dedupe_key = f"project-member:{project_id}:{target_user_id}:{action}:{role_for_key}:{env.version}"
    if action == "removed":
        message = "You were removed from a project."
    elif role:
        message = f"Your project membership was updated to role {role}."
    else:
        message = "Your project membership was updated."
    append_notification_created_event(
        db,
        append_event_fn=append_event_fn,
        user_id=target_user_id,
        actor_id=actor_id,
        workspace_id=workspace_id,
        project_id=project_id,
        message=message,
        notification_type=NOTIFICATION_TYPE_PROJECT_MEMBERSHIP_CHANGED,
        severity=SEVERITY_INFO,
        dedupe_key=dedupe_key,
        payload={
            "project_id": project_id,
            "workspace_id": workspace_id,
            "action": action,
            "role": role,
            "actor_id": actor_id,
        },
        source_event=env.event_type,
    )


def emit_typed_notifications_for_event(
    db: Session,
    env: EventEnvelope,
    *,
    append_event_fn: Callable[..., Any],
) -> None:
    if env.aggregate_type == "Notification":
        return

    if env.aggregate_type == "Task":
        task_id = normalize_optional_id(env.aggregate_id)
        task_state = _task_state_snapshot(db, task_id) if task_id else {}
        if env.event_type in {TASK_EVENT_CREATED, TASK_EVENT_UPDATED}:
            _emit_task_assigned_to_me(db, env, append_event_fn=append_event_fn, task_state=task_state)
        if env.event_type == TASK_EVENT_UPDATED:
            _emit_watched_task_status_changed(db, env, append_event_fn=append_event_fn, task_state=task_state)
        if env.event_type == TASK_EVENT_AUTOMATION_FAILED:
            _emit_task_failure_notification(
                db,
                env,
                append_event_fn=append_event_fn,
                task_state=task_state,
                notification_type=NOTIFICATION_TYPE_TASK_AUTOMATION_FAILED,
                dedupe_prefix="automation-failed",
            )
        if env.event_type == TASK_EVENT_SCHEDULE_FAILED:
            _emit_task_failure_notification(
                db,
                env,
                append_event_fn=append_event_fn,
                task_state=task_state,
                notification_type=NOTIFICATION_TYPE_TASK_SCHEDULE_FAILED,
                dedupe_prefix="schedule-failed",
            )
        return

    if env.aggregate_type == "Project" and env.event_type in {PROJECT_EVENT_MEMBER_UPSERTED, PROJECT_EVENT_MEMBER_REMOVED}:
        _emit_project_membership_changed(db, env, append_event_fn=append_event_fn)
