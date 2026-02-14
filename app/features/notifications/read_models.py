from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from shared.core import ActivityLog, Notification, serialize_notification, to_iso_utc


def list_notifications_read_model(db: Session, user_id: str, limit: int = 100) -> list[dict]:
    items = db.execute(select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at.desc()).limit(limit)).scalars().all()
    return [serialize_notification(n) for n in items]


def list_notifications_after_cursor_read_model(db: Session, user_id: str, cursor: str, limit: int = 50) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user_id)
    if cursor:
        cursor_notification = db.get(Notification, cursor)
        if cursor_notification:
            cursor_created_at = cursor_notification.created_at or datetime.min
            stmt = stmt.where(
                or_(
                    Notification.created_at > cursor_created_at,
                    and_(
                        Notification.created_at == cursor_created_at,
                        Notification.id > cursor,
                    ),
                )
            )
    return db.execute(stmt.order_by(Notification.created_at.asc(), Notification.id.asc()).limit(limit)).scalars().all()


def list_workspace_activity_after_id_read_model(db: Session, workspace_id: str, cursor: int, limit: int = 50) -> list[dict]:
    rows = (
        db.execute(
            select(ActivityLog)
            .where(
                ActivityLog.workspace_id == workspace_id,
                ActivityLog.id > cursor,
            )
            .order_by(ActivityLog.id.asc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "workspace_id": row.workspace_id,
            "project_id": row.project_id,
            "task_id": row.task_id,
            "action": row.action,
            "created_at": to_iso_utc(row.created_at),
        }
        for row in rows
    ]


def latest_workspace_activity_id_read_model(db: Session, workspace_id: str) -> int:
    latest = db.execute(
        select(func.max(ActivityLog.id)).where(ActivityLog.workspace_id == workspace_id)
    ).scalar_one_or_none()
    return int(latest or 0)
