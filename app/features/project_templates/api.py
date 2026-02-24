from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from features.agents.gateway import build_ui_gateway
from shared.core import get_command_id, get_current_user, get_db

from .application import ProjectTemplateApplicationService
from .schemas import ProjectFromTemplateCreate, ProjectFromTemplatePreview

router = APIRouter()


@router.get("/api/project-templates")
def list_project_templates(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.list_project_templates()


@router.get("/api/project-templates/{template_key}")
def get_project_template(
    template_key: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.get_project_template(template_key=template_key)


@router.post("/api/projects/from-template")
def create_project_from_template(
    payload: ProjectFromTemplateCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.create_project_from_template(
        template_key=payload.template_key,
        name=payload.name,
        workspace_id=payload.workspace_id,
        description=payload.description,
        custom_statuses=payload.custom_statuses,
        member_user_ids=payload.member_user_ids,
        embedding_enabled=payload.embedding_enabled,
        embedding_model=payload.embedding_model,
        context_pack_evidence_top_k=payload.context_pack_evidence_top_k,
        chat_index_mode=payload.chat_index_mode,
        chat_attachment_ingestion_mode=payload.chat_attachment_ingestion_mode,
        parameters=payload.parameters,
        command_id=command_id,
    )


@router.post("/api/projects/from-template/preview")
def preview_project_from_template(
    payload: ProjectFromTemplatePreview,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.preview_project_from_template(
        template_key=payload.template_key,
        workspace_id=payload.workspace_id,
        name=payload.name,
        description=payload.description,
        custom_statuses=payload.custom_statuses,
        member_user_ids=payload.member_user_ids,
        embedding_enabled=payload.embedding_enabled,
        embedding_model=payload.embedding_model,
        context_pack_evidence_top_k=payload.context_pack_evidence_top_k,
        chat_index_mode=payload.chat_index_mode,
        chat_attachment_ingestion_mode=payload.chat_attachment_ingestion_mode,
        parameters=payload.parameters,
    )
