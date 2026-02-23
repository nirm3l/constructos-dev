from __future__ import annotations

from sqlalchemy.orm import Session

from shared.commanding import execute_command
from shared.models import User

from .command_handlers import (
    AppendAssistantMessageHandler,
    AppendAssistantMessagePayload,
    AppendUserMessageHandler,
    AppendUserMessagePayload,
    ArchiveSessionHandler,
    ArchiveSessionPayload,
    CommandContext,
    LinkMessageResourceHandler,
    LinkMessageResourcePayload,
    UpdateSessionContextHandler,
    UpdateSessionContextPayload,
)


class ChatApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id
        self.ctx = CommandContext(db=db, user=user)

    def append_user_message(self, payload: AppendUserMessagePayload) -> dict:
        return execute_command(
            self.db,
            command_name="ChatSession.AppendUserMessage",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=AppendUserMessageHandler(self.ctx, payload),
        )

    def append_assistant_message(self, payload: AppendAssistantMessagePayload) -> dict:
        return execute_command(
            self.db,
            command_name="ChatSession.AppendAssistantMessage",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=AppendAssistantMessageHandler(self.ctx, payload),
        )

    def update_session_context(self, payload: UpdateSessionContextPayload) -> dict:
        return execute_command(
            self.db,
            command_name="ChatSession.UpdateContext",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=UpdateSessionContextHandler(self.ctx, payload),
        )

    def archive_session(self, payload: ArchiveSessionPayload) -> dict:
        return execute_command(
            self.db,
            command_name="ChatSession.Archive",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=ArchiveSessionHandler(self.ctx, payload),
        )

    def link_message_resource(self, payload: LinkMessageResourcePayload) -> dict:
        return execute_command(
            self.db,
            command_name="ChatSession.LinkMessageResource",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=LinkMessageResourceHandler(self.ctx, payload),
        )
