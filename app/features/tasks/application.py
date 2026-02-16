from __future__ import annotations

from sqlalchemy.orm import Session

from shared.commanding import execute_command
from shared.core import BulkAction, CommentCreate, ReorderPayload, TaskAutomationRun, TaskCreate, TaskPatch, User, ensure_role

from .command_handlers import (
    AddCommentHandler,
    ArchiveTaskHandler,
    BulkTaskActionHandler,
    CommandContext,
    CompleteTaskHandler,
    CreateTaskHandler,
    PatchTaskHandler,
    ReopenTaskHandler,
    ReorderTasksHandler,
    RequestAutomationRunHandler,
    RestoreTaskHandler,
    ToggleWatchHandler,
)


class TaskApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id
        self.ctx = CommandContext(db=db, user=user)

    def create_task(self, payload: TaskCreate) -> dict:
        return execute_command(
            self.db,
            command_name="Task.Create",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=CreateTaskHandler(self.ctx, payload),
        )

    def patch_task(self, task_id: str, payload: TaskPatch) -> dict:
        return execute_command(
            self.db,
            command_name="Task.Patch",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=PatchTaskHandler(self.ctx, task_id, payload),
        )

    def complete_task(self, task_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Task.Complete",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=CompleteTaskHandler(self.ctx, task_id),
        )

    def reopen_task(self, task_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Task.Reopen",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=ReopenTaskHandler(self.ctx, task_id),
        )

    def archive_task(self, task_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Task.Archive",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=ArchiveTaskHandler(self.ctx, task_id),
        )

    def restore_task(self, task_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Task.Restore",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=RestoreTaskHandler(self.ctx, task_id),
        )

    def bulk_action(self, payload: BulkAction) -> dict:
        updated = 0
        per_task_handler = BulkTaskActionHandler(self.ctx, payload)
        for task_id in payload.task_ids:
            if execute_command(
                self.db,
                command_name=f"Task.Bulk.{payload.action}",
                user_id=self.user.id,
                command_id=f"{self.command_id}:{task_id}" if self.command_id else None,
                handler=lambda task_id=task_id: per_task_handler(task_id),
            ):
                updated += 1
        return {"updated": updated}

    def reorder_tasks(self, workspace_id: str, project_id: str, payload: ReorderPayload) -> dict:
        ensure_role(self.db, workspace_id, self.user.id, {"Owner", "Admin", "Member"})
        handler = ReorderTasksHandler(self.ctx, workspace_id, project_id, payload)
        for idx, task_id in enumerate(payload.ordered_ids):
            execute_command(
                self.db,
                command_name="Task.Reorder",
                user_id=self.user.id,
                command_id=f"{self.command_id}:{task_id}" if self.command_id else None,
                handler=lambda task_id=task_id, idx=idx: handler(task_id, idx + 1),
            )
        return {"ok": True}

    def add_comment(self, task_id: str, payload: CommentCreate) -> dict:
        return execute_command(
            self.db,
            command_name="Task.CommentAdd",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=AddCommentHandler(self.ctx, task_id, payload),
        )

    def toggle_watch(self, task_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Task.ToggleWatch",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=ToggleWatchHandler(self.ctx, task_id),
        )

    def request_automation_run(self, task_id: str, payload: TaskAutomationRun) -> dict:
        return execute_command(
            self.db,
            command_name="Task.Automation.RequestRun",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=RequestAutomationRunHandler(self.ctx, task_id, payload.instruction),
        )
