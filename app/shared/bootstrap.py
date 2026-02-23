from __future__ import annotations

import os
import time
import json
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from features.bootstrap.read_models import bootstrap_payload_read_model
from .eventing import append_event, current_version, emit_system_notifications, get_kurrent_client
from features.projects.domain import EVENT_CREATED as PROJECT_EVENT_CREATED
from features.rules.domain import EVENT_CREATED as PROJECT_RULE_EVENT_CREATED
from features.specifications.domain import EVENT_CREATED as SPECIFICATION_EVENT_CREATED
from features.tasks.domain import EVENT_CREATED as TASK_EVENT_CREATED
from .auth import generate_temporary_password, hash_password
from .licensing import resolve_license_installation_id
from . import models as shared_models
from .models import (
    Note,
    NoteGroup,
    LicenseInstallation,
    Project,
    ProjectMember,
    ProjectRule,
    ProjectTagIndex,
    Specification,
    Task,
    TaskGroup,
    TaskWatcher,
    User,
    Workspace,
    WorkspaceSkill,
    WorkspaceMember,
)
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
    DEFAULT_USER_ID,
    DEFAULT_STATUSES,
    LICENSE_TRIAL_DAYS,
)


_DEFAULT_WORKSPACE_SKILLS: tuple[dict[str, str], ...] = (
    {
        "skill_key": "github_delivery",
        "name": "GitHub Delivery Skill",
        "summary": "Use this skill for repository workflows, pull requests, and release coordination.",
        "source_locator": "seed://workspace-skills/github-delivery",
        "mode": "advisory",
        "trust_level": "verified",
        "content": (
            "# GitHub Delivery Skill\n\n"
            "Use this skill when work involves GitHub repositories, pull requests, or release notes.\n\n"
            "## Workflow\n"
            "- Clarify target repository, default branch, and release expectations.\n"
            "- Review open pull requests and CI status before proposing merges.\n"
            "- Prefer small, reviewable commits with clear commit messages.\n"
            "- Summarize risk, rollback approach, and post-merge validation.\n\n"
            "## Guardrails\n"
            "- Never force-push shared branches unless explicitly approved.\n"
            "- Never merge failing checks without an explicit exception.\n"
            "- Keep changelog and release notes aligned with merged changes.\n"
        ),
    },
    {
        "skill_key": "jira_execution",
        "name": "Jira Execution Skill",
        "summary": "Use this skill for Jira issue updates, workflow transitions, and sprint hygiene.",
        "source_locator": "seed://workspace-skills/jira-execution",
        "mode": "advisory",
        "trust_level": "verified",
        "content": (
            "# Jira Execution Skill\n\n"
            "Use this skill when work requires Jira issue planning, transitions, or reporting.\n\n"
            "## Workflow\n"
            "- Confirm project key, issue type, priority, and expected outcome.\n"
            "- Keep issue summary concise and actionable.\n"
            "- Record status transitions with a short reason.\n"
            "- Keep worklogs and comments consistent with actual work.\n\n"
            "## Guardrails\n"
            "- Do not transition issues without validating required fields.\n"
            "- Do not close issues without linking evidence (PR, commit, test result).\n"
            "- Keep sprint scope changes explicit and documented.\n"
        ),
    },
)


def ensure_system_users(db: Session):
    if not db.get(User, AGENT_SYSTEM_USER_ID):
        db.add(
            User(
                id=AGENT_SYSTEM_USER_ID,
                username=AGENT_SYSTEM_USERNAME,
                full_name=AGENT_SYSTEM_FULL_NAME,
                user_type="agent",
                password_hash=None,
                must_change_password=False,
                password_changed_at=None,
                is_active=True,
                timezone="UTC",
                theme="dark",
            )
        )
    else:
        agent_user = db.get(User, AGENT_SYSTEM_USER_ID)
        if agent_user:
            if agent_user.user_type != "agent":
                agent_user.user_type = "agent"
            # System agent does not authenticate with username/password.
            agent_user.password_hash = None
            agent_user.must_change_password = False
            agent_user.password_changed_at = None
            agent_user.is_active = True
    workspace = db.get(Workspace, BOOTSTRAP_WORKSPACE_ID)
    if workspace:
        membership = db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == BOOTSTRAP_WORKSPACE_ID,
                WorkspaceMember.user_id == AGENT_SYSTEM_USER_ID,
            )
        ).scalar_one_or_none()
        if not membership:
            db.add(WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=AGENT_SYSTEM_USER_ID, role="Admin"))
        elif membership.role not in {"Owner", "Admin"}:
            membership.role = "Admin"
    db.commit()


def ensure_non_human_workspace_admin_roles(db: Session):
    memberships = db.execute(
        select(WorkspaceMember)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(User.user_type != "human")
    ).scalars().all()
    changed = False
    for membership in memberships:
        if membership.role in {"Owner", "Admin"}:
            continue
        membership.role = "Admin"
        changed = True
    if changed:
        db.commit()


def ensure_workspace_skill_catalog_seed(db: Session, *, workspace_id: str, actor_user_id: str):
    changed = False
    imported_at = datetime.now(timezone.utc).isoformat()
    for default_skill in _DEFAULT_WORKSPACE_SKILLS:
        skill_key = str(default_skill["skill_key"])
        existing = db.execute(
            select(WorkspaceSkill).where(
                WorkspaceSkill.workspace_id == workspace_id,
                WorkspaceSkill.skill_key == skill_key,
            )
        ).scalar_one_or_none()
        manifest = {
            "seeded_default": True,
            "imported_at": imported_at,
            "source_content": str(default_skill["content"]),
            "source_content_sha256": "",
            "source_locator": str(default_skill["source_locator"]),
        }
        manifest["source_content_sha256"] = hashlib.sha256(
            str(manifest["source_content"]).encode("utf-8")
        ).hexdigest()
        if existing is None:
            db.add(
                WorkspaceSkill(
                    workspace_id=workspace_id,
                    skill_key=skill_key,
                    name=str(default_skill["name"]),
                    summary=str(default_skill["summary"]),
                    source_type="seed",
                    source_locator=str(default_skill["source_locator"]),
                    source_version=None,
                    trust_level=str(default_skill["trust_level"]),
                    mode=str(default_skill["mode"]),
                    manifest_json=json.dumps(manifest, ensure_ascii=True, sort_keys=True),
                    is_seeded=True,
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                    is_deleted=False,
                )
            )
            changed = True
            continue
        if bool(existing.is_deleted):
            existing.is_deleted = False
            existing.is_seeded = True
            existing.updated_by = actor_user_id
            if not str(existing.manifest_json or "").strip():
                existing.manifest_json = json.dumps(manifest, ensure_ascii=True, sort_keys=True)
            changed = True
    if changed:
        db.commit()


def ensure_user_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("users")}
    if "user_type" not in existing:
        db.execute(text("ALTER TABLE users ADD COLUMN user_type VARCHAR(16) DEFAULT 'human'"))
    if "password_hash" not in existing:
        db.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(256)"))
    if "must_change_password" not in existing:
        db.execute(text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT TRUE"))
    if "password_changed_at" not in existing:
        db.execute(text("ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMP WITH TIME ZONE"))
    if "is_active" not in existing:
        db.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT TRUE"))
    db.execute(text("UPDATE users SET user_type='human' WHERE user_type IS NULL OR user_type = ''"))
    db.execute(text("UPDATE users SET user_type='agent' WHERE id = :agent_id"), {"agent_id": AGENT_SYSTEM_USER_ID})
    db.execute(text("UPDATE users SET must_change_password=TRUE WHERE must_change_password IS NULL"))
    db.execute(text("UPDATE users SET is_active=TRUE WHERE is_active IS NULL"))
    db.commit()


def ensure_user_password_defaults(db: Session):
    default_user = db.get(User, DEFAULT_USER_ID)
    if default_user:
        if not default_user.password_hash:
            default_user.password_hash = hash_password("testtest")
            default_user.must_change_password = False
            default_user.password_changed_at = datetime.now(timezone.utc)
        default_user.is_active = True

    legacy_users = db.execute(
        select(User).where(
            User.id != DEFAULT_USER_ID,
            User.user_type == "human",
            User.password_hash.is_(None),
        )
    ).scalars().all()
    for user in legacy_users:
        user.password_hash = hash_password(generate_temporary_password(12))
        user.must_change_password = True
        user.is_active = True
        user.password_changed_at = None

    # Non-human users (agent/bot/service) should not carry password state.
    non_human_users = db.execute(
        select(User).where(User.user_type != "human")
    ).scalars().all()
    for user in non_human_users:
        user.password_hash = None
        user.must_change_password = False
        user.password_changed_at = None
        user.is_active = True

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
        "external_refs": "ALTER TABLE tasks ADD COLUMN external_refs TEXT DEFAULT '[]'",
        "attachment_refs": "ALTER TABLE tasks ADD COLUMN attachment_refs TEXT DEFAULT '[]'",
        "specification_id": "ALTER TABLE tasks ADD COLUMN specification_id VARCHAR(36)",
    }
    for column, ddl in required_columns.items():
        if column not in existing:
            db.execute(text(ddl))
    db.commit()


def ensure_task_group_tables(db: Session):
    TaskGroup.__table__.create(bind=db.bind, checkfirst=True)
    existing_task_columns = {column["name"] for column in inspect(db.bind).get_columns("tasks")}
    if "task_group_id" not in existing_task_columns:
        db.execute(text("ALTER TABLE tasks ADD COLUMN task_group_id VARCHAR(36)"))
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_task_groups_project_name ON task_groups(project_id, name)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_task_groups_workspace_id ON task_groups(workspace_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_task_groups_project_id ON task_groups(project_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_task_group_id ON tasks(task_group_id)"))
    db.commit()


def ensure_note_group_tables(db: Session):
    NoteGroup.__table__.create(bind=db.bind, checkfirst=True)
    existing_note_columns = {column["name"] for column in inspect(db.bind).get_columns("notes")}
    if "note_group_id" not in existing_note_columns:
        db.execute(text("ALTER TABLE notes ADD COLUMN note_group_id VARCHAR(36)"))
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_note_groups_project_name ON note_groups(project_id, name)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_note_groups_workspace_id ON note_groups(workspace_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_note_groups_project_id ON note_groups(project_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_notes_note_group_id ON notes(note_group_id)"))
    db.commit()


def ensure_saved_view_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("saved_views")}
    if "project_id" not in existing:
        db.execute(text("ALTER TABLE saved_views ADD COLUMN project_id VARCHAR(36)"))
    db.commit()


def ensure_project_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("projects")}
    if "external_refs" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN external_refs TEXT DEFAULT '[]'"))
    if "attachment_refs" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN attachment_refs TEXT DEFAULT '[]'"))
    if "embedding_enabled" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN embedding_enabled BOOLEAN DEFAULT FALSE"))
    if "embedding_model" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN embedding_model VARCHAR(128)"))
    if "context_pack_evidence_top_k" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN context_pack_evidence_top_k INTEGER"))
    if "chat_index_mode" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN chat_index_mode VARCHAR(32) DEFAULT 'OFF'"))
    if "chat_attachment_ingestion_mode" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN chat_attachment_ingestion_mode VARCHAR(32) DEFAULT 'METADATA_ONLY'"))
    db.execute(text("UPDATE projects SET chat_index_mode='OFF' WHERE chat_index_mode IS NULL OR chat_index_mode = ''"))
    db.execute(
        text(
            "UPDATE projects SET chat_attachment_ingestion_mode='METADATA_ONLY' "
            "WHERE chat_attachment_ingestion_mode IS NULL OR chat_attachment_ingestion_mode = ''"
        )
    )
    db.commit()


def ensure_note_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("notes")}
    if "external_refs" not in existing:
        db.execute(text("ALTER TABLE notes ADD COLUMN external_refs TEXT DEFAULT '[]'"))
    if "attachment_refs" not in existing:
        db.execute(text("ALTER TABLE notes ADD COLUMN attachment_refs TEXT DEFAULT '[]'"))
    if "specification_id" not in existing:
        db.execute(text("ALTER TABLE notes ADD COLUMN specification_id VARCHAR(36)"))
    db.commit()


def ensure_specification_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("specifications")}
    if "tags" not in existing:
        db.execute(text("ALTER TABLE specifications ADD COLUMN tags TEXT DEFAULT '[]'"))
    db.commit()


def ensure_notification_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("notifications")}
    if "workspace_id" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN workspace_id VARCHAR(36)"))
    if "project_id" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN project_id VARCHAR(36)"))
    if "task_id" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN task_id VARCHAR(36)"))
    if "note_id" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN note_id VARCHAR(36)"))
    if "specification_id" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN specification_id VARCHAR(36)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_workspace_id ON notifications(workspace_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_project_id ON notifications(project_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_task_id ON notifications(task_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_note_id ON notifications(note_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_specification_id ON notifications(specification_id)"))
    db.commit()


def ensure_task_comment_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("task_comments")}
    if "event_version" not in existing:
        db.execute(text("ALTER TABLE task_comments ADD COLUMN event_version INTEGER"))
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_task_comments_task_event_version ON task_comments(task_id, event_version)"))
    db.commit()


def ensure_chat_table_columns(db: Session):
    existing_sessions = {column["name"] for column in inspect(db.bind).get_columns("chat_sessions")}
    if "session_attachment_refs" not in existing_sessions:
        db.execute(text("ALTER TABLE chat_sessions ADD COLUMN session_attachment_refs TEXT DEFAULT '[]'"))
    db.execute(
        text(
            "UPDATE chat_sessions SET session_attachment_refs='[]' "
            "WHERE session_attachment_refs IS NULL OR session_attachment_refs = ''"
        )
    )
    db.commit()


def ensure_task_watcher_table_constraints(db: Session):
    duplicates = db.execute(
        select(TaskWatcher.task_id, TaskWatcher.user_id)
        .group_by(TaskWatcher.task_id, TaskWatcher.user_id)
        .having(func.count(TaskWatcher.id) > 1)
    ).all()
    for task_id, user_id in duplicates:
        rows = db.execute(
            select(TaskWatcher)
            .where(TaskWatcher.task_id == task_id, TaskWatcher.user_id == user_id)
            .order_by(TaskWatcher.id.asc())
        ).scalars().all()
        for row in rows[1:]:
            db.delete(row)
    db.flush()
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_task_watchers_task_user ON task_watchers(task_id, user_id)"))
    db.commit()


def ensure_license_installation(db: Session):
    installation_id = resolve_license_installation_id(db)
    installation = db.execute(
        select(LicenseInstallation).where(LicenseInstallation.installation_id == installation_id)
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    trial_days = max(1, int(LICENSE_TRIAL_DAYS))
    if installation is None:
        db.add(
            LicenseInstallation(
                installation_id=installation_id,
                workspace_id=None,
                status="trial",
                plan_code="trial",
                activated_at=now,
                trial_ends_at=now + timedelta(days=trial_days),
                metadata_json='{"source":"bootstrap-local"}',
            )
        )
        db.commit()
        return
    changed = False
    if installation.workspace_id is None and db.get(Workspace, BOOTSTRAP_WORKSPACE_ID) is not None:
        installation.workspace_id = BOOTSTRAP_WORKSPACE_ID
        changed = True
    if installation.activated_at is None:
        installation.activated_at = now
        changed = True
    if installation.trial_ends_at is None:
        installation.trial_ends_at = now + timedelta(days=trial_days)
        changed = True
    if changed:
        db.commit()


def bootstrap_data():
    shared_models.ensure_engine()
    shared_models.Base.metadata.create_all(bind=shared_models.engine)
    with shared_models.SessionLocal() as db:
        ensure_user_table_columns(db)
        ensure_project_table_columns(db)
        ensure_note_table_columns(db)
        ensure_note_group_tables(db)
        ensure_specification_table_columns(db)
        ensure_notification_table_columns(db)
        ensure_task_table_columns(db)
        ensure_task_group_tables(db)
        ensure_saved_view_table_columns(db)
        ensure_task_comment_table_columns(db)
        ensure_chat_table_columns(db)
        ensure_task_watcher_table_constraints(db)
        ensure_system_users(db)
        default_user = db.get(User, DEFAULT_USER_ID)
        if not default_user:
            db.add_all(
                [
                    User(
                        id=DEFAULT_USER_ID,
                        username=BOOTSTRAP_USERNAME,
                        full_name=BOOTSTRAP_FULL_NAME,
                        user_type="human",
                        password_hash=hash_password("testtest"),
                        must_change_password=False,
                        password_changed_at=datetime.now(timezone.utc),
                        is_active=True,
                        timezone="Europe/Sarajevo",
                        theme="light",
                    ),
                    Workspace(id=BOOTSTRAP_WORKSPACE_ID, name="My Workspace", type="team"),
                ]
            )
            db.add_all(
                [
                    WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=DEFAULT_USER_ID, role="Owner"),
                    WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=AGENT_SYSTEM_USER_ID, role="Admin"),
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
                db.add(WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=AGENT_SYSTEM_USER_ID, role="Admin"))
            elif agent_member.role not in {"Owner", "Admin"}:
                agent_member.role = "Admin"
            db.commit()

        ensure_license_installation(db)
        ensure_user_password_defaults(db)
        ensure_non_human_workspace_admin_roles(db)
        workspace_ids = db.execute(select(Workspace.id).where(Workspace.is_deleted == False)).scalars().all()
        for workspace_id in workspace_ids:
            ensure_workspace_skill_catalog_seed(
                db,
                workspace_id=str(workspace_id),
                actor_user_id=DEFAULT_USER_ID,
            )

        if current_version(db, "Project", BOOTSTRAP_PROJECT_ID) == 0:
            append_event(
                db,
                aggregate_type="Project",
                aggregate_id=BOOTSTRAP_PROJECT_ID,
                event_type=PROJECT_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "name": "General",
                    "description": "Default project",
                    "custom_statuses": DEFAULT_STATUSES,
                    "external_refs": [],
                    "attachment_refs": [],
                    "chat_index_mode": "OFF",
                    "chat_attachment_ingestion_mode": "METADATA_ONLY",
                },
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
                    "external_refs": [],
                    "attachment_refs": [],
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
        _backfill_project_rule_streams_from_read_model(db)
        _backfill_specification_streams_from_read_model(db)
        _backfill_task_streams_from_read_model(db)
        _rebuild_project_tag_index(db)
        _backfill_project_members_for_existing_projects(db)
        db.commit()


def startup_bootstrap():
    active_database_url = shared_models.ensure_engine()
    if active_database_url.startswith("sqlite"):
        db_path = active_database_url.removeprefix("sqlite:///")
        if db_path:
            os.makedirs(Path(db_path).parent, exist_ok=True)
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
        try:
            external_refs = json.loads(p.external_refs or "[]")
        except Exception:
            external_refs = []
        try:
            attachment_refs = json.loads(p.attachment_refs or "[]")
        except Exception:
            attachment_refs = []
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
                    "external_refs": external_refs,
                    "attachment_refs": attachment_refs,
                    "chat_index_mode": str(getattr(p, "chat_index_mode", "") or "OFF"),
                    "chat_attachment_ingestion_mode": str(
                        getattr(p, "chat_attachment_ingestion_mode", "") or "METADATA_ONLY"
                    ),
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
        try:
            external_refs = json.loads(t.external_refs or "[]")
        except Exception:
            external_refs = []
        try:
            attachment_refs = json.loads(t.attachment_refs or "[]")
        except Exception:
            attachment_refs = attachments

        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=t.id,
            event_type=TASK_EVENT_CREATED,
            payload={
                "workspace_id": t.workspace_id,
                "project_id": t.project_id,
                "specification_id": t.specification_id,
                "title": t.title,
                "description": t.description or "",
                "status": t.status or "To do",
                "priority": t.priority or "Med",
                "due_date": to_iso_utc(t.due_date),
                "assignee_id": t.assignee_id,
                "labels": labels,
                "subtasks": subtasks,
                "attachments": attachments,
                "external_refs": external_refs,
                "attachment_refs": attachment_refs,
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


def _backfill_project_rule_streams_from_read_model(db: Session) -> None:
    if get_kurrent_client() is None:
        return

    rules = db.execute(select(ProjectRule).where(ProjectRule.is_deleted == False)).scalars().all()
    for rule in rules:
        if current_version(db, "ProjectRule", rule.id) != 0:
            continue
        append_event(
            db,
            aggregate_type="ProjectRule",
            aggregate_id=rule.id,
            event_type=PROJECT_RULE_EVENT_CREATED,
            payload={
                "workspace_id": rule.workspace_id,
                "project_id": rule.project_id,
                "title": rule.title,
                "body": rule.body or "",
                "created_by": rule.created_by,
                "updated_by": rule.updated_by,
                "is_deleted": False,
            },
            metadata={
                "actor_id": rule.created_by or DEFAULT_USER_ID,
                "workspace_id": rule.workspace_id,
                "project_id": rule.project_id,
                "project_rule_id": rule.id,
            },
            expected_version=0,
        )


def _backfill_specification_streams_from_read_model(db: Session) -> None:
    if get_kurrent_client() is None:
        return

    specifications = db.execute(select(Specification).where(Specification.is_deleted == False)).scalars().all()
    for specification in specifications:
        if current_version(db, "Specification", specification.id) != 0:
            continue
        try:
            external_refs = json.loads(specification.external_refs or "[]")
        except Exception:
            external_refs = []
        try:
            attachment_refs = json.loads(specification.attachment_refs or "[]")
        except Exception:
            attachment_refs = []
        try:
            tags = json.loads(specification.tags or "[]")
        except Exception:
            tags = []
        append_event(
            db,
            aggregate_type="Specification",
            aggregate_id=specification.id,
            event_type=SPECIFICATION_EVENT_CREATED,
            payload={
                "workspace_id": specification.workspace_id,
                "project_id": specification.project_id,
                "title": specification.title,
                "body": specification.body or "",
                "status": specification.status or "Draft",
                "tags": tags,
                "external_refs": external_refs,
                "attachment_refs": attachment_refs,
                "created_by": specification.created_by,
                "updated_by": specification.updated_by,
                "archived": bool(specification.archived),
                "is_deleted": False,
            },
            metadata={
                "actor_id": specification.created_by or DEFAULT_USER_ID,
                "workspace_id": specification.workspace_id,
                "project_id": specification.project_id,
                "specification_id": specification.id,
            },
            expected_version=0,
        )


def _backfill_project_members_for_existing_projects(db: Session) -> None:
    projects = db.execute(select(Project).where(Project.is_deleted == False)).scalars().all()
    for project in projects:
        has_members = db.execute(
            select(func.count(ProjectMember.id)).where(
                ProjectMember.project_id == project.id,
            )
        ).scalar() or 0
        if has_members > 0:
            continue
        # Safe default: assign workspace owners to existing projects.
        owners = db.execute(
            select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id == project.workspace_id,
                WorkspaceMember.role.in_(["Owner", "Admin"]),
            )
        ).scalars().all()
        if not owners:
            owners = [DEFAULT_USER_ID]
        for uid in dict.fromkeys(owners):
            db.add(
                ProjectMember(
                    workspace_id=project.workspace_id,
                    project_id=project.id,
                    user_id=uid,
                    role="Owner",
                )
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
        specification_rows = db.execute(
            select(Specification.tags).where(
                Specification.project_id == project.id,
                Specification.is_deleted == False,
                Specification.archived == False,
            )
        ).all()
        for (labels_raw,) in task_rows:
            for tag in _parse_tag_list(labels_raw):
                counts[tag] = counts.get(tag, 0) + 1
        for (tags_raw,) in note_rows:
            for tag in _parse_tag_list(tags_raw):
                counts[tag] = counts.get(tag, 0) + 1
        for (tags_raw,) in specification_rows:
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
