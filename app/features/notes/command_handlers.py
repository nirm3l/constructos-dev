from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from shared.core import (
    Note,
    NoteCreate,
    NotePatch,
    User,
    append_event,
    allocate_id,
    ensure_role,
    load_note_command_state,
    load_note_view,
)

from .domain import (
    EVENT_ARCHIVED,
    EVENT_CREATED,
    EVENT_DELETED,
    EVENT_PINNED,
    EVENT_RESTORED,
    EVENT_UNPINNED,
    EVENT_UPDATED,
)


def require_note_command_state(db: Session, user: User, note_id: str, *, allowed: set[str]) -> tuple[str, str | None, str | None, bool, bool]:
    state = load_note_command_state(db, note_id)
    if not state or state.is_deleted:
        raise HTTPException(status_code=404, detail="Note not found")
    ensure_role(db, state.workspace_id, user.id, allowed)
    return state.workspace_id, state.project_id, state.task_id, bool(state.archived), bool(state.pinned)


@dataclass(frozen=True, slots=True)
class CommandContext:
    db: Session
    user: User


@dataclass(frozen=True, slots=True)
class CreateNoteHandler:
    ctx: CommandContext
    payload: NoteCreate

    def __call__(self) -> dict:
        ensure_role(self.ctx.db, self.payload.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member"})
        nid = allocate_id(self.ctx.db)
        append_event(
            self.ctx.db,
            aggregate_type="Note",
            aggregate_id=nid,
            event_type=EVENT_CREATED,
            payload={
                "workspace_id": self.payload.workspace_id,
                "project_id": self.payload.project_id,
                "task_id": self.payload.task_id,
                "title": self.payload.title.strip(),
                "body": self.payload.body or "",
                "tags": list(self.payload.tags or []),
                "pinned": bool(self.payload.pinned),
                "archived": False,
                "is_deleted": False,
                "created_by": self.ctx.user.id,
                "updated_by": self.ctx.user.id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": self.payload.workspace_id,
                "project_id": self.payload.project_id,
                "task_id": self.payload.task_id,
                "note_id": nid,
            },
            expected_version=0,
        )
        self.ctx.db.commit()
        view = load_note_view(self.ctx.db, nid)
        if view is None:
            raise HTTPException(status_code=404, detail="Note not found after create")
        return view


@dataclass(frozen=True, slots=True)
class PatchNoteHandler:
    ctx: CommandContext
    note_id: str
    payload: NotePatch

    def __call__(self) -> dict:
        workspace_id, project_id, task_id, _, _ = require_note_command_state(
            self.ctx.db, self.ctx.user, self.note_id, allowed={"Owner", "Admin", "Member"}
        )
        data = self.payload.model_dump(exclude_unset=True)
        if "title" in data and data["title"] is not None:
            data["title"] = str(data["title"]).strip()
            if not data["title"]:
                raise HTTPException(status_code=422, detail="title cannot be empty")
        if "tags" in data and data["tags"] is not None:
            data["tags"] = [str(t).strip() for t in data["tags"] if str(t).strip()]
        # Keep updated_by in event payload for easy projection/audit.
        data["updated_by"] = self.ctx.user.id
        append_event(
            self.ctx.db,
            aggregate_type="Note",
            aggregate_id=self.note_id,
            event_type=EVENT_UPDATED,
            payload=data,
            metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": task_id,
                "note_id": self.note_id,
            },
        )
        self.ctx.db.commit()
        view = load_note_view(self.ctx.db, self.note_id)
        if view is None:
            raise HTTPException(status_code=404, detail="Note not found")
        return view


@dataclass(frozen=True, slots=True)
class ArchiveNoteHandler:
    ctx: CommandContext
    note_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, task_id, archived, _ = require_note_command_state(
            self.ctx.db, self.ctx.user, self.note_id, allowed={"Owner", "Admin", "Member"}
        )
        if archived:
            raise HTTPException(status_code=409, detail="Note already archived")
        append_event(
            self.ctx.db,
            aggregate_type="Note",
            aggregate_id=self.note_id,
            event_type=EVENT_ARCHIVED,
            payload={"updated_by": self.ctx.user.id},
            metadata={"actor_id": self.ctx.user.id, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id, "note_id": self.note_id},
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class RestoreNoteHandler:
    ctx: CommandContext
    note_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, task_id, archived, _ = require_note_command_state(
            self.ctx.db, self.ctx.user, self.note_id, allowed={"Owner", "Admin", "Member"}
        )
        if not archived:
            raise HTTPException(status_code=409, detail="Note is not archived")
        append_event(
            self.ctx.db,
            aggregate_type="Note",
            aggregate_id=self.note_id,
            event_type=EVENT_RESTORED,
            payload={"updated_by": self.ctx.user.id},
            metadata={"actor_id": self.ctx.user.id, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id, "note_id": self.note_id},
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class PinNoteHandler:
    ctx: CommandContext
    note_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, task_id, _, pinned = require_note_command_state(
            self.ctx.db, self.ctx.user, self.note_id, allowed={"Owner", "Admin", "Member"}
        )
        if pinned:
            raise HTTPException(status_code=409, detail="Note already pinned")
        append_event(
            self.ctx.db,
            aggregate_type="Note",
            aggregate_id=self.note_id,
            event_type=EVENT_PINNED,
            payload={"updated_by": self.ctx.user.id},
            metadata={"actor_id": self.ctx.user.id, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id, "note_id": self.note_id},
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class UnpinNoteHandler:
    ctx: CommandContext
    note_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, task_id, _, pinned = require_note_command_state(
            self.ctx.db, self.ctx.user, self.note_id, allowed={"Owner", "Admin", "Member"}
        )
        if not pinned:
            raise HTTPException(status_code=409, detail="Note is not pinned")
        append_event(
            self.ctx.db,
            aggregate_type="Note",
            aggregate_id=self.note_id,
            event_type=EVENT_UNPINNED,
            payload={"updated_by": self.ctx.user.id},
            metadata={"actor_id": self.ctx.user.id, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id, "note_id": self.note_id},
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class DeleteNoteHandler:
    ctx: CommandContext
    note_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, task_id, _, _ = require_note_command_state(
            self.ctx.db, self.ctx.user, self.note_id, allowed={"Owner", "Admin", "Member"}
        )
        append_event(
            self.ctx.db,
            aggregate_type="Note",
            aggregate_id=self.note_id,
            event_type=EVENT_DELETED,
            payload={"updated_by": self.ctx.user.id},
            metadata={"actor_id": self.ctx.user.id, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id, "note_id": self.note_id},
        )
        self.ctx.db.commit()
        return {"ok": True}


def _debug_dump_notes(db: Session) -> str:  # pragma: no cover
    notes = db.query(Note).order_by(Note.updated_at.desc()).limit(10).all()
    return json.dumps([{"id": n.id, "title": n.title, "archived": n.archived, "pinned": n.pinned} for n in notes])

