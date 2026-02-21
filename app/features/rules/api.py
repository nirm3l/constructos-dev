from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from features.agents.gateway import build_ui_gateway
from shared.core import (
    ProjectRuleCreate,
    ProjectRulePatch,
    User,
    ensure_project_access,
    ensure_role,
    get_command_id,
    get_current_user,
    get_db,
    load_project_rule_view,
)

from .application import ProjectRuleApplicationService
from .read_models import ProjectRuleListQuery, list_project_rules_read_model

router = APIRouter()


@router.get("/api/project-rules")
def list_project_rules(
    workspace_id: str,
    project_id: str,
    q: str | None = None,
    limit: int = Query(default=30, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.list_project_rules(
        workspace_id=workspace_id,
        project_id=project_id,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.post("/api/project-rules")
def create_project_rule(
    payload: ProjectRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.create_project_rule(
        title=payload.title,
        project_id=payload.project_id,
        workspace_id=payload.workspace_id,
        body=payload.body,
        command_id=command_id,
    )


@router.get("/api/project-rules/{rule_id}")
def get_project_rule(rule_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.get_project_rule(rule_id=rule_id)


@router.patch("/api/project-rules/{rule_id}")
def patch_project_rule(
    rule_id: str,
    payload: ProjectRulePatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.update_project_rule(
        rule_id=rule_id,
        patch=payload.model_dump(exclude_unset=True),
        command_id=command_id,
    )


@router.post("/api/project-rules/{rule_id}/delete")
def delete_project_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.delete_project_rule(rule_id=rule_id, command_id=command_id)
