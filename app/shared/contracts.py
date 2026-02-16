from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str = Field(min_length=1)
    workspace_id: str
    project_id: str
    description: str = ""
    priority: str = "Med"
    due_date: datetime | None = None
    assignee_id: str | None = None
    labels: list[str] = Field(default_factory=list)
    subtasks: list[dict[str, Any]] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    recurring_rule: str | None = None
    task_type: str = "manual"
    scheduled_instruction: str | None = None
    scheduled_at_utc: datetime | None = None
    schedule_timezone: str | None = None


class TaskPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    due_date: datetime | None = None
    assignee_id: str | None = None
    labels: list[str] | None = None
    subtasks: list[dict[str, Any]] | None = None
    attachments: list[dict[str, Any]] | None = None
    archived: bool | None = None
    project_id: str | None = None
    recurring_rule: str | None = None
    task_type: str | None = None
    scheduled_instruction: str | None = None
    scheduled_at_utc: datetime | None = None
    schedule_timezone: str | None = None


class BulkAction(BaseModel):
    task_ids: list[str]
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1)


class TaskAutomationRun(BaseModel):
    instruction: str | None = Field(default=None, max_length=2000)


class AgentChatRun(BaseModel):
    workspace_id: str
    instruction: str = Field(min_length=1, max_length=4000)
    project_id: str | None = None
    session_id: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list)
    allow_mutations: bool = True


class NoteCreate(BaseModel):
    title: str = Field(min_length=1)
    workspace_id: str
    project_id: str
    task_id: str | None = None
    body: str = ""
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False


class NotePatch(BaseModel):
    title: str | None = None
    body: str | None = None
    tags: list[str] | None = None
    pinned: bool | None = None
    archived: bool | None = None
    project_id: str | None = None
    task_id: str | None = None


class SavedViewCreate(BaseModel):
    workspace_id: str
    project_id: str
    name: str
    shared: bool = False
    filters: dict[str, Any]


class ProjectCreate(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1)
    description: str = ""
    custom_statuses: list[str] | None = None


class ReorderPayload(BaseModel):
    ordered_ids: list[str]
    status: str | None = None


class UserPreferencesPatch(BaseModel):
    theme: str | None = None
    timezone: str | None = None
    notifications_enabled: bool | None = None


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    aggregate_type: str
    aggregate_id: str
    version: int
    event_type: str
    payload: dict[str, Any]
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TaskDTO:
    id: str
    workspace_id: str
    project_id: str | None
    title: str
    description: str
    status: str
    priority: str
    due_date: str | None
    assignee_id: str | None
    labels: list[str]
    subtasks: list[dict[str, Any]]
    attachments: list[dict[str, Any]]
    recurring_rule: str | None
    task_type: str
    scheduled_instruction: str | None
    scheduled_at_utc: str | None
    schedule_timezone: str | None
    schedule_state: str
    last_schedule_run_at: str | None
    last_schedule_error: str | None
    archived: bool
    completed_at: str | None
    created_at: str | None
    updated_at: str | None
    order_index: int


@dataclass(frozen=True, slots=True)
class NotificationDTO:
    id: str
    message: str
    is_read: bool
    created_at: str | None


@dataclass(frozen=True, slots=True)
class TaskCommandState:
    id: str
    workspace_id: str
    project_id: str | None
    status: str
    archived: bool
    is_deleted: bool


class ConcurrencyConflictError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class NoteDTO:
    id: str
    workspace_id: str
    project_id: str | None
    task_id: str | None
    title: str
    body: str
    tags: list[str]
    pinned: bool
    archived: bool
    created_by: str
    updated_by: str
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class NoteCommandState:
    id: str
    workspace_id: str
    project_id: str | None
    task_id: str | None
    pinned: bool
    archived: bool
    is_deleted: bool
