from __future__ import annotations

from sqlalchemy.orm import Session

from shared.commanding import execute_command
from shared.core import SavedViewCreate, User

from .command_handlers import CommandContext, CreateSavedViewHandler


class SavedViewApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id
        self.ctx = CommandContext(db=db, user=user)

    def create_saved_view(self, payload: SavedViewCreate) -> dict:
        return execute_command(
            self.db,
            command_name="SavedView.Create",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=CreateSavedViewHandler(self.ctx, payload),
        )
