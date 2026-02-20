from __future__ import annotations

from sqlalchemy.orm import Session

from shared.commanding import execute_command
from shared.core import User, UserPreferencesPatch

from .command_handlers import (
    ChangePasswordHandler,
    CommandContext,
    CreateWorkspaceUserHandler,
    DeactivateWorkspaceUserHandler,
    PatchUserPreferencesHandler,
    ResetWorkspaceUserPasswordHandler,
    UpdateWorkspaceUserRoleHandler,
)


class UserApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id
        self.ctx = CommandContext(db=db, user=user)

    def patch_preferences(self, payload: UserPreferencesPatch) -> dict:
        return execute_command(
            self.db,
            command_name="User.PreferencesPatch",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=PatchUserPreferencesHandler(self.ctx, payload),
        )

    def change_password(self, *, current_password: str, new_password: str, keep_session_hash: str | None) -> dict:
        return execute_command(
            self.db,
            command_name="User.PasswordChange",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=ChangePasswordHandler(
                self.ctx,
                current_password=current_password,
                new_password=new_password,
                keep_session_hash=keep_session_hash,
            ),
        )

    def create_workspace_user(
        self,
        *,
        workspace_id: str,
        username: str,
        full_name: str | None,
        role: str,
    ) -> dict:
        return execute_command(
            self.db,
            command_name="User.WorkspaceCreate",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=CreateWorkspaceUserHandler(
                self.ctx,
                workspace_id=workspace_id,
                username=username,
                full_name=full_name,
                role=role,
            ),
        )

    def reset_workspace_user_password(self, *, workspace_id: str, target_user_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="User.WorkspaceResetPassword",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=ResetWorkspaceUserPasswordHandler(
                self.ctx,
                workspace_id=workspace_id,
                target_user_id=target_user_id,
            ),
        )

    def update_workspace_user_role(self, *, workspace_id: str, target_user_id: str, role: str) -> dict:
        return execute_command(
            self.db,
            command_name="User.WorkspaceRoleSet",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=UpdateWorkspaceUserRoleHandler(
                self.ctx,
                workspace_id=workspace_id,
                target_user_id=target_user_id,
                role=role,
            ),
        )

    def deactivate_workspace_user(self, *, workspace_id: str, target_user_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="User.WorkspaceDeactivate",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=DeactivateWorkspaceUserHandler(
                self.ctx,
                workspace_id=workspace_id,
                target_user_id=target_user_id,
            ),
        )
