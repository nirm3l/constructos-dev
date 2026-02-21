from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from features.agents.gateway import build_ui_gateway
from shared.core import (
    ReorderPayload,
    TaskGroupCreate,
    TaskGroupPatch,
    User,
    ensure_project_access,
    get_command_id,
    get_current_user,
    get_db,
    load_task_group_view,
)

from .application import TaskGroupApplicationService
from .read_models import TaskGroupListQuery, list_task_groups_read_model


router = APIRouter()


@router.get("/api/task-groups")
def list_task_groups(
    workspace_id: str,
    project_id: str,
    q: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.list_task_groups(
        workspace_id=workspace_id,
        project_id=project_id,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.post("/api/task-groups")
def create_task_group(
    payload: TaskGroupCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.create_task_group(
        name=payload.name,
        project_id=payload.project_id,
        workspace_id=payload.workspace_id,
        description=payload.description,
        color=payload.color,
        command_id=command_id,
    )


@router.get("/api/task-groups/{group_id}")
def get_task_group(group_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    group = load_task_group_view(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Task group not found")
    ensure_project_access(db, group["workspace_id"], group["project_id"], user.id, {"Owner", "Admin", "Member", "Guest"})
    return group


@router.patch("/api/task-groups/{group_id}")
def patch_task_group(
    group_id: str,
    payload: TaskGroupPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.update_task_group(
        group_id=group_id,
        patch=payload.model_dump(exclude_unset=True),
        command_id=command_id,
    )


@router.post("/api/task-groups/{group_id}/delete")
def delete_task_group(
    group_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.delete_task_group(group_id=group_id, command_id=command_id)


@router.post("/api/task-groups/reorder")
def reorder_task_groups(
    payload: ReorderPayload,
    workspace_id: str,
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.reorder_task_groups(
        ordered_ids=payload.ordered_ids,
        project_id=project_id,
        workspace_id=workspace_id,
        command_id=command_id,
    )
