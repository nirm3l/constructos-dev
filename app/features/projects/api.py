from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from features.agents.gates import plugin_check_catalog_by_scope
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
    event_storming_set_link_review_status,
    event_storming_get_component_links,
    event_storming_get_entity_links,
    event_storming_get_project_overview,
    event_storming_get_project_subgraph,
    graph_generate_layout,
    graph_context_pack,
    graph_get_project_overview,
    graph_get_project_subgraph,
    require_graph_available,
    search_project_knowledge,
)
from shared.eventing_event_storming import enqueue_event_storming_project_backfill
from .task_dependency_graph import get_project_task_dependency_graph
from .application import ProjectApplicationService
from .read_models import (
    get_project_activity_read_model,
    get_project_board_read_model,
    get_project_members_read_model,
    get_project_tags_read_model,
)
from features.tasks.read_models import get_task_automation_status_read_model
from shared.models import Task

router = APIRouter()


def _project_execution_gate_snapshot(*, db: Session, user, project_id: str) -> dict[str, object]:
    rows = db.execute(
        select(Task.id, Task.title, Task.status)
        .where(
            Task.project_id == project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        )
        .order_by(Task.created_at.asc())
        .limit(300)
    ).all()
    tasks: list[dict[str, object]] = []
    communication_events: list[dict[str, object]] = []
    totals = {
        "tasks_with_gates": 0,
        "gates_total": 0,
        "blocking_total": 0,
        "pass": 0,
        "fail": 0,
        "waiting": 0,
        "not_applicable": 0,
    }
    communication_totals: dict[str, int] = {}
    for task_id, title, status in rows:
        task_id_text = str(task_id or "").strip()
        if not task_id_text:
            continue
        try:
            automation_status = get_task_automation_status_read_model(db, user, task_id_text)
        except Exception:
            continue
        requested_source = str(automation_status.get("last_requested_source") or "").strip()
        if requested_source:
            requested_at = (
                str(automation_status.get("last_requested_triggered_at") or "").strip()
                or str(automation_status.get("last_agent_run_at") or "").strip()
                or None
            )
            communication_events.append(
                {
                    "delivery": "requested",
                    "task_id": task_id_text,
                    "title": str(title or "").strip(),
                    "status": str(status or "").strip(),
                    "source": requested_source,
                    "source_task_id": str(automation_status.get("last_requested_source_task_id") or "").strip() or None,
                    "reason": str(automation_status.get("last_requested_reason") or "").strip() or None,
                    "trigger_link": str(automation_status.get("last_requested_trigger_link") or "").strip() or None,
                    "correlation_id": str(automation_status.get("last_requested_correlation_id") or "").strip() or None,
                    "lead_handoff_token": str(automation_status.get("last_lead_handoff_token") or "").strip() or None,
                    "dispatch_decision": (
                        automation_status.get("last_dispatch_decision")
                        if isinstance(automation_status.get("last_dispatch_decision"), dict)
                        else None
                    ),
                    "requested_at": requested_at,
                }
            )
            communication_totals[requested_source] = int(communication_totals.get(requested_source) or 0) + 1
        ignored_source = str(automation_status.get("last_ignored_request_source") or "").strip()
        if ignored_source:
            ignored_at = str(automation_status.get("last_ignored_request_triggered_at") or "").strip() or None
            communication_events.append(
                {
                    "delivery": "ignored",
                    "task_id": task_id_text,
                    "title": str(title or "").strip(),
                    "status": str(status or "").strip(),
                    "source": ignored_source,
                    "source_task_id": str(automation_status.get("last_ignored_request_source_task_id") or "").strip() or None,
                    "reason": str(automation_status.get("last_ignored_request_reason") or "").strip() or None,
                    "trigger_link": str(automation_status.get("last_ignored_request_trigger_link") or "").strip() or None,
                    "correlation_id": str(automation_status.get("last_ignored_request_correlation_id") or "").strip() or None,
                    "lead_handoff_token": None,
                    "dispatch_decision": (
                        automation_status.get("last_dispatch_decision")
                        if isinstance(automation_status.get("last_dispatch_decision"), dict)
                        else None
                    ),
                    "requested_at": ignored_at,
                }
            )
            communication_totals[f"ignored:{ignored_source}"] = int(
                communication_totals.get(f"ignored:{ignored_source}") or 0
            ) + 1
        execution_gates = list(automation_status.get("execution_gates") or [])
        if not execution_gates:
            continue
        totals["tasks_with_gates"] = int(totals["tasks_with_gates"]) + 1
        per_task = {
            "task_id": task_id_text,
            "title": str(title or "").strip(),
            "status": str(status or "").strip(),
            "gates_total": 0,
            "blocking_total": 0,
            "pass": 0,
            "fail": 0,
            "waiting": 0,
            "not_applicable": 0,
        }
        for gate in execution_gates:
            if not isinstance(gate, dict):
                continue
            gate_status = str(gate.get("status") or "").strip().lower()
            blocking = bool(gate.get("blocking"))
            per_task["gates_total"] = int(per_task["gates_total"]) + 1
            totals["gates_total"] = int(totals["gates_total"]) + 1
            if blocking:
                per_task["blocking_total"] = int(per_task["blocking_total"]) + 1
                totals["blocking_total"] = int(totals["blocking_total"]) + 1
            if gate_status in {"pass", "fail", "waiting", "not_applicable"}:
                per_task[gate_status] = int(per_task[gate_status]) + 1
                totals[gate_status] = int(totals[gate_status]) + 1
        tasks.append(per_task)
    communication_events.sort(
        key=lambda event: (
            str(event.get("requested_at") or ""),
            str(event.get("task_id") or ""),
        ),
        reverse=True,
    )
    return {
        "execution_gates": {
            "tasks": tasks,
            "totals": totals,
        },
        "workflow_communication": {
            "events": communication_events,
            "totals": communication_totals,
            "events_total": len(communication_events),
        },
    }


class EventStormingLinkReviewPatch(BaseModel):
    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    component_id: str = Field(min_length=1)
    review_status: str = Field(min_length=1)
    confidence: float | None = None


class EventStormingBulkLinkReviewPatch(BaseModel):
    items: list[EventStormingLinkReviewPatch] = Field(default_factory=list)


class GraphLayoutNodeIn(BaseModel):
    entity_id: str = Field(min_length=1)
    entity_type: str = Field(default="Entity")
    title: str = Field(default="")
    degree: int = Field(default=0)


class GraphLayoutEdgeIn(BaseModel):
    source_entity_id: str = Field(min_length=1)
    target_entity_id: str = Field(min_length=1)
    relationship: str = Field(default="RELATED")


class GraphAiLayoutRequest(BaseModel):
    nodes: list[GraphLayoutNodeIn] = Field(default_factory=list)
    edges: list[GraphLayoutEdgeIn] = Field(default_factory=list)
    node_width: int = Field(default=220, ge=120, le=420)
    node_height: int = Field(default=74, ge=48, le=280)


class ProjectPluginConfigValidateRequest(BaseModel):
    draft_config: dict[str, object] = Field(default_factory=dict)


class ProjectPluginConfigApplyRequest(BaseModel):
    config: dict[str, object] = Field(default_factory=dict)
    expected_version: int | None = Field(default=None, ge=1)
    enabled: bool | None = None


class ProjectPluginEnabledPatch(BaseModel):
    enabled: bool


class ProjectPluginConfigDiffRequest(BaseModel):
    draft_config: dict[str, object] = Field(default_factory=dict)


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
        automation_max_parallel_tasks=payload.automation_max_parallel_tasks,
        chat_index_mode=payload.chat_index_mode,
        chat_attachment_ingestion_mode=payload.chat_attachment_ingestion_mode,
        event_storming_enabled=payload.event_storming_enabled,
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
    project = _load_project_with_access(db, user, project_id)
    was_enabled = bool(getattr(project, "event_storming_enabled", True))
    updated = ProjectApplicationService(db, user, command_id=command_id).patch_project(project_id, payload)
    requested = payload.model_dump(exclude_unset=True)
    now_enabled = bool(updated.get("event_storming_enabled", was_enabled))
    if "event_storming_enabled" in requested and requested.get("event_storming_enabled") is True and not was_enabled and now_enabled:
        enqueue_event_storming_project_backfill(project_id=project_id, workspace_id=str(project.workspace_id))
    return updated


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


@router.get("/api/projects/{project_id}/checks/verify")
def project_checks_verify(
    project_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    team_mode = gateway.verify_team_mode_workflow(project_id=project_id)
    delivery = gateway.verify_delivery_workflow(project_id=project_id)
    project_execution_snapshot = _project_execution_gate_snapshot(db=db, user=user, project_id=project_id)
    return {
        "project_id": project_id,
        "team_mode": team_mode,
        "delivery": delivery,
        "execution_gates": project_execution_snapshot.get("execution_gates") or {"tasks": [], "totals": {}},
        "workflow_communication": project_execution_snapshot.get("workflow_communication")
        or {"events": [], "totals": {}, "events_total": 0},
        "catalog": plugin_check_catalog_by_scope(),
        "ok": bool(team_mode.get("ok")) and bool(delivery.get("ok")),
    }


@router.get("/api/projects/{project_id}/plugins/{plugin_key}")
def project_plugin_config_get(
    project_id: str,
    plugin_key: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _load_project_with_access(db, user, project_id)
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.get_project_plugin_config(
        project_id=project_id,
        plugin_key=plugin_key,
    )


@router.post("/api/projects/{project_id}/plugins/{plugin_key}/validate")
def project_plugin_config_validate(
    project_id: str,
    plugin_key: str,
    payload: ProjectPluginConfigValidateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _load_project_with_access(db, user, project_id)
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.validate_project_plugin_config(
        project_id=project_id,
        plugin_key=plugin_key,
        draft_config=payload.draft_config,
    )


@router.post("/api/projects/{project_id}/plugins/{plugin_key}/apply")
def project_plugin_config_apply(
    project_id: str,
    plugin_key: str,
    payload: ProjectPluginConfigApplyRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _load_project_with_access(db, user, project_id)
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.apply_project_plugin_config(
        project_id=project_id,
        plugin_key=plugin_key,
        config=payload.config,
        expected_version=payload.expected_version,
        enabled=payload.enabled,
    )


@router.post("/api/projects/{project_id}/plugins/{plugin_key}/enabled")
def project_plugin_enabled_patch(
    project_id: str,
    plugin_key: str,
    payload: ProjectPluginEnabledPatch,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _load_project_with_access(db, user, project_id)
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.set_project_plugin_enabled(
        project_id=project_id,
        plugin_key=plugin_key,
        enabled=bool(payload.enabled),
    )


@router.post("/api/projects/{project_id}/plugins/{plugin_key}/diff")
def project_plugin_config_diff(
    project_id: str,
    plugin_key: str,
    payload: ProjectPluginConfigDiffRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _load_project_with_access(db, user, project_id)
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.diff_project_plugin_config(
        project_id=project_id,
        plugin_key=plugin_key,
        draft_config=payload.draft_config,
    )


@router.get("/api/projects/{project_id}/capabilities")
def project_capabilities_get(
    project_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _load_project_with_access(db, user, project_id)
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.get_project_capabilities(
        project_id=project_id,
    )


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


@router.get("/api/projects/{project_id}/task-dependency-graph")
def project_task_dependency_graph(
    project_id: str,
    limit_nodes: int = Query(default=240, ge=8, le=600),
    limit_edges: int = Query(default=1600, ge=8, le=4000),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    return get_project_task_dependency_graph(
        db=db,
        project_id=project.id,
        limit_nodes=limit_nodes,
        limit_edges=limit_edges,
    )


@router.post("/api/projects/{project_id}/knowledge-graph/layout")
def project_knowledge_graph_layout(
    project_id: str,
    payload: GraphAiLayoutRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        return graph_generate_layout(
            project_id=project.id,
            project_name=str(project.name or project.id),
            nodes=[row.model_dump() for row in payload.nodes],
            edges=[row.model_dump() for row in payload.edges],
            node_width=payload.node_width,
            node_height=payload.node_height,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AI layout is unavailable: {exc}") from exc


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


@router.get("/api/projects/{project_id}/event-storming/overview")
def project_event_storming_overview(
    project_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        require_graph_available()
        return event_storming_get_project_overview(project.id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Event storming projection is unavailable: {exc}") from exc


@router.get("/api/projects/{project_id}/event-storming/subgraph")
def project_event_storming_subgraph(
    project_id: str,
    limit_nodes: int = Query(default=120, ge=16, le=300),
    limit_edges: int = Query(default=220, ge=16, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        require_graph_available()
        return event_storming_get_project_subgraph(
            project_id=project.id,
            limit_nodes=limit_nodes,
            limit_edges=limit_edges,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Event storming projection is unavailable: {exc}") from exc


@router.get("/api/projects/{project_id}/event-storming/entity-links")
def project_event_storming_entity_links(
    project_id: str,
    entity_type: str = Query(..., min_length=1),
    entity_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        require_graph_available()
        return event_storming_get_entity_links(
            project_id=project.id,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Event storming projection is unavailable: {exc}") from exc


@router.get("/api/projects/{project_id}/event-storming/component-links")
def project_event_storming_component_links(
    project_id: str,
    component_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        require_graph_available()
        return event_storming_get_component_links(
            project_id=project.id,
            component_id=component_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Event storming projection is unavailable: {exc}") from exc


@router.post("/api/projects/{project_id}/event-storming/review-link")
def project_event_storming_review_link(
    project_id: str,
    payload: EventStormingLinkReviewPatch,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        require_graph_available()
        return event_storming_set_link_review_status(
            project_id=project.id,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            component_id=payload.component_id,
            review_status=payload.review_status,
            confidence=payload.confidence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Event storming projection is unavailable: {exc}") from exc


@router.post("/api/projects/{project_id}/event-storming/review-links")
def project_event_storming_review_links(
    project_id: str,
    payload: EventStormingBulkLinkReviewPatch,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    if not payload.items:
        return {"project_id": project.id, "updated": [], "errors": []}
    updated: list[dict] = []
    errors: list[dict] = []
    try:
        require_graph_available()
        for idx, item in enumerate(payload.items):
            try:
                updated.append(
                    event_storming_set_link_review_status(
                        project_id=project.id,
                        entity_type=item.entity_type,
                        entity_id=item.entity_id,
                        component_id=item.component_id,
                        review_status=item.review_status,
                        confidence=item.confidence,
                    )
                )
            except Exception as exc:
                errors.append({"index": idx, "entity_id": item.entity_id, "component_id": item.component_id, "detail": str(exc)})
        return {"project_id": project.id, "updated": updated, "errors": errors}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Event storming projection is unavailable: {exc}") from exc


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
