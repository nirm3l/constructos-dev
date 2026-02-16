from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.core import (
    Note,
    NoteCreate,
    NotePatch,
    Project,
    Task,
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


def _normalize_tags(values: list[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        tag = str(raw).strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _normalize_external_refs(values: list[dict] | None) -> list[dict]:
    if not values:
        return []
    out: list[dict] = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "").strip()
        if not url:
            continue
        item = {"url": url}
        title = str(raw.get("title") or "").strip()
        source = str(raw.get("source") or "").strip()
        if title:
            item["title"] = title
        if source:
            item["source"] = source
        out.append(item)
    return out


def _normalize_attachment_refs(values: list[dict] | None) -> list[dict]:
    if not values:
        return []
    out: list[dict] = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        path = str(raw.get("path") or "").strip()
        if not path:
            continue
        item = {"path": path}
        name = str(raw.get("name") or "").strip()
        mime_type = str(raw.get("mime_type") or "").strip()
        size_bytes = raw.get("size_bytes")
        if name:
            item["name"] = name
        if mime_type:
            item["mime_type"] = mime_type
        if isinstance(size_bytes, int) and size_bytes >= 0:
            item["size_bytes"] = size_bytes
        out.append(item)
    return out


def _require_project_scope(db: Session, *, workspace_id: str, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Project does not belong to workspace")
    return project


def _require_task_scope(db: Session, *, workspace_id: str, project_id: str, task_id: str) -> Task:
    task = db.execute(select(Task).where(Task.id == task_id, Task.is_deleted == False)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Task does not belong to workspace")
    if task.project_id != project_id:
        raise HTTPException(status_code=400, detail="Task does not belong to project")
    return task


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
        _require_project_scope(self.ctx.db, workspace_id=self.payload.workspace_id, project_id=self.payload.project_id)
        if self.payload.task_id:
            _require_task_scope(
                self.ctx.db,
                workspace_id=self.payload.workspace_id,
                project_id=self.payload.project_id,
                task_id=self.payload.task_id,
            )
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
                "tags": _normalize_tags(self.payload.tags),
                "external_refs": _normalize_external_refs([r.model_dump() for r in self.payload.external_refs]),
                "attachment_refs": _normalize_attachment_refs([r.model_dump() for r in self.payload.attachment_refs]),
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
        effective_project_id = project_id
        if "project_id" in data:
            if not data["project_id"]:
                raise HTTPException(status_code=422, detail="project_id cannot be null")
            _require_project_scope(self.ctx.db, workspace_id=workspace_id, project_id=str(data["project_id"]))
            effective_project_id = str(data["project_id"])
        if "task_id" in data and data["task_id"]:
            if not effective_project_id:
                raise HTTPException(status_code=400, detail="project_id is required when task_id is set")
            _require_task_scope(self.ctx.db, workspace_id=workspace_id, project_id=effective_project_id or "", task_id=str(data["task_id"]))
        if "title" in data and data["title"] is not None:
            data["title"] = str(data["title"]).strip()
            if not data["title"]:
                raise HTTPException(status_code=422, detail="title cannot be empty")
        if "tags" in data and data["tags"] is not None:
            data["tags"] = _normalize_tags(data["tags"])
        if "external_refs" in data and data["external_refs"] is not None:
            data["external_refs"] = _normalize_external_refs(data["external_refs"])
        if "attachment_refs" in data and data["attachment_refs"] is not None:
            data["attachment_refs"] = _normalize_attachment_refs(data["attachment_refs"])
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
                "project_id": data.get("project_id", project_id),
                "task_id": data.get("task_id", task_id),
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
