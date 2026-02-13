from __future__ import annotations

from sqlalchemy.orm import Session

from shared.commanding import execute_command
from shared.core import User, UserPreferencesPatch

from .command_handlers import CommandContext, PatchUserPreferencesHandler


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
