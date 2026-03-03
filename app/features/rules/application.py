from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.commanding import execute_command
from shared.core import ProjectRuleCreate, ProjectRulePatch, User
from shared.models import ProjectRule

from .command_handlers import CommandContext, CreateProjectRuleHandler, DeleteProjectRuleHandler, PatchProjectRuleHandler

_GATE_POLICY_RULE_TITLES = ("gate policy", "delivery gates", "workflow gates")


class ProjectRuleApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id
        self.ctx = CommandContext(db=db, user=user)

    def _find_existing_gate_policy_rule_id(
        self,
        *,
        workspace_id: str,
        project_id: str,
    ) -> str | None:
        rows = self.db.execute(
            select(ProjectRule).where(
                ProjectRule.workspace_id == workspace_id,
                ProjectRule.project_id == project_id,
                ProjectRule.is_deleted == False,  # noqa: E712
            )
        ).scalars()
        for row in rows:
            title = str(getattr(row, "title", "") or "").strip().lower()
            if any(marker in title for marker in _GATE_POLICY_RULE_TITLES):
                return str(row.id)
        return None

    def create_project_rule(self, payload: ProjectRuleCreate) -> dict:
        normalized_title = str(payload.title or "").strip().lower()
        if any(marker in normalized_title for marker in _GATE_POLICY_RULE_TITLES):
            existing_rule_id = self._find_existing_gate_policy_rule_id(
                workspace_id=payload.workspace_id,
                project_id=payload.project_id,
            )
            if existing_rule_id:
                return self.patch_project_rule(
                    existing_rule_id,
                    ProjectRulePatch(
                        title=payload.title,
                        body=payload.body,
                    ),
                )
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
