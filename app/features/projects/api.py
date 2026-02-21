from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from features.agents.gateway import build_ui_gateway
from shared.core import (
    Project,
    ProjectCreate,
    ProjectMemberUpsert,
    ProjectPatch,
    ensure_project_access,
    get_command_id,
    get_current_user,
    get_db,
)
from shared.knowledge_graph import (
    graph_context_pack,
    graph_get_project_overview,
    graph_get_project_subgraph,
    require_graph_available,
    search_project_knowledge,
)
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
    ensure_project_access(db, project.workspace_id, project.id, user.id, {"Owner", "Admin", "Member", "Guest"})
    return project


@router.post("/api/projects")
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.create_project(
        name=payload.name,
        workspace_id=payload.workspace_id,
        description=payload.description,
        custom_statuses=payload.custom_statuses,
        external_refs=[item.model_dump() for item in payload.external_refs],
        attachment_refs=[item.model_dump() for item in payload.attachment_refs],
        embedding_enabled=payload.embedding_enabled,
        embedding_model=payload.embedding_model,
        context_pack_evidence_top_k=payload.context_pack_evidence_top_k,
        member_user_ids=payload.member_user_ids,
        command_id=command_id,
    )


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
def project_board(
    project_id: str,
    tags: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    parsed_tags = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else None
    return get_project_board_read_model(db, user, project_id, tags=parsed_tags)


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
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.graph_get_project_overview(project_id=project_id, top_limit=top_limit)


@router.get("/api/projects/{project_id}/knowledge-graph/context-pack")
def project_knowledge_graph_context_pack(
    project_id: str,
    focus_entity_type: str | None = None,
    focus_entity_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=60),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.graph_context_pack(
        project_id=project_id,
        focus_entity_type=focus_entity_type,
        focus_entity_id=focus_entity_id,
        limit=limit,
    )


@router.get("/api/projects/{project_id}/knowledge-graph/subgraph")
def project_knowledge_graph_subgraph(
    project_id: str,
    limit_nodes: int = Query(default=48, ge=8, le=120),
    limit_edges: int = Query(default=160, ge=8, le=320),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        require_graph_available()
        return graph_get_project_subgraph(
            project_id=project.id,
            limit_nodes=limit_nodes,
            limit_edges=limit_edges,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Knowledge graph is unavailable: {exc}") from exc


@router.get("/api/projects/{project_id}/knowledge/search")
def project_knowledge_search(
    project_id: str,
    q: str = Query(min_length=1),
    focus_entity_type: str | None = None,
    focus_entity_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.search_project_knowledge(
        project_id=project_id,
        query=q,
        focus_entity_type=focus_entity_type,
        focus_entity_id=focus_entity_id,
        limit=limit,
    )


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
