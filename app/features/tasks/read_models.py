from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from shared.core import Task, get_user_zoneinfo, normalize_datetime_to_utc, serialize_task


@dataclass(frozen=True, slots=True)
class TaskListQuery:
    workspace_id: str
    view: str | None = None
    q: str | None = None
    status: str | None = None
    project_id: str | None = None
    label: str | None = None
    assignee_id: str | None = None
    due_from: datetime | None = None
    due_to: datetime | None = None
    priority: str | None = None
    archived: bool = False
    limit: int = 30
    offset: int = 0


def list_tasks_read_model(db: Session, user, query: TaskListQuery) -> dict:
    stmt = select(Task).where(Task.workspace_id == query.workspace_id, Task.is_deleted == False, Task.archived == query.archived)
    now = datetime.now(timezone.utc)
    user_tz = get_user_zoneinfo(user)

    if query.q:
        stmt = stmt.where(or_(Task.title.ilike(f"%{query.q}%"), Task.description.ilike(f"%{query.q}%"), Task.labels.ilike(f"%{query.q}%")))
    if query.status:
        stmt = stmt.where(Task.status == query.status)
    if query.project_id is not None:
        stmt = stmt.where(Task.project_id == query.project_id)
    if query.label:
        stmt = stmt.where(Task.labels.ilike(f"%{query.label}%"))
    if query.assignee_id is not None:
        stmt = stmt.where(Task.assignee_id == query.assignee_id)
    if query.due_from:
        stmt = stmt.where(Task.due_date >= normalize_datetime_to_utc(query.due_from, user_tz))
    if query.due_to:
        stmt = stmt.where(Task.due_date <= normalize_datetime_to_utc(query.due_to, user_tz))
    if query.priority:
        stmt = stmt.where(Task.priority == query.priority)

    if query.view == "inbox":
        stmt = stmt.where(Task.project_id.is_(None))
    elif query.view == "today":
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
    return {"items": [serialize_task(t) for t in tasks], "total": total, "limit": query.limit, "offset": query.offset}
