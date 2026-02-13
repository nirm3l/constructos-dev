from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str = Field(min_length=1)
    workspace_id: str
    project_id: str | None = None
    description: str = ""
    priority: str = "Med"
    due_date: datetime | None = None
    assignee_id: str | None = None
    labels: list[str] = Field(default_factory=list)
    subtasks: list[dict[str, Any]] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    recurring_rule: str | None = None


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


class BulkAction(BaseModel):
    task_ids: list[str]
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1)


class SavedViewCreate(BaseModel):
    workspace_id: str
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
