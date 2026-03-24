from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from features.agents.gateway import build_ui_gateway
from shared.contracts import AttachmentRef, ExternalRef
from shared.core import (
    SpecificationCreate,
    SpecificationPatch,
    User,
    get_command_id,
    get_current_user,
    get_db,
)

from .application import SpecificationApplicationService

router = APIRouter()


class SpecificationTaskCreatePayload(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    priority: str = "Med"
    due_date: datetime | None = None
    assignee_id: str | None = None
    labels: list[str] = Field(default_factory=list)
    external_refs: list[ExternalRef] = Field(default_factory=list)
    attachment_refs: list[AttachmentRef] = Field(default_factory=list)
    recurring_rule: str | None = None
    task_type: str = "manual"
    scheduled_instruction: str | None = None
    scheduled_at_utc: datetime | None = None
    schedule_timezone: str | None = None


class SpecificationTaskBulkCreatePayload(BaseModel):
    titles: list[str] = Field(min_length=1)
    description: str = ""
    priority: str = "Med"
    due_date: datetime | None = None
    assignee_id: str | None = None
    labels: list[str] = Field(default_factory=list)


class SpecificationNoteCreatePayload(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False
    external_refs: list[ExternalRef] = Field(default_factory=list)
    attachment_refs: list[AttachmentRef] = Field(default_factory=list)


@router.get("/api/specifications")
def list_specifications(
    workspace_id: str,
    project_id: str,
    q: str | None = None,
    status: str | None = None,
    tags: str | None = None,
    archived: bool = False,
    limit: int = Query(default=30, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.list_specifications(
        workspace_id=workspace_id,
        project_id=project_id,
        q=q,
        status=status,
        tags=[t.strip().lower() for t in tags.split(",") if t.strip()] if tags else None,
        archived=archived,
        limit=limit,
        offset=offset,
    )


@router.post("/api/specifications")
def create_specification(
    payload: SpecificationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return SpecificationApplicationService(db, user, command_id=command_id).create_specification(payload)


@router.get("/api/specifications/{specification_id}")
def get_specification(specification_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.get_specification(specification_id=specification_id)


@router.patch("/api/specifications/{specification_id}")
def patch_specification(
    specification_id: str,
    payload: SpecificationPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return SpecificationApplicationService(db, user, command_id=command_id).patch_specification(
        specification_id,
        payload,
    )


@router.post("/api/specifications/{specification_id}/tasks")
def create_specification_task(
    specification_id: str,
    payload: SpecificationTaskCreatePayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return SpecificationApplicationService(db, user, command_id=command_id).create_task_from_specification(
        specification_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        due_date=payload.due_date,
        assignee_id=payload.assignee_id,
        labels=payload.labels,
        external_refs=[item.model_dump() for item in payload.external_refs],
        attachment_refs=[item.model_dump() for item in payload.attachment_refs],
        recurring_rule=payload.recurring_rule,
        task_type=payload.task_type,
        scheduled_instruction=payload.scheduled_instruction,
        scheduled_at_utc=payload.scheduled_at_utc,
        schedule_timezone=payload.schedule_timezone,
    )


@router.post("/api/specifications/{specification_id}/tasks/bulk")
def create_specification_tasks_bulk(
    specification_id: str,
    payload: SpecificationTaskBulkCreatePayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return SpecificationApplicationService(db, user, command_id=command_id).create_tasks_from_specification(
        specification_id=specification_id,
        titles=payload.titles,
        description=payload.description,
        priority=payload.priority,
        due_date=payload.due_date,
        assignee_id=payload.assignee_id,
        labels=payload.labels,
    )


@router.post("/api/specifications/{specification_id}/notes")
def create_specification_note(
    specification_id: str,
    payload: SpecificationNoteCreatePayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return SpecificationApplicationService(db, user, command_id=command_id).create_note_from_specification(
        specification_id,
        title=payload.title,
        body=payload.body,
        tags=payload.tags,
        pinned=payload.pinned,
        external_refs=[item.model_dump() for item in payload.external_refs],
        attachment_refs=[item.model_dump() for item in payload.attachment_refs],
    )


@router.post("/api/specifications/{specification_id}/tasks/{task_id}/link")
def link_task_to_specification(
    specification_id: str,
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return SpecificationApplicationService(db, user, command_id=command_id).link_task_to_specification(
        specification_id,
        task_id,
    )


@router.post("/api/specifications/{specification_id}/tasks/{task_id}/unlink")
def unlink_task_from_specification(
    specification_id: str,
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return SpecificationApplicationService(db, user, command_id=command_id).unlink_task_from_specification(
        specification_id,
        task_id,
    )


@router.post("/api/specifications/{specification_id}/notes/{note_id}/link")
def link_note_to_specification(
    specification_id: str,
    note_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return SpecificationApplicationService(db, user, command_id=command_id).link_note_to_specification(
        specification_id,
        note_id,
    )


@router.post("/api/specifications/{specification_id}/notes/{note_id}/unlink")
def unlink_note_from_specification(
    specification_id: str,
    note_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return SpecificationApplicationService(db, user, command_id=command_id).unlink_note_from_specification(
        specification_id,
        note_id,
    )


@router.post("/api/specifications/{specification_id}/archive")
def archive_specification(
    specification_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return SpecificationApplicationService(db, user, command_id=command_id).archive_specification(specification_id)


@router.post("/api/specifications/{specification_id}/restore")
def restore_specification(
    specification_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return SpecificationApplicationService(db, user, command_id=command_id).restore_specification(specification_id)


@router.post("/api/specifications/{specification_id}/delete")
def delete_specification(
    specification_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return SpecificationApplicationService(db, user, command_id=command_id).delete_specification(specification_id)
