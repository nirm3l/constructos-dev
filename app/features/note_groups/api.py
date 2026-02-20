from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from shared.core import (
    NoteGroupCreate,
    NoteGroupPatch,
    ReorderPayload,
    User,
    ensure_project_access,
    get_command_id,
    get_current_user,
    get_db,
    load_note_group_view,
)

from .application import NoteGroupApplicationService
from .read_models import NoteGroupListQuery, list_note_groups_read_model


router = APIRouter()


@router.get("/api/note-groups")
def list_note_groups(
    workspace_id: str,
    project_id: str,
    q: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_project_access(db, workspace_id, project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    return list_note_groups_read_model(
        db,
        user,
        NoteGroupListQuery(
            workspace_id=workspace_id,
            project_id=project_id,
            q=q,
            limit=limit,
            offset=offset,
        ),
    )


@router.post("/api/note-groups")
def create_note_group(
    payload: NoteGroupCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NoteGroupApplicationService(db, user, command_id=command_id).create_note_group(payload)


@router.get("/api/note-groups/{group_id}")
def get_note_group(group_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    group = load_note_group_view(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Note group not found")
    ensure_project_access(db, group["workspace_id"], group["project_id"], user.id, {"Owner", "Admin", "Member", "Guest"})
    return group


@router.patch("/api/note-groups/{group_id}")
def patch_note_group(
    group_id: str,
    payload: NoteGroupPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NoteGroupApplicationService(db, user, command_id=command_id).patch_note_group(group_id, payload)


@router.post("/api/note-groups/{group_id}/delete")
def delete_note_group(
    group_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NoteGroupApplicationService(db, user, command_id=command_id).delete_note_group(group_id)


@router.post("/api/note-groups/reorder")
def reorder_note_groups(
    payload: ReorderPayload,
    workspace_id: str,
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NoteGroupApplicationService(db, user, command_id=command_id).reorder_note_groups(workspace_id, project_id, payload)
