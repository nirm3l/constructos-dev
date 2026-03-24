from __future__ import annotations

from sqlalchemy.orm import Session

from shared.commanding import execute_command
from shared.core import ReorderPayload, TaskGroupCreate, TaskGroupPatch, User, ensure_project_access

from .command_handlers import (
    CommandContext,
    CreateTaskGroupHandler,
    DeleteTaskGroupHandler,
    PatchTaskGroupHandler,
    ReorderTaskGroupsHandler,
)


class TaskGroupApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id
        self.ctx = CommandContext(db=db, user=user)

    def create_task_group(self, payload: TaskGroupCreate) -> dict:
        return execute_command(
            self.db,
            command_name="TaskGroup.Create",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=CreateTaskGroupHandler(self.ctx, payload),
        )

    def patch_task_group(self, group_id: str, payload: TaskGroupPatch) -> dict:
        return execute_command(
            self.db,
            command_name="TaskGroup.Patch",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=PatchTaskGroupHandler(self.ctx, group_id, payload),
        )

    def delete_task_group(self, group_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="TaskGroup.Delete",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=DeleteTaskGroupHandler(self.ctx, group_id),
        )

    def reorder_task_groups(self, workspace_id: str, project_id: str, payload: ReorderPayload) -> dict:
        ensure_project_access(self.db, workspace_id, project_id, self.user.id, {"Owner", "Admin", "Member"})
        return execute_command(
            self.db,
            command_name="TaskGroup.Reorder",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=ReorderTaskGroupsHandler(self.ctx, workspace_id, project_id, payload),
        )
