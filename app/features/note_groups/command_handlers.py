from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared.core import (
    AggregateEventRepository,
    NoteGroup,
    NoteGroupCreate,
    NoteGroupPatch,
    Project,
    ReorderPayload,
    User,
    allocate_id,
    coerce_originator_id,
    ensure_project_access,
    ensure_role,
    load_note_group_command_state,
    load_note_group_view,
)

from .domain import NoteGroupAggregate


def _normalize_group_name(value: str) -> str:
    return " ".join(str(value or "").split())


def _group_name_key(value: str) -> str:
    return _normalize_group_name(value).casefold()


def _require_project_scope(db: Session, *, workspace_id: str, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Project does not belong to workspace")
    return project


def _find_group_by_name(db: Session, *, workspace_id: str, project_id: str, name: str) -> NoteGroup | None:
    key = _group_name_key(name)
    rows = db.execute(
        select(NoteGroup).where(
            NoteGroup.workspace_id == workspace_id,
            NoteGroup.project_id == project_id,
        )
    ).scalars().all()
    for row in rows:
        if _group_name_key(row.name) == key:
            return row
    return None


def _ensure_unique_group_name(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    name: str,
    exclude_group_id: str | None = None,
) -> None:
    key = _group_name_key(name)
    rows = db.execute(
        select(NoteGroup).where(
            NoteGroup.workspace_id == workspace_id,
            NoteGroup.project_id == project_id,
            NoteGroup.is_deleted == False,
        )
    ).scalars().all()
    for row in rows:
        if exclude_group_id and row.id == exclude_group_id:
            continue
        if _group_name_key(row.name) == key:
            raise HTTPException(status_code=409, detail="Note group name already exists in this project")


def require_note_group_command_state(db: Session, user: User, group_id: str, *, allowed: set[str]) -> tuple[str, str]:
    state = load_note_group_command_state(db, group_id)
    if not state or state.is_deleted:
        raise HTTPException(status_code=404, detail="Note group not found")
    ensure_project_access(db, state.workspace_id, state.project_id, user.id, allowed)
    return state.workspace_id, state.project_id


@dataclass(frozen=True, slots=True)
class CommandContext:
    db: Session
    user: User


@dataclass(frozen=True, slots=True)
class CreateNoteGroupHandler:
    ctx: CommandContext
    payload: NoteGroupCreate

    def __call__(self) -> dict:
        ensure_role(self.ctx.db, self.payload.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member"})
        _require_project_scope(self.ctx.db, workspace_id=self.payload.workspace_id, project_id=self.payload.project_id)
        ensure_project_access(
            self.ctx.db,
            self.payload.workspace_id,
            self.payload.project_id,
            self.ctx.user.id,
            {"Owner", "Admin", "Member"},
        )
        name = _normalize_group_name(self.payload.name)
        if not name:
            raise HTTPException(status_code=422, detail="name cannot be empty")

        existing = _find_group_by_name(
            self.ctx.db,
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            name=name,
        )
        if existing and not existing.is_deleted:
            view = load_note_group_view(self.ctx.db, existing.id)
            if view is None:
                raise HTTPException(status_code=404, detail="Note group not found")
            return view
        if existing and existing.is_deleted:
            raise HTTPException(status_code=409, detail="Note group with this name already exists in deleted state")

        max_order = self.ctx.db.execute(
            select(func.max(NoteGroup.order_index)).where(
                NoteGroup.workspace_id == self.payload.workspace_id,
                NoteGroup.project_id == self.payload.project_id,
                NoteGroup.is_deleted == False,
            )
        ).scalar() or 0

        group_id = allocate_id(self.ctx.db)
        aggregate = NoteGroupAggregate(
            id=coerce_originator_id(group_id),
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            name=name,
            description=self.payload.description or "",
            color=(self.payload.color.strip() if isinstance(self.payload.color, str) else self.payload.color) or None,
            order_index=max_order + 1,
        )
        AggregateEventRepository(self.ctx.db).persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": self.payload.workspace_id,
                "project_id": self.payload.project_id,
                "note_group_id": group_id,
            },
            expected_version=0,
        )
        self.ctx.db.commit()
        view = load_note_group_view(self.ctx.db, group_id)
        if view is None:
            raise HTTPException(status_code=404, detail="Note group not found after create")
        return view


@dataclass(frozen=True, slots=True)
class PatchNoteGroupHandler:
    ctx: CommandContext
    group_id: str
    payload: NoteGroupPatch

    def __call__(self) -> dict:
        workspace_id, project_id = require_note_group_command_state(
            self.ctx.db,
            self.ctx.user,
            self.group_id,
            allowed={"Owner", "Admin", "Member"},
        )
        data = self.payload.model_dump(exclude_unset=True)
        event_payload: dict[str, str | None] = {}

        if "name" in data:
            raw_name = data.get("name")
            if raw_name is None:
                raise HTTPException(status_code=422, detail="name cannot be null")
            normalized_name = _normalize_group_name(str(raw_name))
            if not normalized_name:
                raise HTTPException(status_code=422, detail="name cannot be empty")
            _ensure_unique_group_name(
                self.ctx.db,
                workspace_id=workspace_id,
                project_id=project_id,
                name=normalized_name,
                exclude_group_id=self.group_id,
            )
            event_payload["name"] = normalized_name

        if "description" in data and data["description"] is not None:
            event_payload["description"] = str(data["description"])

        if "color" in data:
            color = data.get("color")
            if isinstance(color, str):
                color = color.strip() or None
            event_payload["color"] = color

        if not event_payload:
            view = load_note_group_view(self.ctx.db, self.group_id)
            if view is None:
                raise HTTPException(status_code=404, detail="Note group not found")
            return view

        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="NoteGroup",
            aggregate_id=self.group_id,
            aggregate_cls=NoteGroupAggregate,
        )
        if bool(getattr(aggregate, "is_deleted", False)):
            raise HTTPException(status_code=404, detail="Note group not found")
        aggregate.update(changes=event_payload)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "note_group_id": self.group_id,
            },
        )
        self.ctx.db.commit()
        view = load_note_group_view(self.ctx.db, self.group_id)
        if view is None:
            raise HTTPException(status_code=404, detail="Note group not found")
        return view


@dataclass(frozen=True, slots=True)
class DeleteNoteGroupHandler:
    ctx: CommandContext
    group_id: str

    def __call__(self) -> dict:
        workspace_id, project_id = require_note_group_command_state(
            self.ctx.db,
            self.ctx.user,
            self.group_id,
            allowed={"Owner", "Admin", "Member"},
        )
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="NoteGroup",
            aggregate_id=self.group_id,
            aggregate_cls=NoteGroupAggregate,
        )
        if bool(getattr(aggregate, "is_deleted", False)):
            return {"ok": True}
        aggregate.delete()
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "note_group_id": self.group_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class ReorderNoteGroupsHandler:
    ctx: CommandContext
    workspace_id: str
    project_id: str
    payload: ReorderPayload

    def __call__(self, group_id: str, order_index: int) -> bool:
        _ = self.payload
        state = load_note_group_command_state(self.ctx.db, group_id)
        if not state or state.is_deleted or state.workspace_id != self.workspace_id or state.project_id != self.project_id:
            return False

        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="NoteGroup",
            aggregate_id=group_id,
            aggregate_cls=NoteGroupAggregate,
        )
        if bool(getattr(aggregate, "is_deleted", False)):
            return False
        aggregate.reorder(order_index=order_index)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": self.workspace_id,
                "project_id": self.project_id,
                "note_group_id": group_id,
            },
        )
        self.ctx.db.commit()
        return True
