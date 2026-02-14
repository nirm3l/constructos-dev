from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from features.bootstrap.read_models import bootstrap_payload_read_model
from .eventing import append_event, current_version, emit_system_notifications
from features.projects.domain import EVENT_CREATED as PROJECT_EVENT_CREATED
from features.tasks.domain import EVENT_CREATED as TASK_EVENT_CREATED
from .models import Base, SessionLocal, User, Workspace, WorkspaceMember, engine
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
    # Lightweight SQLite migration path for new task scheduling fields.
    existing = {
        row[1]
        for row in db.execute(text("PRAGMA table_info(tasks)")).fetchall()
    }
    required_columns = {
        "task_type": "ALTER TABLE tasks ADD COLUMN task_type VARCHAR(32) DEFAULT 'manual'",
        "scheduled_instruction": "ALTER TABLE tasks ADD COLUMN scheduled_instruction TEXT",
        "scheduled_at_utc": "ALTER TABLE tasks ADD COLUMN scheduled_at_utc DATETIME",
        "schedule_timezone": "ALTER TABLE tasks ADD COLUMN schedule_timezone VARCHAR(64)",
        "schedule_state": "ALTER TABLE tasks ADD COLUMN schedule_state VARCHAR(16) DEFAULT 'idle'",
        "last_schedule_run_at": "ALTER TABLE tasks ADD COLUMN last_schedule_run_at DATETIME",
        "last_schedule_error": "ALTER TABLE tasks ADD COLUMN last_schedule_error TEXT",
    }
    for column, ddl in required_columns.items():
        if column not in existing:
            db.execute(text(ddl))
    db.commit()


def bootstrap_data():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_task_table_columns(db)
        ensure_system_users(db)
        if db.get(User, DEFAULT_USER_ID):
            return

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


def startup_bootstrap():
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
