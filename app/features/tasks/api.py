import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.core import (
    ActivityLog,
    BulkAction,
    CommentCreate,
    ReorderPayload,
    Task,
    TaskAutomationRun,
    TaskComment,
    TaskCreate,
    TaskPatch,
    TaskWatcher,
    User,
    ensure_role,
    export_tasks_response,
    get_command_id,
    get_current_user,
    get_db,
    get_user_zoneinfo,
    serialize_task,
    to_iso_utc,
)
from .application import TaskApplicationService
from .read_models import TaskListQuery, get_task_automation_status_read_model, list_tasks_read_model

router = APIRouter()


@router.get("/api/tasks")
def list_tasks(
    workspace_id: str,
    project_id: str,
    view: str | None = None,
    q: str | None = None,
    status: str | None = None,
    tags: str | None = None,
    label: str | None = None,
    assignee_id: str | None = None,
    due_from: datetime | None = None,
    due_to: datetime | None = None,
    priority: str | None = None,
    archived: bool = False,
    limit: int = Query(default=30, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    return list_tasks_read_model(
        db,
        user,
        TaskListQuery(
            workspace_id=workspace_id,
            project_id=project_id,
            view=view,
            q=q,
            status=status,
            tags=[t.strip().lower() for t in tags.split(",") if t.strip()] if tags else None,
            label=label,
            assignee_id=assignee_id,
            due_from=due_from,
            due_to=due_to,
            priority=priority,
            archived=archived,
            limit=limit,
            offset=offset,
        ),
    )


@router.post("/api/tasks")
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).create_task(payload)


@router.patch("/api/tasks/{task_id}")
def patch_task(
    task_id: str,
    payload: TaskPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).patch_task(task_id, payload)


@router.post("/api/tasks/{task_id}/complete")
def complete_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).complete_task(task_id)


@router.post("/api/tasks/{task_id}/reopen")
def reopen_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).reopen_task(task_id)


@router.post("/api/tasks/{task_id}/archive")
def archive_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).archive_task(task_id)


@router.post("/api/tasks/{task_id}/restore")
def restore_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).restore_task(task_id)


@router.post("/api/tasks/bulk")
def bulk_action(
    payload: BulkAction,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).bulk_action(payload)


@router.post("/api/tasks/reorder")
def reorder_tasks(
    payload: ReorderPayload,
    workspace_id: str,
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).reorder_tasks(workspace_id, project_id, payload)


@router.get("/api/calendar")
def calendar_view(
    workspace_id: str,
    project_id: str,
    from_date: date,
    to_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    user_tz = get_user_zoneinfo(user)
    start = datetime.combine(from_date, datetime.min.time(), tzinfo=user_tz).astimezone(timezone.utc)
    end = datetime.combine(to_date, datetime.max.time(), tzinfo=user_tz).astimezone(timezone.utc)
    tasks = db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.project_id == project_id,
            Task.due_date >= start,
            Task.due_date <= end,
            Task.is_deleted == False,
        )
    ).scalars().all()
    return {"items": [serialize_task(t) for t in tasks]}


@router.post("/api/tasks/{task_id}/comments")
def add_comment(
    task_id: str,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).add_comment(task_id, payload)


@router.get("/api/tasks/{task_id}/comments")
def list_comments(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.get(Task, task_id)
    if not task or task.is_deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    ensure_role(db, task.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    comments = db.execute(select(TaskComment).where(TaskComment.task_id == task_id).order_by(TaskComment.created_at.desc())).scalars().all()
    return [{"id": c.id, "task_id": c.task_id, "user_id": c.user_id, "body": c.body, "created_at": to_iso_utc(c.created_at)} for c in comments]


@router.post("/api/tasks/{task_id}/comments/{comment_id}/delete")
def delete_comment(
    task_id: str,
    comment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).delete_comment(task_id, comment_id)


@router.post("/api/tasks/{task_id}/watch")
def toggle_watch(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).toggle_watch(task_id)


@router.get("/api/tasks/{task_id}/activity")
def task_activity(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.get(Task, task_id)
    if not task or task.is_deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    ensure_role(db, task.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    logs = db.execute(select(ActivityLog).where(ActivityLog.task_id == task_id).order_by(ActivityLog.created_at.desc()).limit(200)).scalars().all()
    return [{"id": l.id, "action": l.action, "actor_id": l.actor_id, "details": json.loads(l.details or "{}"), "created_at": to_iso_utc(l.created_at)} for l in logs]


@router.get("/api/export")
def export_tasks(
    workspace_id: str,
    project_id: str,
    format: str = "json",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member"})
    return export_tasks_response(db, workspace_id, project_id, format)


@router.post("/api/tasks/{task_id}/automation/run")
def request_automation_run(
    task_id: str,
    payload: TaskAutomationRun,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).request_automation_run(task_id, payload)


@router.get("/api/tasks/{task_id}/automation")
def task_automation_status(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_task_automation_status_read_model(db, user, task_id)
