from __future__ import annotations

from sqlalchemy.orm import Session

from shared.commanding import execute_command
from shared.core import ProjectCreate, ProjectPatch, User

from .command_handlers import (
    AddProjectMemberHandler,
    CommandContext,
    CreateProjectHandler,
    DeleteProjectHandler,
    PatchProjectHandler,
    RemoveProjectMemberHandler,
)


class ProjectApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id
        self.ctx = CommandContext(db=db, user=user)

    def create_project(self, payload: ProjectCreate) -> dict:
        return execute_command(
            self.db,
            command_name="Project.Create",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=CreateProjectHandler(self.ctx, payload),
        )

    def delete_project(self, project_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Project.Delete",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=DeleteProjectHandler(self.ctx, project_id),
        )

    def patch_project(self, project_id: str, payload: ProjectPatch) -> dict:
        return execute_command(
            self.db,
            command_name="Project.Patch",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=PatchProjectHandler(self.ctx, project_id, payload),
        )

    def add_project_member(self, project_id: str, user_id: str, role: str = "Contributor") -> dict:
        return execute_command(
            self.db,
            command_name="Project.MemberAdd",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=AddProjectMemberHandler(self.ctx, project_id, user_id, role=role),
        )

    def remove_project_member(self, project_id: str, user_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Project.MemberRemove",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=RemoveProjectMemberHandler(self.ctx, project_id, user_id),
        )
