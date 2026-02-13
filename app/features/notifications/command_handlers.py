from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.core import Notification, User, WorkspaceMember, append_event
from shared.settings import BOOTSTRAP_WORKSPACE_ID
from .domain import EVENT_MARKED_READ as NOTIFICATION_EVENT_MARKED_READ


@dataclass(frozen=True, slots=True)
class CommandContext:
    db: Session
    user: User


@dataclass(frozen=True, slots=True)
class MarkNotificationReadHandler:
    ctx: CommandContext
    notification_id: str

    def __call__(self) -> dict:
        n = self.ctx.db.get(Notification, self.notification_id)
        if not n or n.user_id != self.ctx.user.id:
            raise HTTPException(status_code=404, detail="Notification not found")
        append_event(
            self.ctx.db,
            aggregate_type="Notification",
            aggregate_id=self.notification_id,
            event_type=NOTIFICATION_EVENT_MARKED_READ,
            payload={"notification_id": self.notification_id, "user_id": self.ctx.user.id},
            metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": self.ctx.db.execute(select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == self.ctx.user.id)).scalar() or BOOTSTRAP_WORKSPACE_ID,
            },
        )
        self.ctx.db.commit()
        return {"ok": True}
