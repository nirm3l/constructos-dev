from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from features.notifications.domain import EVENT_CREATED as NOTIFICATION_EVENT_CREATED

from .eventing_store import allocate_id
from .models import Notification, User

DEFAULT_NOTIFICATION_TYPE = "Legacy"
DEFAULT_NOTIFICATION_SEVERITY = "info"
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"
NOTIFICATION_SEVERITIES = {SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL}

NOTIFICATION_TYPE_TASK_ASSIGNED_TO_ME = "TaskAssignedToMe"
NOTIFICATION_TYPE_WATCHED_TASK_STATUS_CHANGED = "WatchedTaskStatusChanged"
NOTIFICATION_TYPE_TASK_AUTOMATION_FAILED = "TaskAutomationFailed"
NOTIFICATION_TYPE_TASK_SCHEDULE_FAILED = "TaskScheduleFailed"
NOTIFICATION_TYPE_PROJECT_MEMBERSHIP_CHANGED = "ProjectMembershipChanged"
NOTIFICATION_TYPE_LICENSE_GRACE_ENDING_SOON = "LicenseGraceEndingSoon"


def normalize_optional_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def normalize_notification_type(value: Any) -> str:
    text = str(value or "").strip()
    return text or DEFAULT_NOTIFICATION_TYPE


def normalize_severity(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in NOTIFICATION_SEVERITIES:
        return text
    return DEFAULT_NOTIFICATION_SEVERITY


def normalize_dedupe_key(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def dumps_payload_json(payload: dict[str, Any] | None) -> str:
    data = payload if isinstance(payload, dict) else {}
    try:
        return json.dumps(data, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    except Exception:
        return "{}"


def loads_payload_json(payload_json: Any) -> dict[str, Any]:
    if not str(payload_json or "").strip():
        return {}
    try:
        parsed = json.loads(str(payload_json))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def filter_enabled_user_ids(db: Session, user_ids: Iterable[str]) -> list[str]:
    normalized = [uid for uid in {str(value or "").strip() for value in user_ids} if uid]
    if not normalized:
        return []
    rows = db.execute(
        select(User.id).where(
            User.id.in_(normalized),
            User.is_active == True,  # noqa: E712
            User.notifications_enabled == True,  # noqa: E712
        )
    ).scalars().all()
    return [str(uid) for uid in rows]


def has_notification_dedupe_key(db: Session, *, user_id: str, dedupe_key: str) -> bool:
    if not user_id or not dedupe_key:
        return False
    existing = db.execute(
        select(Notification.id).where(
            and_(
                Notification.user_id == user_id,
                Notification.dedupe_key == dedupe_key,
            )
        ).limit(1)
    ).scalar_one_or_none()
    return existing is not None


def append_notification_created_event(
    db: Session,
    *,
    append_event_fn: Callable[..., Any],
    user_id: str,
    message: str,
    actor_id: str | None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    task_id: str | None = None,
    note_id: str | None = None,
    specification_id: str | None = None,
    notification_type: str | None = None,
    severity: str | None = None,
    dedupe_key: str | None = None,
    payload: dict[str, Any] | None = None,
    source_event: str | None = None,
) -> bool:
    target_user_id = normalize_optional_id(user_id)
    if not target_user_id:
        return False
    dedupe = normalize_dedupe_key(dedupe_key)
    if dedupe and has_notification_dedupe_key(db, user_id=target_user_id, dedupe_key=dedupe):
        return False

    notification_id = allocate_id(db)
    event_payload = {
        "user_id": target_user_id,
        "message": str(message or "").strip() or "Notification",
        "workspace_id": normalize_optional_id(workspace_id),
        "project_id": normalize_optional_id(project_id),
        "task_id": normalize_optional_id(task_id),
        "note_id": normalize_optional_id(note_id),
        "specification_id": normalize_optional_id(specification_id),
        "notification_type": normalize_notification_type(notification_type),
        "severity": normalize_severity(severity),
        "dedupe_key": dedupe,
        "payload_json": dumps_payload_json(payload),
        "source_event": str(source_event or "").strip() or None,
    }
    event_metadata = {
        "actor_id": str(actor_id or target_user_id),
        "workspace_id": event_payload["workspace_id"],
        "project_id": event_payload["project_id"],
        "task_id": event_payload["task_id"],
        "note_id": event_payload["note_id"],
        "specification_id": event_payload["specification_id"],
    }
    append_event_fn(
        db,
        aggregate_type="Notification",
        aggregate_id=notification_id,
        event_type=NOTIFICATION_EVENT_CREATED,
        payload=event_payload,
        metadata=event_metadata,
        expected_version=0,
    )
    return True
