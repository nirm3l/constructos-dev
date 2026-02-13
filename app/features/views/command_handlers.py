from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from shared.core import SavedViewCreate, User, append_event, allocate_id, ensure_role, load_saved_view
from .domain import EVENT_CREATED as SAVED_VIEW_EVENT_CREATED


@dataclass(frozen=True, slots=True)
class CommandContext:
    db: Session
    user: User


@dataclass(frozen=True, slots=True)
class CreateSavedViewHandler:
    ctx: CommandContext
    payload: SavedViewCreate

    def __call__(self) -> dict:
        role_required = {"Owner", "Admin", "Member"} if self.payload.shared else {"Owner", "Admin", "Member", "Guest"}
        ensure_role(self.ctx.db, self.payload.workspace_id, self.ctx.user.id, role_required)
        sid = allocate_id(self.ctx.db)
        append_event(
            self.ctx.db,
            aggregate_type="SavedView",
            aggregate_id=sid,
            event_type=SAVED_VIEW_EVENT_CREATED,
            payload={
                "workspace_id": self.payload.workspace_id,
                "user_id": None if self.payload.shared else self.ctx.user.id,
                "name": self.payload.name,
                "shared": self.payload.shared,
                "filters": self.payload.filters,
            },
            metadata={"actor_id": self.ctx.user.id, "workspace_id": self.payload.workspace_id},
            expected_version=0,
        )
        self.ctx.db.commit()
        sv = load_saved_view(self.ctx.db, sid)
        if sv is None:
            return {"id": sid, "name": self.payload.name, "shared": self.payload.shared, "filters": self.payload.filters}
        return sv
