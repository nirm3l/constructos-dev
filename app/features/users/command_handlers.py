from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.core import User, UserPreferencesPatch, WorkspaceMember, append_event
from shared.settings import BOOTSTRAP_WORKSPACE_ID
from .domain import EVENT_PREFERENCES_UPDATED as USER_EVENT_PREFERENCES_UPDATED


@dataclass(frozen=True, slots=True)
class CommandContext:
    db: Session
    user: User


@dataclass(frozen=True, slots=True)
class PatchUserPreferencesHandler:
    ctx: CommandContext
    payload: UserPreferencesPatch

    def __call__(self) -> dict:
        data = self.payload.model_dump(exclude_unset=True)
        append_event(
            self.ctx.db,
            aggregate_type="User",
            aggregate_id=self.ctx.user.id,
            event_type=USER_EVENT_PREFERENCES_UPDATED,
            payload=data,
            metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": self.ctx.db.execute(select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == self.ctx.user.id)).scalar() or BOOTSTRAP_WORKSPACE_ID,
            },
        )
        self.ctx.db.commit()
        return {
            "id": self.ctx.user.id,
            "theme": data.get("theme", self.ctx.user.theme),
            "timezone": data.get("timezone", self.ctx.user.timezone),
            "notifications_enabled": bool(data.get("notifications_enabled", self.ctx.user.notifications_enabled)),
        }
