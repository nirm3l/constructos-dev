import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from features.agents.gateway import build_ui_gateway
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
    ensure_project_access,
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
from .read_models import TaskListQuery, list_tasks_read_model

router = APIRouter()


@router.get("/api/tasks")
def list_tasks(
    workspace_id: str,
    project_id: str,
    task_group_id: str | None = None,
    specification_id: str | None = None,
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
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.list_tasks(
        workspace_id=workspace_id,
        project_id=project_id,
        task_group_id=task_group_id,
        specification_id=specification_id,
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
    )


@router.post("/api/tasks")
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    provided_fields = payload.model_fields_set
    return gateway.create_task(
        workspace_id=payload.workspace_id,
        title=payload.title,
        project_id=payload.project_id,
        description=payload.description,
        status=payload.status if "status" in provided_fields else None,
        priority=payload.priority,
        due_date=payload.due_date.isoformat() if payload.due_date else None,
        external_refs=[item.model_dump() for item in payload.external_refs],
        attachment_refs=[item.model_dump() for item in payload.attachment_refs],
        instruction=payload.instruction if "instruction" in provided_fields else None,
        execution_triggers=payload.execution_triggers if "execution_triggers" in provided_fields else None,
        recurring_rule=payload.recurring_rule if "recurring_rule" in provided_fields else None,
        specification_id=payload.specification_id,
        task_group_id=payload.task_group_id,
        task_type=payload.task_type if "task_type" in provided_fields else None,
        scheduled_instruction=payload.scheduled_instruction if "scheduled_instruction" in provided_fields else None,
        scheduled_at_utc=(
            payload.scheduled_at_utc.isoformat()
            if "scheduled_at_utc" in provided_fields and payload.scheduled_at_utc
            else None
        ),
        schedule_timezone=payload.schedule_timezone if "schedule_timezone" in provided_fields else None,
        assignee_id=payload.assignee_id,
        labels=payload.labels,
        command_id=command_id,
    )


@router.patch("/api/tasks/{task_id}")
def patch_task(
    task_id: str,
    payload: TaskPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.update_task(
        task_id=task_id,
        patch=payload.model_dump(exclude_unset=True),
        command_id=command_id,
    )


@router.post("/api/tasks/{task_id}/complete")
def complete_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.complete_task(task_id=task_id, command_id=command_id)


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
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.bulk_task_action(
        task_ids=payload.task_ids,
        action=payload.action,
        payload=payload.payload,
        command_id=command_id,
    )


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
    ensure_project_access(db, workspace_id, project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
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
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.add_task_comment(task_id=task_id, body=payload.body, command_id=command_id)


@router.get("/api/tasks/{task_id}/comments")
def list_comments(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.get(Task, task_id)
    if not task or task.is_deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    ensure_project_access(db, task.workspace_id, task.project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
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
    ensure_project_access(db, task.workspace_id, task.project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    logs = db.execute(select(ActivityLog).where(ActivityLog.task_id == task_id).order_by(ActivityLog.created_at.desc()).limit(200)).scalars().all()
    out = []
    for l in logs:
        details = json.loads(l.details or "{}")
        if isinstance(details, dict):
            details.pop("_event_key", None)
        out.append({"id": l.id, "action": l.action, "actor_id": l.actor_id, "details": details, "created_at": to_iso_utc(l.created_at)})
    return out


@router.get("/api/export")
def export_tasks(
    workspace_id: str,
    project_id: str,
    format: str = "json",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_project_access(db, workspace_id, project_id, user.id, {"Owner", "Admin", "Member"})
    return export_tasks_response(db, workspace_id, project_id, format)


@router.post("/api/tasks/{task_id}/automation/run")
def request_automation_run(
    task_id: str,
    payload: TaskAutomationRun,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.request_task_automation_run(
        task_id=task_id,
        instruction=payload.instruction,
        command_id=command_id,
    )


@router.get("/api/tasks/{task_id}/automation")
def task_automation_status(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.get_task_automation_status(task_id=task_id)
