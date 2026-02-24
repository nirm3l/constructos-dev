from __future__ import annotations

from sqlalchemy.orm import Session

from shared.commanding import execute_command
from shared.core import User

from .command_handlers import (
    CommandContext,
    MarkAllNotificationsReadHandler,
    MarkNotificationReadHandler,
)


class NotificationApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id
        self.ctx = CommandContext(db=db, user=user)

    def mark_read(self, notification_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Notification.MarkRead",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=MarkNotificationReadHandler(self.ctx, notification_id),
        )

    def mark_all_read(self) -> dict:
        return execute_command(
            self.db,
            command_name="Notification.MarkAllRead",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=MarkAllNotificationsReadHandler(self.ctx),
        )
