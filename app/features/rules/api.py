from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

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
    ensure_project_access(db, workspace_id, project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    return list_project_rules_read_model(
        db,
        user,
        ProjectRuleListQuery(
            workspace_id=workspace_id,
            project_id=project_id,
            q=q,
            limit=limit,
            offset=offset,
        ),
    )


@router.post("/api/project-rules")
def create_project_rule(
    payload: ProjectRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return ProjectRuleApplicationService(db, user, command_id=command_id).create_project_rule(payload)


@router.get("/api/project-rules/{rule_id}")
def get_project_rule(rule_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rule = load_project_rule_view(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Project rule not found")
    ensure_project_access(db, rule["workspace_id"], rule["project_id"], user.id, {"Owner", "Admin", "Member", "Guest"})
    return rule


@router.patch("/api/project-rules/{rule_id}")
def patch_project_rule(
    rule_id: str,
    payload: ProjectRulePatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return ProjectRuleApplicationService(db, user, command_id=command_id).patch_project_rule(rule_id, payload)


@router.post("/api/project-rules/{rule_id}/delete")
def delete_project_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return ProjectRuleApplicationService(db, user, command_id=command_id).delete_project_rule(rule_id)
