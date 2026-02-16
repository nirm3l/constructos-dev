from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from shared.core import Task, ensure_role, get_user_zoneinfo, load_task_command_state, normalize_datetime_to_utc, rebuild_state, serialize_task
from shared.serializers import load_created_by_map


@dataclass(frozen=True, slots=True)
class TaskListQuery:
    workspace_id: str
    project_id: str
    specification_id: str | None = None
    view: str | None = None
    q: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    label: str | None = None
    assignee_id: str | None = None
    due_from: datetime | None = None
    due_to: datetime | None = None
    priority: str | None = None
    archived: bool = False
    limit: int = 30
    offset: int = 0


def list_tasks_read_model(db: Session, user, query: TaskListQuery) -> dict:
    stmt = select(Task).where(
        Task.workspace_id == query.workspace_id,
        Task.project_id == query.project_id,
        Task.is_deleted == False,
        Task.archived == query.archived,
    )
    now = datetime.now(timezone.utc)
    user_tz = get_user_zoneinfo(user)

    if query.q:
        stmt = stmt.where(or_(Task.title.ilike(f"%{query.q}%"), Task.description.ilike(f"%{query.q}%"), Task.labels.ilike(f"%{query.q}%")))
    if query.status:
        stmt = stmt.where(Task.status == query.status)
    if query.label:
        stmt = stmt.where(Task.labels.ilike(f"%{query.label}%"))
    if query.tags:
        for tag in query.tags:
            stmt = stmt.where(Task.labels.ilike(f'%"{tag}"%'))
    if query.assignee_id is not None:
        stmt = stmt.where(Task.assignee_id == query.assignee_id)
    if query.specification_id is not None:
        stmt = stmt.where(Task.specification_id == query.specification_id)
    if query.due_from:
        stmt = stmt.where(Task.due_date >= normalize_datetime_to_utc(query.due_from, user_tz))
    if query.due_to:
        stmt = stmt.where(Task.due_date <= normalize_datetime_to_utc(query.due_to, user_tz))
    if query.priority:
        stmt = stmt.where(Task.priority == query.priority)

    if query.view == "today":
        local_now = now.astimezone(user_tz)
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_end = local_start + timedelta(days=1)
        stmt = stmt.where(Task.due_date >= local_start.astimezone(timezone.utc), Task.due_date < local_end.astimezone(timezone.utc), Task.completed_at.is_(None))
    elif query.view == "upcoming":
        local_now = now.astimezone(user_tz)
        local_tomorrow_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        stmt = stmt.where(Task.due_date >= local_tomorrow_start.astimezone(timezone.utc), Task.completed_at.is_(None))
    elif query.view == "overdue":
        stmt = stmt.where(Task.due_date < now, Task.completed_at.is_(None))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    tasks = db.execute(stmt.order_by(Task.order_index.asc(), Task.created_at.desc()).limit(query.limit).offset(query.offset)).scalars().all()
    created_by_map = load_created_by_map(db, "Task", [t.id for t in tasks])
    return {
        "items": [serialize_task(t, created_by=created_by_map.get(t.id, "")) for t in tasks],
        "total": total,
        "limit": query.limit,
        "offset": query.offset,
    }


def get_task_automation_status_read_model(db: Session, user, task_id: str) -> dict:
    command_state = load_task_command_state(db, task_id)
    if not command_state or command_state.is_deleted:
        raise HTTPException(status_code=404, detail="Task not found")

    ensure_role(db, command_state.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})

    state, _ = rebuild_state(db, "Task", task_id)
    return {
        "task_id": task_id,
        "automation_state": state.get("automation_state", "idle"),
        "last_agent_run_at": state.get("last_agent_run_at"),
        "last_agent_error": state.get("last_agent_error"),
        "last_agent_comment": state.get("last_agent_comment"),
        "last_requested_instruction": state.get("last_requested_instruction"),
        "task_type": state.get("task_type", "manual"),
        "schedule_state": state.get("schedule_state", "idle"),
        "scheduled_at_utc": state.get("scheduled_at_utc"),
        "scheduled_instruction": state.get("scheduled_instruction"),
        "last_schedule_run_at": state.get("last_schedule_run_at"),
        "last_schedule_error": state.get("last_schedule_error"),
    }
