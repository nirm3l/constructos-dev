from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ExternalRef(BaseModel):
    url: str = Field(min_length=1)
    title: str | None = None
    source: str | None = None


class AttachmentRef(BaseModel):
    path: str = Field(min_length=1)
    name: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1)
    workspace_id: str
    project_id: str
    task_group_id: str | None = None
    specification_id: str | None = None
    description: str = ""
    priority: str = "Med"
    due_date: datetime | None = None
    assignee_id: str | None = None
    labels: list[str] = Field(default_factory=list)
    subtasks: list[dict[str, Any]] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    external_refs: list[ExternalRef] = Field(default_factory=list)
    attachment_refs: list[AttachmentRef] = Field(default_factory=list)
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
    external_refs: list[ExternalRef] | None = None
    attachment_refs: list[AttachmentRef] | None = None
    archived: bool | None = None
    project_id: str | None = None
    task_group_id: str | None = None
    specification_id: str | None = None
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
    mcp_servers: list[str] | None = None
    history: list[dict[str, str]] = Field(default_factory=list)
    attachment_refs: list[AttachmentRef] = Field(default_factory=list)
    allow_mutations: bool = True


class NoteCreate(BaseModel):
    title: str = Field(min_length=1)
    workspace_id: str
    project_id: str
    note_group_id: str | None = None
    task_id: str | None = None
    specification_id: str | None = None
    body: str = ""
    tags: list[str] = Field(default_factory=list)
    external_refs: list[ExternalRef] = Field(default_factory=list)
    attachment_refs: list[AttachmentRef] = Field(default_factory=list)
    pinned: bool = False


class NotePatch(BaseModel):
    title: str | None = None
    body: str | None = None
    tags: list[str] | None = None
    external_refs: list[ExternalRef] | None = None
    attachment_refs: list[AttachmentRef] | None = None
    pinned: bool | None = None
    archived: bool | None = None
    project_id: str | None = None
    note_group_id: str | None = None
    task_id: str | None = None
    specification_id: str | None = None


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
    external_refs: list[ExternalRef] = Field(default_factory=list)
    attachment_refs: list[AttachmentRef] = Field(default_factory=list)
    embedding_enabled: bool = False
    embedding_model: str | None = None
    context_pack_evidence_top_k: int | None = Field(default=None, ge=1, le=40)
    member_user_ids: list[str] = Field(default_factory=list)


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    custom_statuses: list[str] | None = None
    external_refs: list[ExternalRef] | None = None
    attachment_refs: list[AttachmentRef] | None = None
    embedding_enabled: bool | None = None
    embedding_model: str | None = None
    context_pack_evidence_top_k: int | None = Field(default=None, ge=1, le=40)


class ProjectMemberUpsert(BaseModel):
    user_id: str
    role: str = "Contributor"


class ProjectRuleCreate(BaseModel):
    workspace_id: str
    project_id: str
    title: str = Field(min_length=1)
    body: str = ""


class ProjectRulePatch(BaseModel):
    title: str | None = None
    body: str | None = None


class TaskGroupCreate(BaseModel):
    workspace_id: str
    project_id: str
    name: str = Field(min_length=1)
    description: str = ""
    color: str | None = None


class TaskGroupPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None


class NoteGroupCreate(BaseModel):
    workspace_id: str
    project_id: str
    name: str = Field(min_length=1)
    description: str = ""
    color: str | None = None


class NoteGroupPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None


class SpecificationCreate(BaseModel):
    workspace_id: str
    project_id: str
    title: str = Field(min_length=1)
    body: str = ""
    status: str = "Draft"
    tags: list[str] = Field(default_factory=list)
    external_refs: list[ExternalRef] = Field(default_factory=list)
    attachment_refs: list[AttachmentRef] = Field(default_factory=list)


class SpecificationPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    external_refs: list[ExternalRef] | None = None
    attachment_refs: list[AttachmentRef] | None = None
    archived: bool | None = None


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
    task_group_id: str | None
    specification_id: str | None
    title: str
    description: str
    status: str
    priority: str
    due_date: str | None
    assignee_id: str | None
    labels: list[str]
    subtasks: list[dict[str, Any]]
    attachments: list[dict[str, Any]]
    external_refs: list[dict[str, Any]]
    attachment_refs: list[dict[str, Any]]
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
    created_by: str
    order_index: int


@dataclass(frozen=True, slots=True)
class NotificationDTO:
    id: str
    message: str
    is_read: bool
    created_at: str | None
    workspace_id: str | None = None
    project_id: str | None = None
    task_id: str | None = None
    note_id: str | None = None
    specification_id: str | None = None


@dataclass(frozen=True, slots=True)
class TaskCommandState:
    id: str
    workspace_id: str
    project_id: str | None
    task_group_id: str | None
    specification_id: str | None
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
    note_group_id: str | None
    task_id: str | None
    specification_id: str | None
    title: str
    body: str
    tags: list[str]
    external_refs: list[dict[str, Any]]
    attachment_refs: list[dict[str, Any]]
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
    note_group_id: str | None
    task_id: str | None
    specification_id: str | None
    pinned: bool
    archived: bool
    is_deleted: bool


@dataclass(frozen=True, slots=True)
class ProjectRuleDTO:
    id: str
    workspace_id: str
    project_id: str
    title: str
    body: str
    created_by: str
    updated_by: str
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class ProjectRuleCommandState:
    id: str
    workspace_id: str
    project_id: str
    is_deleted: bool


@dataclass(frozen=True, slots=True)
class SpecificationDTO:
    id: str
    workspace_id: str
    project_id: str
    title: str
    body: str
    status: str
    tags: list[str]
    external_refs: list[dict[str, Any]]
    attachment_refs: list[dict[str, Any]]
    archived: bool
    created_by: str
    updated_by: str
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class SpecificationCommandState:
    id: str
    workspace_id: str
    project_id: str
    status: str
    archived: bool
    is_deleted: bool


@dataclass(frozen=True, slots=True)
class TaskGroupDTO:
    id: str
    workspace_id: str
    project_id: str
    name: str
    description: str
    color: str | None
    order_index: int
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class TaskGroupCommandState:
    id: str
    workspace_id: str
    project_id: str
    is_deleted: bool


@dataclass(frozen=True, slots=True)
class NoteGroupDTO:
    id: str
    workspace_id: str
    project_id: str
    name: str
    description: str
    color: str | None
    order_index: int
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class NoteGroupCommandState:
    id: str
    workspace_id: str
    project_id: str
    is_deleted: bool
