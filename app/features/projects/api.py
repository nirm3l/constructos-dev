from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.core import ProjectCreate, ProjectMemberUpsert, ProjectPatch, get_command_id, get_current_user, get_db
from .application import ProjectApplicationService
from .read_models import (
    get_project_activity_read_model,
    get_project_board_read_model,
    get_project_members_read_model,
    get_project_tags_read_model,
)

router = APIRouter()


@router.post("/api/projects")
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return ProjectApplicationService(db, user, command_id=command_id).create_project(payload)


@router.delete("/api/projects/{project_id}")
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return ProjectApplicationService(db, user, command_id=command_id).delete_project(project_id)


@router.patch("/api/projects/{project_id}")
def patch_project(
    project_id: str,
    payload: ProjectPatch,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return ProjectApplicationService(db, user, command_id=command_id).patch_project(project_id, payload)


@router.get("/api/projects/{project_id}/board")
def project_board(project_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return get_project_board_read_model(db, user, project_id)


@router.get("/api/projects/{project_id}/activity")
def project_activity(project_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return get_project_activity_read_model(db, user, project_id)


@router.get("/api/projects/{project_id}/tags")
def project_tags(project_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return get_project_tags_read_model(db, user, project_id)


@router.get("/api/projects/{project_id}/members")
def project_members(project_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return get_project_members_read_model(db, user, project_id)


@router.post("/api/projects/{project_id}/members")
def add_project_member(
    project_id: str,
    payload: ProjectMemberUpsert,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return ProjectApplicationService(db, user, command_id=command_id).add_project_member(
        project_id=project_id,
        user_id=payload.user_id,
        role=payload.role,
    )


@router.post("/api/projects/{project_id}/members/{member_user_id}/remove")
def remove_project_member(
    project_id: str,
    member_user_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return ProjectApplicationService(db, user, command_id=command_id).remove_project_member(
        project_id=project_id,
        user_id=member_user_id,
    )
