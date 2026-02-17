from __future__ import annotations

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
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class ProjectMember(Base, TimeMixin):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="ux_project_members_project_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="Contributor")


class Task(Base, TimeMixin):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
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


engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
