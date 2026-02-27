from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from features.agents.gateway import build_ui_gateway
from shared.core import NoteCreate, NotePatch, User, ensure_project_access, ensure_role, get_command_id, get_current_user, get_db, load_note_view

from .application import NoteApplicationService
from .read_models import NoteListQuery, list_notes_read_model


router = APIRouter()


@router.get("/api/notes")
def list_notes(
    workspace_id: str,
    project_id: str,
    note_group_id: str | None = None,
    task_id: str | None = None,
    specification_id: str | None = None,
    q: str | None = None,
    tags: str | None = None,
    archived: bool = False,
    pinned: bool | None = None,
    limit: int = Query(default=30, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.list_notes(
        workspace_id=workspace_id,
        project_id=project_id,
        note_group_id=note_group_id,
        task_id=task_id,
        specification_id=specification_id,
        q=q,
        tags=[t.strip().lower() for t in tags.split(",") if t.strip()] if tags else None,
        archived=archived,
        pinned=pinned,
        limit=limit,
        offset=offset,
    )


@router.post("/api/notes")
def create_note(
    payload: NoteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.create_note(
        title=payload.title,
        body=payload.body,
        workspace_id=payload.workspace_id,
        project_id=payload.project_id,
        note_group_id=payload.note_group_id,
        task_id=payload.task_id,
        specification_id=payload.specification_id,
        tags=payload.tags,
        pinned=payload.pinned,
        external_refs=[item.model_dump() for item in payload.external_refs],
        attachment_refs=[item.model_dump() for item in payload.attachment_refs],
        force_new=payload.force_new,
        command_id=command_id,
    )


@router.get("/api/notes/{note_id}")
def get_note(note_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.get_note(note_id=note_id)


@router.patch("/api/notes/{note_id}")
def patch_note(
    note_id: str,
    payload: NotePatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.update_note(
        note_id=note_id,
        patch=payload.model_dump(exclude_unset=True),
        command_id=command_id,
    )


@router.post("/api/notes/{note_id}/archive")
def archive_note(
    note_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.archive_note(note_id=note_id, command_id=command_id)


@router.post("/api/notes/{note_id}/restore")
def restore_note(
    note_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.restore_note(note_id=note_id, command_id=command_id)


@router.post("/api/notes/{note_id}/pin")
def pin_note(
    note_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.pin_note(note_id=note_id, command_id=command_id)


@router.post("/api/notes/{note_id}/unpin")
def unpin_note(
    note_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.unpin_note(note_id=note_id, command_id=command_id)


@router.post("/api/notes/{note_id}/delete")
def delete_note(
    note_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.delete_note(note_id=note_id, command_id=command_id)
