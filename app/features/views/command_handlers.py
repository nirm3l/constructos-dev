from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.core import (
    AggregateEventRepository,
    Project,
    SavedViewCreate,
    User,
    allocate_id,
    ensure_project_access,
    ensure_role,
    load_saved_view,
)
from .domain import SavedViewAggregate


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
        ensure_project_access(
            self.ctx.db,
            self.payload.workspace_id,
            self.payload.project_id,
            self.ctx.user.id,
            role_required,
        )
        project = self.ctx.db.get(Project, self.payload.project_id)
        if not project or project.is_deleted:
            raise HTTPException(status_code=404, detail="Project not found")
        if project.workspace_id != self.payload.workspace_id:
            raise HTTPException(status_code=400, detail="Project does not belong to workspace")
        sid = allocate_id(self.ctx.db)
        aggregate = SavedViewAggregate(sid, version=0)
        aggregate.create(
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            user_id=None if self.payload.shared else self.ctx.user.id,
            name=self.payload.name,
            shared=self.payload.shared,
            filters=self.payload.filters,
        )
        AggregateEventRepository(self.ctx.db).persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": self.payload.workspace_id,
                "project_id": self.payload.project_id,
            },
            expected_version=0,
        )
        try:
            self.ctx.db.commit()
        except IntegrityError as exc:
            self.ctx.db.rollback()
            message = str(exc).lower()
            if "unique constraint failed" not in message or "saved_views.id" not in message:
                raise
        sv = load_saved_view(self.ctx.db, sid)
        if sv is None:
            return {"id": sid, "name": self.payload.name, "shared": self.payload.shared, "filters": self.payload.filters}
        return sv
