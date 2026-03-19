from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.core import User, get_command_id, get_current_user, get_db

from .service import get_doctor_status, reset_doctor_workspace, run_doctor_workspace, seed_doctor_workspace

router = APIRouter()


@router.get("/api/workspaces/{workspace_id}/doctor")
def workspace_doctor_status(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return get_doctor_status(db, workspace_id=workspace_id, user=user)


@router.post("/api/workspaces/{workspace_id}/doctor/seed")
def workspace_doctor_seed(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return seed_doctor_workspace(db, workspace_id=workspace_id, user=user, command_id=command_id)


@router.post("/api/workspaces/{workspace_id}/doctor/run")
def workspace_doctor_run(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return run_doctor_workspace(db, workspace_id=workspace_id, user=user, command_id=command_id)


@router.post("/api/workspaces/{workspace_id}/doctor/reset")
def workspace_doctor_reset(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return reset_doctor_workspace(db, workspace_id=workspace_id, user=user, command_id=command_id)
