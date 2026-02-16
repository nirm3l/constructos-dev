from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from shared.core import (
    SpecificationCreate,
    SpecificationPatch,
    User,
    ensure_role,
    get_command_id,
    get_current_user,
    get_db,
    load_specification_view,
)

from .application import SpecificationApplicationService
from .read_models import SpecificationListQuery, list_specifications_read_model

router = APIRouter()


@router.get("/api/specifications")
def list_specifications(
    workspace_id: str,
    project_id: str,
    q: str | None = None,
    status: str | None = None,
    archived: bool = False,
    limit: int = Query(default=30, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    return list_specifications_read_model(
        db,
        user,
        SpecificationListQuery(
            workspace_id=workspace_id,
            project_id=project_id,
            q=q,
            status=status,
            archived=archived,
            limit=limit,
            offset=offset,
        ),
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
    specification = load_specification_view(db, specification_id)
    if not specification:
        raise HTTPException(status_code=404, detail="Specification not found")
    ensure_role(db, specification["workspace_id"], user.id, {"Owner", "Admin", "Member", "Guest"})
    return specification


@router.patch("/api/specifications/{specification_id}")
def patch_specification(
    specification_id: str,
    payload: SpecificationPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return SpecificationApplicationService(db, user, command_id=command_id).patch_specification(specification_id, payload)


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
