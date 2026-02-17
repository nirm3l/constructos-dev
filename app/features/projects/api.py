from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from shared.core import Project, ProjectCreate, ProjectMemberUpsert, ProjectPatch, ensure_role, get_command_id, get_current_user, get_db
from shared.knowledge_graph import graph_context_pack, graph_get_project_overview, require_graph_available
from .application import ProjectApplicationService
from .read_models import (
    get_project_activity_read_model,
    get_project_board_read_model,
    get_project_members_read_model,
    get_project_tags_read_model,
)

router = APIRouter()


def _load_project_with_access(db: Session, user, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    return project


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


@router.get("/api/projects/{project_id}/knowledge-graph/overview")
def project_knowledge_graph_overview(
    project_id: str,
    top_limit: int = Query(default=8, ge=1, le=30),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        require_graph_available()
        return graph_get_project_overview(project_id=project.id, top_limit=top_limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Knowledge graph is unavailable: {exc}") from exc


@router.get("/api/projects/{project_id}/knowledge-graph/context-pack")
def project_knowledge_graph_context_pack(
    project_id: str,
    focus_entity_type: str | None = None,
    focus_entity_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=60),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    if bool(str(focus_entity_type or "").strip()) != bool(str(focus_entity_id or "").strip()):
        raise HTTPException(status_code=400, detail="focus_entity_type and focus_entity_id must be provided together")
    try:
        require_graph_available()
        return graph_context_pack(
            project_id=project.id,
            focus_entity_type=focus_entity_type,
            focus_entity_id=focus_entity_id,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Knowledge graph is unavailable: {exc}") from exc


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
