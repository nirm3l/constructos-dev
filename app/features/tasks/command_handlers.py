from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared.core import (
    BulkAction,
    CommentCreate,
    ReorderPayload,
    Task,
    TaskComment,
    TaskCreate,
    TaskPatch,
    TaskWatcher,
    User,
    append_event,
    allocate_id,
    ensure_role,
    get_user_zoneinfo,
    load_task_command_state,
    load_task_view,
    normalize_datetime_to_utc,
    to_iso_utc,
)
from .domain import (
    EVENT_ARCHIVED,
    EVENT_COMMENT_ADDED,
    EVENT_COMPLETED,
    EVENT_CREATED,
    EVENT_DELETED,
    EVENT_REOPENED,
    EVENT_REORDERED,
    EVENT_RESTORED,
    EVENT_UPDATED,
    EVENT_WATCH_TOGGLED,
)


def require_task_command_state(db: Session, user: User, task_id: str, *, allowed: set[str]) -> tuple[str, str | None, str, bool]:
    state = load_task_command_state(db, task_id)
    if not state or state.is_deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    ensure_role(db, state.workspace_id, user.id, allowed)
    return state.workspace_id, state.project_id, state.status, state.archived


@dataclass(frozen=True, slots=True)
class CommandContext:
    db: Session
    user: User


@dataclass(frozen=True, slots=True)
class CreateTaskHandler:
    ctx: CommandContext
    payload: TaskCreate

    def __call__(self) -> dict:
        ensure_role(self.ctx.db, self.payload.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member"})
        user_tz = get_user_zoneinfo(self.ctx.user)
        tid = allocate_id(self.ctx.db)
        max_order = self.ctx.db.execute(select(func.max(Task.order_index)).where(Task.workspace_id == self.payload.workspace_id)).scalar() or 0
        append_event(
            self.ctx.db,
            aggregate_type="Task",
            aggregate_id=tid,
            event_type=EVENT_CREATED,
            payload={
                "workspace_id": self.payload.workspace_id,
                "project_id": self.payload.project_id,
                "title": self.payload.title.strip(),
                "description": self.payload.description,
                "status": "To do",
                "priority": self.payload.priority,
                "due_date": to_iso_utc(normalize_datetime_to_utc(self.payload.due_date, user_tz)),
                "assignee_id": self.payload.assignee_id,
                "labels": self.payload.labels,
                "subtasks": self.payload.subtasks,
                "attachments": self.payload.attachments,
                "recurring_rule": self.payload.recurring_rule,
                "order_index": max_order + 1,
            },
            metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": self.payload.workspace_id,
                "project_id": self.payload.project_id,
                "task_id": tid,
            },
            expected_version=0,
        )
        self.ctx.db.commit()
        task_view = load_task_view(self.ctx.db, tid)
        if task_view is None:
            raise HTTPException(status_code=404, detail="Task not found after create")
        return task_view


@dataclass(frozen=True, slots=True)
class PatchTaskHandler:
    ctx: CommandContext
    task_id: str
    payload: TaskPatch

    def __call__(self) -> dict:
        user_tz = get_user_zoneinfo(self.ctx.user)
        data = self.payload.model_dump(exclude_unset=True)
        workspace_id, project_id, _, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        event_payload = dict(data)
        if "due_date" in event_payload:
            event_payload["due_date"] = to_iso_utc(normalize_datetime_to_utc(event_payload["due_date"], user_tz))
        append_event(
            self.ctx.db,
            aggregate_type="Task",
            aggregate_id=self.task_id,
            event_type=EVENT_UPDATED,
            payload=event_payload,
            metadata={"actor_id": self.ctx.user.id, "workspace_id": workspace_id, "project_id": project_id, "task_id": self.task_id},
        )
        self.ctx.db.commit()
        task_view = load_task_view(self.ctx.db, self.task_id)
        if task_view is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task_view


@dataclass(frozen=True, slots=True)
class CompleteTaskHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, status, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        if status == "Done":
            raise HTTPException(status_code=409, detail="Task already completed")
        append_event(
            self.ctx.db,
            aggregate_type="Task",
            aggregate_id=self.task_id,
            event_type=EVENT_COMPLETED,
            payload={"completed_at": to_iso_utc(datetime.now(timezone.utc))},
            metadata={"actor_id": self.ctx.user.id, "workspace_id": workspace_id, "project_id": project_id, "task_id": self.task_id},
        )
        self.ctx.db.commit()
        task_view = load_task_view(self.ctx.db, self.task_id)
        if task_view is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task_view


@dataclass(frozen=True, slots=True)
class ReopenTaskHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, status, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        if status != "Done":
            raise HTTPException(status_code=409, detail="Task is not completed")
        append_event(
            self.ctx.db,
            aggregate_type="Task",
            aggregate_id=self.task_id,
            event_type=EVENT_REOPENED,
            payload={"status": "To do"},
            metadata={"actor_id": self.ctx.user.id, "workspace_id": workspace_id, "project_id": project_id, "task_id": self.task_id},
        )
        self.ctx.db.commit()
        task_view = load_task_view(self.ctx.db, self.task_id)
        if task_view is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task_view


@dataclass(frozen=True, slots=True)
class ArchiveTaskHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, _, archived = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        if archived:
            raise HTTPException(status_code=409, detail="Task already archived")
        append_event(
            self.ctx.db,
            aggregate_type="Task",
            aggregate_id=self.task_id,
            event_type=EVENT_ARCHIVED,
            payload={},
            metadata={"actor_id": self.ctx.user.id, "workspace_id": workspace_id, "project_id": project_id, "task_id": self.task_id},
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class RestoreTaskHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, _, archived = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        if not archived:
            raise HTTPException(status_code=409, detail="Task is not archived")
        append_event(
            self.ctx.db,
            aggregate_type="Task",
            aggregate_id=self.task_id,
            event_type=EVENT_RESTORED,
            payload={},
            metadata={"actor_id": self.ctx.user.id, "workspace_id": workspace_id, "project_id": project_id, "task_id": self.task_id},
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class BulkTaskActionHandler:
    ctx: CommandContext
    payload: BulkAction

    def __call__(self, task_id: str) -> bool:
        workspace_id, project_id, status, archived = require_task_command_state(self.ctx.db, self.ctx.user, task_id, allowed={"Owner", "Admin", "Member"})
        if self.payload.action == "complete":
            if status == "Done":
                return False
            et, ep = EVENT_COMPLETED, {"completed_at": to_iso_utc(datetime.now(timezone.utc))}
        elif self.payload.action == "archive":
            if archived:
                return False
            et, ep = EVENT_ARCHIVED, {}
        elif self.payload.action == "delete":
            et, ep = EVENT_DELETED, {}
        elif self.payload.action == "set_status":
            et, ep = EVENT_UPDATED, {"status": self.payload.payload.get("status", status)}
        elif self.payload.action == "reopen":
            if status != "Done":
                return False
            et, ep = EVENT_REOPENED, {"status": self.payload.payload.get("status", "To do")}
        else:
            return False

        append_event(
            self.ctx.db,
            aggregate_type="Task",
            aggregate_id=task_id,
            event_type=et,
            payload=ep,
            metadata={"actor_id": self.ctx.user.id, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id},
        )
        self.ctx.db.commit()
        return True


@dataclass(frozen=True, slots=True)
class ReorderTasksHandler:
    ctx: CommandContext
    workspace_id: str
    payload: ReorderPayload

    def __call__(self, task_id: str, order_index: int) -> bool:
        state = load_task_command_state(self.ctx.db, task_id)
        if not state or state.is_deleted or state.workspace_id != self.workspace_id:
            return False
        append_event(
            self.ctx.db,
            aggregate_type="Task",
            aggregate_id=task_id,
            event_type=EVENT_REORDERED,
            payload={"order_index": order_index, "status": self.payload.status},
            metadata={"actor_id": self.ctx.user.id, "workspace_id": self.workspace_id, "project_id": state.project_id, "task_id": task_id},
        )
        self.ctx.db.commit()
        return True


@dataclass(frozen=True, slots=True)
class AddCommentHandler:
    ctx: CommandContext
    task_id: str
    payload: CommentCreate

    def __call__(self) -> dict:
        workspace_id, project_id, _, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member", "Guest"})
        append_event(
            self.ctx.db,
            aggregate_type="Task",
            aggregate_id=self.task_id,
            event_type=EVENT_COMMENT_ADDED,
            payload={"task_id": self.task_id, "user_id": self.ctx.user.id, "body": self.payload.body},
            metadata={"actor_id": self.ctx.user.id, "workspace_id": workspace_id, "project_id": project_id, "task_id": self.task_id},
        )
        self.ctx.db.commit()
        last = self.ctx.db.execute(select(TaskComment).where(TaskComment.task_id == self.task_id).order_by(TaskComment.id.desc()).limit(1)).scalar_one_or_none()
        if last:
            return {"id": last.id, "task_id": self.task_id, "body": last.body, "created_at": to_iso_utc(last.created_at)}
        return {"id": None, "task_id": self.task_id, "body": self.payload.body, "created_at": None}


@dataclass(frozen=True, slots=True)
class ToggleWatchHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, _, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member", "Guest"})
        append_event(
            self.ctx.db,
            aggregate_type="Task",
            aggregate_id=self.task_id,
            event_type=EVENT_WATCH_TOGGLED,
            payload={"task_id": self.task_id, "user_id": self.ctx.user.id},
            metadata={"actor_id": self.ctx.user.id, "workspace_id": workspace_id, "project_id": project_id, "task_id": self.task_id},
        )
        self.ctx.db.commit()
        watched = self.ctx.db.execute(
            select(TaskWatcher).where(TaskWatcher.task_id == self.task_id, TaskWatcher.user_id == self.ctx.user.id)
        ).scalar_one_or_none() is not None
        return {"watched": watched}
