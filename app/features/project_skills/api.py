from __future__ import annotations

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from features.agents.gateway import build_ui_gateway
from shared.core import get_command_id, get_current_user, get_db

from .schemas import (
    ProjectSkillDeleteRequest,
    ProjectSkillImportRequest,
    ProjectSkillPatch,
    WorkspaceSkillAttachRequest,
    WorkspaceSkillImportRequest,
    WorkspaceSkillPatch,
)

router = APIRouter()


@router.get("/api/project-skills")
def list_project_skills(
    workspace_id: str,
    project_id: str,
    q: str | None = None,
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.list_project_skills(
        workspace_id=workspace_id,
        project_id=project_id,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/api/project-skills/{skill_id}")
def get_project_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.get_project_skill(skill_id=skill_id)


@router.post("/api/project-skills/import")
def import_project_skill(
    payload: ProjectSkillImportRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.import_project_skill(
        workspace_id=payload.workspace_id,
        project_id=payload.project_id,
        source_url=payload.source_url,
        name=payload.name,
        skill_key=payload.skill_key,
        mode=payload.mode,
        trust_level=payload.trust_level,
        command_id=command_id,
    )


@router.post("/api/project-skills/{skill_id}/apply")
def apply_project_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.apply_project_skill(
        skill_id=skill_id,
        command_id=command_id,
    )


@router.post("/api/project-skills/import-file")
async def import_project_skill_file(
    workspace_id: str = Form(...),
    project_id: str = Form(...),
    file: UploadFile = File(...),
    name: str = Form(default=""),
    skill_key: str = Form(default=""),
    mode: str = Form(default="advisory"),
    trust_level: str = Form(default="reviewed"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    file_content = await file.read()
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.import_project_skill_file(
        workspace_id=workspace_id,
        project_id=project_id,
        file_name=file.filename or "",
        file_content=file_content,
        file_content_type=file.content_type or "",
        name=name,
        skill_key=skill_key,
        mode=mode,
        trust_level=trust_level,
        command_id=command_id,
    )


@router.patch("/api/project-skills/{skill_id}")
def patch_project_skill(
    skill_id: str,
    payload: ProjectSkillPatch,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.update_project_skill(
        skill_id=skill_id,
        patch=payload.model_dump(exclude_unset=True),
        command_id=command_id,
    )


@router.post("/api/project-skills/{skill_id}/delete")
def delete_project_skill(
    skill_id: str,
    payload: ProjectSkillDeleteRequest = Body(default_factory=ProjectSkillDeleteRequest),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.delete_project_skill(
        skill_id=skill_id,
        delete_linked_rule=payload.delete_linked_rule,
        command_id=command_id,
    )


@router.get("/api/workspace-skills")
def list_workspace_skills(
    workspace_id: str,
    q: str | None = None,
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.list_workspace_skills(
        workspace_id=workspace_id,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/api/workspace-skills/{skill_id}")
def get_workspace_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.get_workspace_skill(skill_id=skill_id)


@router.post("/api/workspace-skills/import")
def import_workspace_skill(
    payload: WorkspaceSkillImportRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.import_workspace_skill(
        workspace_id=payload.workspace_id,
        source_url=payload.source_url,
        name=payload.name,
        skill_key=payload.skill_key,
        mode=payload.mode,
        trust_level=payload.trust_level,
        command_id=command_id,
    )


@router.post("/api/workspace-skills/import-file")
async def import_workspace_skill_file(
    workspace_id: str = Form(...),
    file: UploadFile = File(...),
    name: str = Form(default=""),
    skill_key: str = Form(default=""),
    mode: str = Form(default="advisory"),
    trust_level: str = Form(default="reviewed"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    file_content = await file.read()
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.import_workspace_skill_file(
        workspace_id=workspace_id,
        file_name=file.filename or "",
        file_content=file_content,
        file_content_type=file.content_type or "",
        name=name,
        skill_key=skill_key,
        mode=mode,
        trust_level=trust_level,
        command_id=command_id,
    )


@router.patch("/api/workspace-skills/{skill_id}")
def patch_workspace_skill(
    skill_id: str,
    payload: WorkspaceSkillPatch,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.update_workspace_skill(
        skill_id=skill_id,
        patch=payload.model_dump(exclude_unset=True),
        command_id=command_id,
    )


@router.post("/api/workspace-skills/{skill_id}/delete")
def delete_workspace_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.delete_workspace_skill(
        skill_id=skill_id,
        command_id=command_id,
    )


@router.post("/api/workspace-skills/{skill_id}/attach")
def attach_workspace_skill_to_project(
    skill_id: str,
    payload: WorkspaceSkillAttachRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.attach_workspace_skill_to_project(
        workspace_skill_id=skill_id,
        workspace_id=payload.workspace_id,
        project_id=payload.project_id,
        command_id=command_id,
    )
