from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from features.notifications.domain import EVENT_CREATED as NOTIFICATION_EVENT_CREATED
from .eventing_store import allocate_id
from .models import Notification, Task, WorkspaceMember
from .serializers import get_user_zoneinfo


def _maybe_append_system_notification_event(
    db: Session,
    *,
    user_id: str,
    workspace_id: str,
    project_id: str | None = None,
    task_id: str | None = None,
    note_id: str | None = None,
    specification_id: str | None = None,
    message: str,
    lookback_hours: int,
    append_event_fn,
) -> bool:
    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    existing = db.execute(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.message == message,
            Notification.created_at >= since,
        )
    ).first()
    if existing:
        return False

    nid = allocate_id(db)
    payload = {
        "user_id": user_id,
        "message": message,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "task_id": task_id,
        "note_id": note_id,
        "specification_id": specification_id,
    }
    append_event_fn(
        db,
        aggregate_type="Notification",
        aggregate_id=nid,
        event_type=NOTIFICATION_EVENT_CREATED,
        payload=payload,
        metadata={
            "actor_id": user_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": task_id,
            "note_id": note_id,
            "specification_id": specification_id,
        },
        expected_version=0,
    )
    db.flush()
    return True


def _has_daily_digest_for_local_date(db: Session, *, user_id: str, local_date: str) -> bool:
    digest_prefix = f"Daily digest for {local_date}:%"
    existing = db.execute(
        select(Notification.id).where(
            Notification.user_id == user_id,
            Notification.message.like(digest_prefix),
        ).limit(1)
    ).first()
    return existing is not None


def emit_system_notifications(db: Session, user, append_event_fn) -> int:
    memberships = db.execute(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)).scalars().all()
    workspace_ids = [m.workspace_id for m in memberships]
    if not workspace_ids:
        return 0

    now = datetime.now(timezone.utc)
    user_tz = get_user_zoneinfo(user)
    local_today = now.astimezone(user_tz).date().isoformat()

    tasks = db.execute(
        select(Task).where(
            Task.workspace_id.in_(workspace_ids),
            Task.is_deleted == False,
            Task.archived == False,
            Task.status != "Done",
        )
    ).scalars().all()

    created = 0
    first_workspace_id = workspace_ids[0]

    for task in tasks:
        if not task.due_date:
            continue
        task_due = task.due_date if task.due_date.tzinfo else task.due_date.replace(tzinfo=timezone.utc)
        if now <= task_due <= now + timedelta(hours=1):
            if _maybe_append_system_notification_event(
                db,
                user_id=user.id,
                workspace_id=task.workspace_id or first_workspace_id,
                project_id=task.project_id,
                task_id=task.id,
                message=f'Task "{task.title}" is due within 1 hour.',
                lookback_hours=6,
                append_event_fn=append_event_fn,
            ):
                created += 1
        if task_due < now:
            if _maybe_append_system_notification_event(
                db,
                user_id=user.id,
                workspace_id=task.workspace_id or first_workspace_id,
                project_id=task.project_id,
                task_id=task.id,
                message=f'Overdue today ({local_today}): "{task.title}"',
                lookback_hours=28,
                append_event_fn=append_event_fn,
            ):
                created += 1

    today_count = 0
    overdue_count = 0
    high_count = 0
    for task in tasks:
        task_due = None
        if task.due_date:
            task_due = task.due_date if task.due_date.tzinfo else task.due_date.replace(tzinfo=timezone.utc)
        if task.priority == "High":
            high_count += 1
        if task_due and task_due < now:
            overdue_count += 1
        if task_due and task_due.astimezone(user_tz).date().isoformat() == local_today:
            today_count += 1

    if not _has_daily_digest_for_local_date(db, user_id=user.id, local_date=local_today):
        digest_message = f"Daily digest for {local_today}: {today_count} due today, {overdue_count} overdue, {high_count} high priority."
        if _maybe_append_system_notification_event(
            db,
            user_id=user.id,
            workspace_id=first_workspace_id,
            message=digest_message,
            lookback_hours=28,
            append_event_fn=append_event_fn,
        ):
            created += 1

    if created:
        db.commit()
    return created
