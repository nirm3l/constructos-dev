from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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


def _build_daily_digest_message(tasks: list[Task], *, now: datetime, user_tz: ZoneInfo, local_today: str) -> str | None:
    local_today_date = now.astimezone(user_tz).date()
    today_count = 0
    overdue_count = 0
    high_count = 0
    actionable: list[tuple[int, datetime, str, str]] = []

    for task in tasks:
        task_due = None
        if task.due_date:
            task_due = task.due_date if task.due_date.tzinfo else task.due_date.replace(tzinfo=timezone.utc)

        is_high = task.priority == "High"
        if is_high:
            high_count += 1

        is_overdue = bool(task_due and task_due < now)
        is_due_today = bool(task_due and task_due.astimezone(user_tz).date() == local_today_date)

        if is_due_today:
            today_count += 1
        if is_overdue:
            overdue_count += 1

        if is_overdue:
            actionable.append((0, task_due or datetime.max.replace(tzinfo=timezone.utc), str(task.title or ""), "overdue"))
        elif is_due_today:
            actionable.append((1, task_due or datetime.max.replace(tzinfo=timezone.utc), str(task.title or ""), "due today"))
        elif is_high:
            actionable.append((2, task_due or datetime.max.replace(tzinfo=timezone.utc), str(task.title or ""), "high priority"))

    parts: list[str] = []
    if today_count > 0:
        parts.append(f"{today_count} due today")
    if overdue_count > 0:
        parts.append(f"{overdue_count} overdue")
    if high_count > 0:
        parts.append(f"{high_count} high priority")
    if not parts:
        return None

    actionable.sort(key=lambda item: (item[0], item[1], item[2].casefold()))
    top_actionable = actionable[:3]
    tasks_part = ""
    if top_actionable:
        formatted = ", ".join(f'"{title}" ({reason})' for _, _, title, reason in top_actionable)
        tasks_part = f" Top tasks: {formatted}."
    return f"Daily digest for {local_today}: {', '.join(parts)}.{tasks_part}"


def emit_system_notifications(db: Session, user, append_event_fn) -> int:
    if not bool(getattr(user, "notifications_enabled", True)):
        return 0

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

    if not _has_daily_digest_for_local_date(db, user_id=user.id, local_date=local_today):
        digest_message = _build_daily_digest_message(
            tasks,
            now=now,
            user_tz=user_tz,
            local_today=local_today,
        )
        if digest_message is not None:
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
