from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from features.notifications.domain import EVENT_CREATED as NOTIFICATION_EVENT_CREATED
from features.licensing.read_models import license_status_read_model
from .eventing_store import allocate_id
from .models import Notification, Task, WorkspaceMember
from .serializers import get_user_zoneinfo
from .typed_notifications import (
    NOTIFICATION_TYPE_LICENSE_GRACE_ENDING_SOON,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    append_notification_created_event,
)


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


def _license_grace_threshold_hours(hours_remaining: int) -> int | None:
    if hours_remaining <= 6:
        return 6
    if hours_remaining <= 24:
        return 24
    if hours_remaining <= 72:
        return 72
    return None


def _maybe_append_license_grace_notification(
    db: Session,
    *,
    user_id: str,
    workspace_id: str,
    append_event_fn,
) -> bool:
    license_payload = license_status_read_model(db)
    if str(license_payload.get("status") or "").strip().lower() != "grace":
        return False
    installation_id = str(license_payload.get("installation_id") or "").strip()
    grace_ends_at_raw = str(license_payload.get("grace_ends_at") or "").strip()
    if not installation_id or not grace_ends_at_raw:
        return False
    try:
        grace_ends_at = datetime.fromisoformat(grace_ends_at_raw)
    except Exception:
        return False
    if grace_ends_at.tzinfo is None:
        grace_ends_at = grace_ends_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    total_seconds = (grace_ends_at.astimezone(timezone.utc) - now).total_seconds()
    if total_seconds <= 0:
        return False
    hours_remaining = max(1, int((total_seconds + 3599) // 3600))
    threshold_hours = _license_grace_threshold_hours(hours_remaining)
    if threshold_hours is None:
        return False

    severity = SEVERITY_CRITICAL if threshold_hours <= 6 else SEVERITY_WARNING
    dedupe_key = f"license-grace:{installation_id}:{threshold_hours}"
    message = f"License grace period ends in about {hours_remaining}h."
    return append_notification_created_event(
        db,
        append_event_fn=append_event_fn,
        user_id=user_id,
        actor_id=user_id,
        workspace_id=workspace_id,
        message=message,
        notification_type=NOTIFICATION_TYPE_LICENSE_GRACE_ENDING_SOON,
        severity=severity,
        dedupe_key=dedupe_key,
        payload={
            "installation_id": installation_id,
            "grace_ends_at": grace_ends_at.astimezone(timezone.utc).isoformat(),
            "hours_remaining": hours_remaining,
            "status": str(license_payload.get("status") or "").strip().lower(),
        },
        source_event="LicenseStatusPolled",
    )


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

    is_admin_member = any(str(m.role or "").strip().lower() in {"owner", "admin"} for m in memberships)
    if is_admin_member:
        admin_workspace_id = next(
            (str(m.workspace_id or "").strip() for m in memberships if str(m.role or "").strip().lower() in {"owner", "admin"}),
            first_workspace_id,
        )
        if admin_workspace_id and _maybe_append_license_grace_notification(
            db,
            user_id=user.id,
            workspace_id=admin_workspace_id,
            append_event_fn=append_event_fn,
        ):
            created += 1

    if created:
        db.commit()
    return created
