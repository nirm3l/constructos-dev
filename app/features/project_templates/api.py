from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.core import get_command_id, get_current_user, get_db

from .application import ProjectTemplateApplicationService
from .schemas import ProjectFromTemplateCreate, ProjectFromTemplatePreview

router = APIRouter()


@router.get("/api/project-templates")
def list_project_templates(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return ProjectTemplateApplicationService(db, user).list_templates()


@router.get("/api/project-templates/{template_key}")
def get_project_template(
    template_key: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return ProjectTemplateApplicationService(db, user).get_template(template_key)


@router.post("/api/projects/from-template")
def create_project_from_template(
    payload: ProjectFromTemplateCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return ProjectTemplateApplicationService(db, user, command_id=command_id).create_project_from_template(payload)


@router.post("/api/projects/from-template/preview")
def preview_project_from_template(
    payload: ProjectFromTemplatePreview,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return ProjectTemplateApplicationService(db, user).preview_project_from_template(payload)
