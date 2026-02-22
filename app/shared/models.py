from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .settings import DATABASE_URL


class Base(DeclarativeBase):
    pass


class TimeMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


def new_uuid() -> str:
    return str(uuid.uuid4())


class User(Base, TimeMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(128))
    user_type: Mapped[str] = mapped_column(String(16), default="human")
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    theme: Mapped[str] = mapped_column(String(16), default="light")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Workspace(Base, TimeMixin):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(16), default="personal")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16), default="Member")


class Project(Base, TimeMixin):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="Active")
    custom_statuses: Mapped[str] = mapped_column(Text, default='["To do", "In progress", "Done"]')
    external_refs: Mapped[str] = mapped_column(Text, default="[]")
    attachment_refs: Mapped[str] = mapped_column(Text, default="[]")
    embedding_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    context_pack_evidence_top_k: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class ProjectMember(Base, TimeMixin):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="ux_project_members_project_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="Contributor")


class ProjectTemplateBinding(Base, TimeMixin):
    __tablename__ = "project_template_bindings"
    __table_args__ = (UniqueConstraint("project_id", name="ux_project_template_bindings_project"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    template_key: Mapped[str] = mapped_column(String(128), index=True)
    template_version: Mapped[str] = mapped_column(String(32))
    applied_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    parameters_json: Mapped[str] = mapped_column(Text, default="{}")


class ProjectSkill(Base, TimeMixin):
    __tablename__ = "project_skills"
    __table_args__ = (UniqueConstraint("project_id", "skill_key", name="ux_project_skills_project_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    skill_key: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(160))
    summary: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String(32), default="url")
    source_locator: Mapped[str] = mapped_column(Text, default="")
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trust_level: Mapped[str] = mapped_column(String(24), default="reviewed")
    mode: Mapped[str] = mapped_column(String(24), default="advisory")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    generated_rule_id: Mapped[str | None] = mapped_column(ForeignKey("project_rules.id"), nullable=True, index=True)
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class TaskGroup(Base, TimeMixin):
    __tablename__ = "task_groups"
    __table_args__ = (UniqueConstraint("project_id", "name", name="ux_task_groups_project_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Task(Base, TimeMixin):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    task_group_id: Mapped[str | None] = mapped_column(ForeignKey("task_groups.id"), nullable=True, index=True)
    specification_id: Mapped[str | None] = mapped_column(ForeignKey("specifications.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="To do")
    priority: Mapped[str] = mapped_column(String(16), default="Med")
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    labels: Mapped[str] = mapped_column(Text, default="[]")
    subtasks: Mapped[str] = mapped_column(Text, default="[]")
    attachments: Mapped[str] = mapped_column(Text, default="[]")
    external_refs: Mapped[str] = mapped_column(Text, default="[]")
    attachment_refs: Mapped[str] = mapped_column(Text, default="[]")
    recurring_rule: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_type: Mapped[str] = mapped_column(String(32), default="manual")
    scheduled_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schedule_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schedule_state: Mapped[str] = mapped_column(String(16), default="idle")
    last_schedule_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_schedule_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class TaskWatcher(Base):
    __tablename__ = "task_watchers"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="ux_task_watchers_task_user"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


class TaskComment(Base, TimeMixin):
    __tablename__ = "task_comments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    event_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Note(Base, TimeMixin):
    __tablename__ = "notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    note_group_id: Mapped[str | None] = mapped_column(ForeignKey("note_groups.id"), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    specification_id: Mapped[str | None] = mapped_column(ForeignKey("specifications.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="[]")
    external_refs: Mapped[str] = mapped_column(Text, default="[]")
    attachment_refs: Mapped[str] = mapped_column(Text, default="[]")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class NoteGroup(Base, TimeMixin):
    __tablename__ = "note_groups"
    __table_args__ = (UniqueConstraint("project_id", "name", name="ux_note_groups_project_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class ProjectTagIndex(Base, TimeMixin):
    __tablename__ = "project_tag_index"
    __table_args__ = (UniqueConstraint("project_id", "tag", name="ux_project_tag_index_project_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    tag: Mapped[str] = mapped_column(String(128), index=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)


class ProjectRule(Base, TimeMixin):
    __tablename__ = "project_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Specification(Base, TimeMixin):
    __tablename__ = "specifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="Draft")
    tags: Mapped[str] = mapped_column(Text, default="[]")
    external_refs: Mapped[str] = mapped_column(Text, default="[]")
    attachment_refs: Mapped[str] = mapped_column(Text, default="[]")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Notification(Base, TimeMixin):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    note_id: Mapped[str | None] = mapped_column(ForeignKey("notes.id"), nullable=True, index=True)
    specification_id: Mapped[str | None] = mapped_column(ForeignKey("specifications.id"), nullable=True, index=True)
    message: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)


class ActivityLog(Base, TimeMixin):
    __tablename__ = "activity_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    details: Mapped[str] = mapped_column(Text, default="{}")


class SavedView(Base, TimeMixin):
    __tablename__ = "saved_views"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(128))
    filters: Mapped[str] = mapped_column(Text, default="{}")
    shared: Mapped[bool] = mapped_column(Boolean, default=False)


class StoredEvent(Base):
    __tablename__ = "stored_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(128), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    meta: Mapped[str] = mapped_column(Text, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class AggregateSnapshot(Base):
    __tablename__ = "aggregate_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ProjectionCheckpoint(Base):
    __tablename__ = "projection_checkpoints"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    commit_position: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class CommandExecution(Base):
    __tablename__ = "command_executions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    command_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    command_name: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    response_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class LicenseInstallation(Base, TimeMixin):
    __tablename__ = "license_installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="trial")
    plan_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")


class LicenseEntitlement(Base, TimeMixin):
    __tablename__ = "license_entitlements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[int] = mapped_column(ForeignKey("license_installations.id"), index=True)
    source: Mapped[str] = mapped_column(String(32), default="local")
    status: Mapped[str] = mapped_column(String(24), default="trial")
    plan_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload_json: Mapped[str] = mapped_column(Text, default="{}")


class LicenseValidationLog(Base):
    __tablename__ = "license_validation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[int] = mapped_column(ForeignKey("license_installations.id"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    result: Mapped[str] = mapped_column(String(24), index=True)
    reason: Mapped[str] = mapped_column(String(256), default="")
    details_json: Mapped[str] = mapped_column(Text, default="{}")


class SupportBugReportOutbox(Base, TimeMixin):
    __tablename__ = "support_bug_report_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(128), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class AuthSession(Base, TimeMixin):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class VectorChunk(Base, TimeMixin):
    __tablename__ = "vector_chunks"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "entity_type",
            "entity_id",
            "source_type",
            "chunk_index",
            name="ux_vector_chunks_source_chunk",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(128), index=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    text_chunk: Mapped[str] = mapped_column(Text, default="")
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_json: Mapped[str] = mapped_column(Text, default="[]")
    embedding_model: Mapped[str] = mapped_column(String(128), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


def _runtime_database_url() -> str:
    configured = os.getenv("DATABASE_URL", "").strip()
    if configured:
        return configured
    db_path = os.getenv("DB_PATH", "/data/app.db")
    return f"sqlite:///{db_path}"


def _build_engine(url: str):
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


_engine_url = str(DATABASE_URL or "").strip() or _runtime_database_url()
engine = _build_engine(_engine_url)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def ensure_engine() -> str:
    global engine, _engine_url
    runtime_url = _runtime_database_url()
    if runtime_url == _engine_url:
        return _engine_url
    new_engine = _build_engine(runtime_url)
    previous_engine = engine
    engine = new_engine
    SessionLocal.configure(bind=new_engine)
    _engine_url = runtime_url
    try:
        previous_engine.dispose()
    except Exception:
        pass
    return _engine_url
