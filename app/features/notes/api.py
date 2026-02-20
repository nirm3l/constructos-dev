from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

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
    limit: int = Query(default=30, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_project_access(db, workspace_id, project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    return list_notes_read_model(
        db,
        user,
        NoteListQuery(
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
        ),
    )


@router.post("/api/notes")
def create_note(
    payload: NoteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NoteApplicationService(db, user, command_id=command_id).create_note(payload)


@router.get("/api/notes/{note_id}")
def get_note(note_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    note = load_note_view(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    project_id = str(note.get("project_id") or "")
    if project_id:
        ensure_project_access(db, note["workspace_id"], project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    else:
        ensure_role(db, note["workspace_id"], user.id, {"Owner", "Admin", "Member", "Guest"})
    return note


@router.patch("/api/notes/{note_id}")
def patch_note(
    note_id: str,
    payload: NotePatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NoteApplicationService(db, user, command_id=command_id).patch_note(note_id, payload)


@router.post("/api/notes/{note_id}/archive")
def archive_note(
    note_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NoteApplicationService(db, user, command_id=command_id).archive_note(note_id)


@router.post("/api/notes/{note_id}/restore")
def restore_note(
    note_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NoteApplicationService(db, user, command_id=command_id).restore_note(note_id)


@router.post("/api/notes/{note_id}/pin")
def pin_note(
    note_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NoteApplicationService(db, user, command_id=command_id).pin_note(note_id)


@router.post("/api/notes/{note_id}/unpin")
def unpin_note(
    note_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NoteApplicationService(db, user, command_id=command_id).unpin_note(note_id)


@router.post("/api/notes/{note_id}/delete")
def delete_note(
    note_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NoteApplicationService(db, user, command_id=command_id).delete_note(note_id)
