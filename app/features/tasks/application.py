from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from shared.commanding import execute_command
from shared.core import BulkAction, CommentCreate, ReorderPayload, TaskAutomationRun, TaskCreate, TaskPatch, User, ensure_project_access

from .command_handlers import (
    AddCommentHandler,
    ArchiveTaskHandler,
    BulkTaskActionHandler,
    CommandContext,
    CompleteTaskHandler,
    CreateTaskHandler,
    DeleteCommentHandler,
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
                command_id=_derive_child_command_id(self.command_id, task_id),
                handler=lambda task_id=task_id: per_task_handler(task_id),
            ):
                updated += 1
        return {"updated": updated}

    def reorder_tasks(self, workspace_id: str, project_id: str, payload: ReorderPayload) -> dict:
        ensure_project_access(self.db, workspace_id, project_id, self.user.id, {"Owner", "Admin", "Member"})
        handler = ReorderTasksHandler(self.ctx, workspace_id, project_id, payload)
        for idx, task_id in enumerate(payload.ordered_ids):
            execute_command(
                self.db,
                command_name="Task.Reorder",
                user_id=self.user.id,
                command_id=_derive_child_command_id(self.command_id, task_id),
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

    def delete_comment(self, task_id: str, comment_id: int) -> dict:
        return execute_command(
            self.db,
            command_name="Task.CommentDelete",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=DeleteCommentHandler(self.ctx, task_id, comment_id),
        )

    def toggle_watch(self, task_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Task.ToggleWatch",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=ToggleWatchHandler(self.ctx, task_id),
        )

    def request_automation_run(
        self,
        task_id: str,
        payload: TaskAutomationRun,
        *,
        wake_runner: bool = True,
    ) -> dict:
        return execute_command(
            self.db,
            command_name="Task.Automation.RequestRun",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=RequestAutomationRunHandler(
                self.ctx,
                task_id,
                payload.instruction,
                payload.source,
                payload.execution_intent,
                payload.execution_kickoff_intent,
                payload.project_creation_intent,
                payload.workflow_scope,
                payload.execution_mode,
                payload.task_completion_requested,
                payload.classifier_reason,
                wake_runner=wake_runner,
            ),
        )


def _derive_child_command_id(command_id: str | None, child_key: str) -> str | None:
    if not command_id:
        return None
    base = str(command_id or "").strip()
    if not base:
        return None
    suffix = str(child_key or "").strip()
    if not suffix:
        return base
    candidate = f"{base}:{suffix}"
    if len(candidate) <= 64:
        return candidate
    suffix_digest = hashlib.sha1(suffix.encode("utf-8")).hexdigest()[:12]
    keep = max(1, 64 - len(suffix_digest) - 1)
    return f"{base[:keep]}:{suffix_digest}"
