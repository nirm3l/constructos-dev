from __future__ import annotations

import os
import time
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from features.bootstrap.read_models import bootstrap_payload_read_model
from .eventing import append_event, current_version, emit_system_notifications, get_kurrent_client
from features.projects.domain import EVENT_CREATED as PROJECT_EVENT_CREATED
from features.tasks.domain import EVENT_CREATED as TASK_EVENT_CREATED
from .models import Base, Note, Project, ProjectTagIndex, SessionLocal, Task, User, Workspace, WorkspaceMember, engine
from .serializers import to_iso_utc
from .settings import (
    AGENT_SYSTEM_FULL_NAME,
    AGENT_SYSTEM_USER_ID,
    AGENT_SYSTEM_USERNAME,
    BOOTSTRAP_PROJECT_ID,
    BOOTSTRAP_TASK_ID,
    BOOTSTRAP_FULL_NAME,
    BOOTSTRAP_USERNAME,
    BOOTSTRAP_WORKSPACE_ID,
    DB_PATH,
    DATABASE_URL,
    DEFAULT_USER_ID,
    DEFAULT_STATUSES,
)


def ensure_system_users(db: Session):
    if not db.get(User, AGENT_SYSTEM_USER_ID):
        db.add(
            User(
                id=AGENT_SYSTEM_USER_ID,
                username=AGENT_SYSTEM_USERNAME,
                full_name=AGENT_SYSTEM_FULL_NAME,
                timezone="UTC",
                theme="dark",
            )
        )
    workspace = db.get(Workspace, BOOTSTRAP_WORKSPACE_ID)
    if workspace:
        membership = db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == BOOTSTRAP_WORKSPACE_ID,
                WorkspaceMember.user_id == AGENT_SYSTEM_USER_ID,
            )
        ).scalar_one_or_none()
        if not membership:
            db.add(WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=AGENT_SYSTEM_USER_ID, role="Member"))
    db.commit()


def ensure_task_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("tasks")}
    required_columns = {
        "task_type": "ALTER TABLE tasks ADD COLUMN task_type VARCHAR(32) DEFAULT 'manual'",
        "scheduled_instruction": "ALTER TABLE tasks ADD COLUMN scheduled_instruction TEXT",
        "scheduled_at_utc": "ALTER TABLE tasks ADD COLUMN scheduled_at_utc TIMESTAMP WITH TIME ZONE",
        "schedule_timezone": "ALTER TABLE tasks ADD COLUMN schedule_timezone VARCHAR(64)",
        "schedule_state": "ALTER TABLE tasks ADD COLUMN schedule_state VARCHAR(16) DEFAULT 'idle'",
        "last_schedule_run_at": "ALTER TABLE tasks ADD COLUMN last_schedule_run_at TIMESTAMP WITH TIME ZONE",
        "last_schedule_error": "ALTER TABLE tasks ADD COLUMN last_schedule_error TEXT",
    }
    for column, ddl in required_columns.items():
        if column not in existing:
            db.execute(text(ddl))
    db.commit()


def ensure_saved_view_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("saved_views")}
    if "project_id" not in existing:
        db.execute(text("ALTER TABLE saved_views ADD COLUMN project_id VARCHAR(36)"))
    db.commit()


def ensure_task_comment_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("task_comments")}
    if "event_version" not in existing:
        db.execute(text("ALTER TABLE task_comments ADD COLUMN event_version INTEGER"))
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_task_comments_task_event_version ON task_comments(task_id, event_version)"))
    db.commit()


def bootstrap_data():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_task_table_columns(db)
        ensure_saved_view_table_columns(db)
        ensure_task_comment_table_columns(db)
        ensure_system_users(db)
        default_user = db.get(User, DEFAULT_USER_ID)
        if not default_user:
            db.add_all(
                [
                    User(id=DEFAULT_USER_ID, username=BOOTSTRAP_USERNAME, full_name=BOOTSTRAP_FULL_NAME, timezone="Europe/Sarajevo", theme="light"),
                    Workspace(id=BOOTSTRAP_WORKSPACE_ID, name="My Workspace", type="team"),
                ]
            )
            db.add_all(
                [
                    WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=DEFAULT_USER_ID, role="Owner"),
                    WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=AGENT_SYSTEM_USER_ID, role="Member"),
                ]
            )
            db.commit()
        else:
            # Ensure workspace + membership even if app.db was persisted.
            if not db.get(Workspace, BOOTSTRAP_WORKSPACE_ID):
                db.add(Workspace(id=BOOTSTRAP_WORKSPACE_ID, name="My Workspace", type="team"))
                db.commit()
            owner = db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == BOOTSTRAP_WORKSPACE_ID,
                    WorkspaceMember.user_id == DEFAULT_USER_ID,
                )
            ).scalar_one_or_none()
            if not owner:
                db.add(WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=DEFAULT_USER_ID, role="Owner"))
            agent_member = db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == BOOTSTRAP_WORKSPACE_ID,
                    WorkspaceMember.user_id == AGENT_SYSTEM_USER_ID,
                )
            ).scalar_one_or_none()
            if not agent_member:
                db.add(WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=AGENT_SYSTEM_USER_ID, role="Member"))
            db.commit()

        if current_version(db, "Project", BOOTSTRAP_PROJECT_ID) == 0:
            append_event(
                db,
                aggregate_type="Project",
                aggregate_id=BOOTSTRAP_PROJECT_ID,
                event_type=PROJECT_EVENT_CREATED,
                payload={"workspace_id": BOOTSTRAP_WORKSPACE_ID, "name": "General", "description": "Default project", "custom_statuses": DEFAULT_STATUSES},
                metadata={"actor_id": DEFAULT_USER_ID, "workspace_id": BOOTSTRAP_WORKSPACE_ID, "project_id": BOOTSTRAP_PROJECT_ID},
                expected_version=0,
            )
        if current_version(db, "Task", BOOTSTRAP_TASK_ID) == 0:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=BOOTSTRAP_TASK_ID,
                event_type=TASK_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "title": "Setup your first task",
                    "description": "Use FAB + to add tasks quickly.",
                    "status": "To do",
                    "priority": "Med",
                    "due_date": to_iso_utc(datetime.now(timezone.utc) + timedelta(days=1)),
                    "assignee_id": DEFAULT_USER_ID,
                    "labels": ["welcome"],
                    "subtasks": [],
                    "attachments": [],
                    "recurring_rule": None,
                    "order_index": 1,
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "task_id": BOOTSTRAP_TASK_ID,
                },
                expected_version=0,
            )
        db.commit()

        # Repair drift: if Kurrent was reset but app.db persisted, backfill streams.
        _backfill_project_streams_from_read_model(db)
        _backfill_task_streams_from_read_model(db)
        _rebuild_project_tag_index(db)
        db.commit()


def startup_bootstrap():
    if DATABASE_URL.startswith("sqlite"):
        os.makedirs(Path(DB_PATH).parent, exist_ok=True)
    last_exc: Exception | None = None
    for _ in range(20):
        try:
            bootstrap_data()
            last_exc = None
            break
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            time.sleep(1)
    if last_exc is not None:
        raise last_exc


def bootstrap_payload(db: Session, user: User) -> dict[str, Any]:
    emit_system_notifications(db, user)
    return bootstrap_payload_read_model(db, user)


def _backfill_project_streams_from_read_model(db: Session) -> None:
    """
    If EventStore/Kurrent was reset but app.db is persisted, we can end up with
    read-model rows that have no corresponding event streams. That breaks edits
    (commands rely on rebuild_state when Kurrent is enabled).
    """
    if get_kurrent_client() is None:
        return

    projects = db.execute(select(Project).where(Project.is_deleted == False)).scalars().all()
    for p in projects:
        if current_version(db, "Project", p.id) != 0:
            continue
        try:
            custom_statuses = json.loads(p.custom_statuses or "[]")
        except Exception:
            custom_statuses = DEFAULT_STATUSES
        append_event(
            db,
            aggregate_type="Project",
            aggregate_id=p.id,
            event_type=PROJECT_EVENT_CREATED,
            payload={
                "workspace_id": p.workspace_id,
                "name": p.name,
                "description": p.description or "",
                "custom_statuses": custom_statuses or DEFAULT_STATUSES,
            },
            metadata={"actor_id": DEFAULT_USER_ID, "workspace_id": p.workspace_id, "project_id": p.id},
            expected_version=0,
        )


def _backfill_task_streams_from_read_model(db: Session) -> None:
    if get_kurrent_client() is None:
        return

    tasks = db.execute(select(Task).where(Task.is_deleted == False)).scalars().all()
    for t in tasks:
        if current_version(db, "Task", t.id) != 0:
            continue
        try:
            labels = json.loads(t.labels or "[]")
        except Exception:
            labels = []
        try:
            subtasks = json.loads(t.subtasks or "[]")
        except Exception:
            subtasks = []
        try:
            attachments = json.loads(t.attachments or "[]")
        except Exception:
            attachments = []

        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=t.id,
            event_type=TASK_EVENT_CREATED,
            payload={
                "workspace_id": t.workspace_id,
                "project_id": t.project_id,
                "title": t.title,
                "description": t.description or "",
                "status": t.status or "To do",
                "priority": t.priority or "Med",
                "due_date": to_iso_utc(t.due_date),
                "assignee_id": t.assignee_id,
                "labels": labels,
                "subtasks": subtasks,
                "attachments": attachments,
                "recurring_rule": t.recurring_rule,
                "order_index": int(t.order_index or 0),
                "task_type": t.task_type or "manual",
                "scheduled_instruction": t.scheduled_instruction,
                "scheduled_at_utc": to_iso_utc(t.scheduled_at_utc),
                "schedule_timezone": t.schedule_timezone,
                "schedule_state": t.schedule_state or "idle",
            },
            metadata={
                "actor_id": DEFAULT_USER_ID,
                "workspace_id": t.workspace_id,
                "project_id": t.project_id,
                "task_id": t.id,
            },
            expected_version=0,
        )


def _parse_tag_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except Exception:
        return []
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        tag = str(value or "").strip().lower()
        if tag:
            out.append(tag)
    return out


def _rebuild_project_tag_index(db: Session) -> None:
    db.query(ProjectTagIndex).delete()
    projects = db.execute(select(Project).where(Project.is_deleted == False)).scalars().all()
    for project in projects:
        counts: dict[str, int] = {}
        task_rows = db.execute(
            select(Task.labels).where(
                Task.project_id == project.id,
                Task.is_deleted == False,
                Task.archived == False,
            )
        ).all()
        note_rows = db.execute(
            select(Note.tags).where(
                Note.project_id == project.id,
                Note.is_deleted == False,
                Note.archived == False,
            )
        ).all()
        for (labels_raw,) in task_rows:
            for tag in _parse_tag_list(labels_raw):
                counts[tag] = counts.get(tag, 0) + 1
        for (tags_raw,) in note_rows:
            for tag in _parse_tag_list(tags_raw):
                counts[tag] = counts.get(tag, 0) + 1
        for tag, usage_count in sorted(counts.items(), key=lambda item: item[0]):
            db.add(
                ProjectTagIndex(
                    workspace_id=project.workspace_id,
                    project_id=project.id,
                    tag=tag,
                    usage_count=usage_count,
                )
            )
