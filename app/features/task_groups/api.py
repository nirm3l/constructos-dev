from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

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
    ensure_project_access(db, workspace_id, project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    return list_task_groups_read_model(
        db,
        user,
        TaskGroupListQuery(
            workspace_id=workspace_id,
            project_id=project_id,
            q=q,
            limit=limit,
            offset=offset,
        ),
    )


@router.post("/api/task-groups")
def create_task_group(
    payload: TaskGroupCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskGroupApplicationService(db, user, command_id=command_id).create_task_group(payload)


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
    return TaskGroupApplicationService(db, user, command_id=command_id).patch_task_group(group_id, payload)


@router.post("/api/task-groups/{group_id}/delete")
def delete_task_group(
    group_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskGroupApplicationService(db, user, command_id=command_id).delete_task_group(group_id)


@router.post("/api/task-groups/reorder")
def reorder_task_groups(
    payload: ReorderPayload,
    workspace_id: str,
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskGroupApplicationService(db, user, command_id=command_id).reorder_task_groups(workspace_id, project_id, payload)
