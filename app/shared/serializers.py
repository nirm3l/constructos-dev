from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .contracts import (
    NoteCommandState,
    NoteDTO,
    NotificationDTO,
    ProjectRuleCommandState,
    ProjectRuleDTO,
    TaskCommandState,
    TaskDTO,
)
from .models import Note, Notification, Project, ProjectRule, SavedView, StoredEvent, Task
from .settings import DEFAULT_STATUSES


def to_iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def get_user_zoneinfo(user) -> ZoneInfo:
    try:
        return ZoneInfo(user.timezone or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def normalize_datetime_to_utc(value: datetime | None, user_tz: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=user_tz)
    return value.astimezone(timezone.utc)


def load_created_by(db: Session, aggregate_type: str, aggregate_id: str) -> str:
    row = db.execute(
        select(StoredEvent.meta).where(
            StoredEvent.aggregate_type == aggregate_type,
            StoredEvent.aggregate_id == aggregate_id,
            StoredEvent.version == 1,
        )
    ).first()
    if not row:
        return ""
    try:
        metadata = json.loads(row[0] or "{}")
    except Exception:
        metadata = {}
    return str(metadata.get("actor_id") or "")


def load_created_by_map(db: Session, aggregate_type: str, aggregate_ids: list[str]) -> dict[str, str]:
    ids = [aggregate_id for aggregate_id in aggregate_ids if aggregate_id]
    if not ids:
        return {}
    rows = db.execute(
        select(StoredEvent.aggregate_id, StoredEvent.meta).where(
            StoredEvent.aggregate_type == aggregate_type,
            StoredEvent.aggregate_id.in_(ids),
            StoredEvent.version == 1,
        )
    ).all()
    out: dict[str, str] = {}
    for aggregate_id, raw_meta in rows:
        try:
            metadata = json.loads(raw_meta or "{}")
        except Exception:
            metadata = {}
        out[str(aggregate_id)] = str(metadata.get("actor_id") or "")
    return out


def serialize_task(task: Task, created_by: str = "") -> dict[str, Any]:
    dto = TaskDTO(
        id=task.id,
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        due_date=to_iso_utc(task.due_date),
        assignee_id=task.assignee_id,
        labels=json.loads(task.labels or "[]"),
        subtasks=json.loads(task.subtasks or "[]"),
        attachments=json.loads(task.attachments or "[]"),
        external_refs=json.loads(task.external_refs or "[]"),
        attachment_refs=json.loads(task.attachment_refs or "[]"),
        recurring_rule=task.recurring_rule,
        task_type=task.task_type or "manual",
        scheduled_instruction=task.scheduled_instruction,
        scheduled_at_utc=to_iso_utc(task.scheduled_at_utc),
        schedule_timezone=task.schedule_timezone,
        schedule_state=task.schedule_state or "idle",
        last_schedule_run_at=to_iso_utc(task.last_schedule_run_at),
        last_schedule_error=task.last_schedule_error,
        archived=task.archived,
        completed_at=to_iso_utc(task.completed_at),
        created_at=to_iso_utc(task.created_at),
        updated_at=to_iso_utc(task.updated_at),
        created_by=created_by,
        order_index=task.order_index,
    )
    return asdict(dto)


def serialize_note(note: Note) -> dict[str, Any]:
    dto = NoteDTO(
        id=note.id,
        workspace_id=note.workspace_id,
        project_id=note.project_id,
        task_id=note.task_id,
        title=note.title,
        body=note.body or "",
        tags=json.loads(note.tags or "[]"),
        external_refs=json.loads(note.external_refs or "[]"),
        attachment_refs=json.loads(note.attachment_refs or "[]"),
        pinned=bool(note.pinned),
        archived=bool(note.archived),
        created_by=note.created_by,
        updated_by=note.updated_by,
        created_at=to_iso_utc(note.created_at),
        updated_at=to_iso_utc(note.updated_at),
    )
    return asdict(dto)


def serialize_notification(notification: Notification) -> dict[str, Any]:
    dto = NotificationDTO(
        id=notification.id,
        message=notification.message,
        is_read=notification.is_read,
        created_at=to_iso_utc(notification.created_at),
    )
    return asdict(dto)


def serialize_project_rule(rule: ProjectRule) -> dict[str, Any]:
    dto = ProjectRuleDTO(
        id=rule.id,
        workspace_id=rule.workspace_id,
        project_id=rule.project_id,
        title=rule.title,
        body=rule.body or "",
        created_by=rule.created_by,
        updated_by=rule.updated_by,
        created_at=to_iso_utc(rule.created_at),
        updated_at=to_iso_utc(rule.updated_at),
    )
    return asdict(dto)


def load_task_view(db: Session, task_id: str) -> dict[str, Any] | None:
    from .eventing import get_kurrent_client, rebuild_state

    if get_kurrent_client() is not None:
        state, _ = rebuild_state(db, "Task", task_id)
        if not state or state.get("is_deleted"):
            return None
        created_by = str(state.get("created_by") or "") or load_created_by(db, "Task", task_id)
        return {
            "id": task_id,
            "workspace_id": state.get("workspace_id"),
            "project_id": state.get("project_id"),
            "title": state.get("title"),
            "description": state.get("description", ""),
            "status": state.get("status", "To do"),
            "priority": state.get("priority", "Med"),
            "due_date": state.get("due_date"),
            "assignee_id": state.get("assignee_id"),
            "labels": state.get("labels", []),
            "subtasks": state.get("subtasks", []),
            "attachments": state.get("attachments", []),
            "external_refs": state.get("external_refs", []),
            "attachment_refs": state.get("attachment_refs", state.get("attachments", [])),
            "recurring_rule": state.get("recurring_rule"),
            "task_type": state.get("task_type", "manual"),
            "scheduled_instruction": state.get("scheduled_instruction"),
            "scheduled_at_utc": state.get("scheduled_at_utc"),
            "schedule_timezone": state.get("schedule_timezone"),
            "schedule_state": state.get("schedule_state", "idle"),
            "last_schedule_run_at": state.get("last_schedule_run_at"),
            "last_schedule_error": state.get("last_schedule_error"),
            "archived": bool(state.get("archived", False)),
            "completed_at": state.get("completed_at"),
            "created_at": None,
            "updated_at": None,
            "created_by": created_by,
            "order_index": int(state.get("order_index", 0)),
        }

    task = db.get(Task, task_id)
    if task and not task.is_deleted:
        return serialize_task(task, created_by=load_created_by(db, "Task", task_id))
    return None


def load_note_view(db: Session, note_id: str) -> dict[str, Any] | None:
    from .eventing import get_kurrent_client, rebuild_state

    if get_kurrent_client() is not None:
        state, _ = rebuild_state(db, "Note", note_id)
        if not state or state.get("is_deleted"):
            return None
        return {
            "id": note_id,
            "workspace_id": state.get("workspace_id"),
            "project_id": state.get("project_id"),
            "task_id": state.get("task_id"),
            "title": state.get("title") or "",
            "body": state.get("body", ""),
            "tags": state.get("tags", []),
            "external_refs": state.get("external_refs", []),
            "attachment_refs": state.get("attachment_refs", []),
            "pinned": bool(state.get("pinned", False)),
            "archived": bool(state.get("archived", False)),
            "created_by": state.get("created_by") or "",
            "updated_by": state.get("updated_by") or "",
            "created_at": None,
            "updated_at": None,
        }

    note = db.get(Note, note_id)
    if note and not note.is_deleted:
        return serialize_note(note)
    return None


def load_task_command_state(db: Session, task_id: str) -> TaskCommandState | None:
    from .eventing import get_kurrent_client, rebuild_state

    if get_kurrent_client() is None:
        task = db.get(Task, task_id)
        if not task:
            return None
        return TaskCommandState(
            id=task.id,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            status=task.status,
            archived=task.archived,
            is_deleted=task.is_deleted,
        )

    state, _ = rebuild_state(db, "Task", task_id)
    if not state:
        return None
    return TaskCommandState(
        id=task_id,
        workspace_id=state.get("workspace_id", ""),
        project_id=state.get("project_id"),
        status=state.get("status", "To do"),
        archived=bool(state.get("archived", False)),
        is_deleted=bool(state.get("is_deleted", False)),
    )


def load_note_command_state(db: Session, note_id: str) -> NoteCommandState | None:
    from .eventing import get_kurrent_client, rebuild_state

    if get_kurrent_client() is None:
        note = db.get(Note, note_id)
        if not note:
            return None
        return NoteCommandState(
            id=note.id,
            workspace_id=note.workspace_id,
            project_id=note.project_id,
            task_id=note.task_id,
            pinned=bool(note.pinned),
            archived=bool(note.archived),
            is_deleted=bool(note.is_deleted),
        )

    state, _ = rebuild_state(db, "Note", note_id)
    if not state:
        return None
    return NoteCommandState(
        id=note_id,
        workspace_id=state.get("workspace_id", ""),
        project_id=state.get("project_id"),
        task_id=state.get("task_id"),
        pinned=bool(state.get("pinned", False)),
        archived=bool(state.get("archived", False)),
        is_deleted=bool(state.get("is_deleted", False)),
    )


def load_project_view(db: Session, project_id: str) -> dict[str, Any] | None:
    project = db.get(Project, project_id)
    if project and not project.is_deleted:
        created_by = load_created_by(db, "Project", project.id)
        return {
            "id": project.id,
            "workspace_id": project.workspace_id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "custom_statuses": json.loads(project.custom_statuses or "[]"),
            "external_refs": json.loads(project.external_refs or "[]"),
            "attachment_refs": json.loads(project.attachment_refs or "[]"),
            "created_by": created_by,
            "created_at": to_iso_utc(project.created_at),
            "updated_at": to_iso_utc(project.updated_at),
        }

    from .eventing import get_kurrent_client, rebuild_state

    if get_kurrent_client() is None:
        return None
    state, _ = rebuild_state(db, "Project", project_id)
    if not state or state.get("is_deleted"):
        return None
    created_by = str(state.get("created_by") or "") or load_created_by(db, "Project", project_id)
    return {
        "id": project_id,
        "workspace_id": state.get("workspace_id"),
        "name": state.get("name"),
        "description": state.get("description", ""),
        "status": state.get("status", "Active"),
        "custom_statuses": state.get("custom_statuses", DEFAULT_STATUSES),
        "external_refs": state.get("external_refs", []),
        "attachment_refs": state.get("attachment_refs", []),
        "created_by": created_by,
        "created_at": None,
        "updated_at": None,
    }


def load_saved_view(db: Session, saved_view_id: str) -> dict[str, Any] | None:
    saved_view = db.get(SavedView, saved_view_id)
    if saved_view:
        return {
            "id": saved_view.id,
            "project_id": saved_view.project_id,
            "name": saved_view.name,
            "shared": saved_view.shared,
            "filters": json.loads(saved_view.filters or "{}"),
        }
    return None


def load_project_rule_view(db: Session, rule_id: str) -> dict[str, Any] | None:
    from .eventing import get_kurrent_client, rebuild_state

    if get_kurrent_client() is not None:
        state, _ = rebuild_state(db, "ProjectRule", rule_id)
        if not state or state.get("is_deleted"):
            return None
        return {
            "id": rule_id,
            "workspace_id": state.get("workspace_id"),
            "project_id": state.get("project_id"),
            "title": state.get("title", ""),
            "body": state.get("body", ""),
            "created_by": state.get("created_by") or "",
            "updated_by": state.get("updated_by") or "",
            "created_at": None,
            "updated_at": None,
        }

    rule = db.get(ProjectRule, rule_id)
    if rule and not rule.is_deleted:
        return serialize_project_rule(rule)
    return None


def load_project_rule_command_state(db: Session, rule_id: str) -> ProjectRuleCommandState | None:
    from .eventing import get_kurrent_client, rebuild_state

    if get_kurrent_client() is None:
        rule = db.get(ProjectRule, rule_id)
        if not rule:
            return None
        return ProjectRuleCommandState(
            id=rule.id,
            workspace_id=rule.workspace_id,
            project_id=rule.project_id,
            is_deleted=bool(rule.is_deleted),
        )

    state, _ = rebuild_state(db, "ProjectRule", rule_id)
    if not state:
        return None
    return ProjectRuleCommandState(
        id=rule_id,
        workspace_id=state.get("workspace_id", ""),
        project_id=state.get("project_id", ""),
        is_deleted=bool(state.get("is_deleted", False)),
    )


def export_tasks_response(db: Session, workspace_id: str, project_id: str, format: str):
    tasks = db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.project_id == project_id,
            Task.is_deleted == False,
        )
    ).scalars().all()
    if format == "csv":
        buff = io.StringIO()
        writer = csv.DictWriter(buff, fieldnames=["id", "title", "status", "priority", "due_date", "assignee_id", "project_id"])
        writer.writeheader()
        for t in tasks:
            writer.writerow(
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "priority": t.priority,
                    "due_date": to_iso_utc(t.due_date) or "",
                    "assignee_id": t.assignee_id,
                    "project_id": t.project_id,
                }
            )
        return StreamingResponse(iter([buff.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=tasks.csv"})
    return JSONResponse({"items": [serialize_task(t) for t in tasks]})
