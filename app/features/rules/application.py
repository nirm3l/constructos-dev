from __future__ import annotations

from sqlalchemy.orm import Session

from shared.commanding import execute_command
from shared.core import ProjectRuleCreate, ProjectRulePatch, User

from .command_handlers import CommandContext, CreateProjectRuleHandler, DeleteProjectRuleHandler, PatchProjectRuleHandler


class ProjectRuleApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id
        self.ctx = CommandContext(db=db, user=user)

    def create_project_rule(self, payload: ProjectRuleCreate) -> dict:
        return execute_command(
            self.db,
            command_name="ProjectRule.Create",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=CreateProjectRuleHandler(self.ctx, payload),
        )

    def patch_project_rule(self, rule_id: str, payload: ProjectRulePatch) -> dict:
        return execute_command(
            self.db,
            command_name="ProjectRule.Patch",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=PatchProjectRuleHandler(self.ctx, rule_id, payload),
        )

    def delete_project_rule(self, rule_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="ProjectRule.Delete",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=DeleteProjectRuleHandler(self.ctx, rule_id),
        )
