from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from shared.core import (
    AggregateEventRepository,
    Note,
    NoteCreate,
    NotePatch,
    Project,
    User,
    coerce_originator_id,
    ensure_project_access,
    ensure_role,
    load_project_command_state,
    load_note_group_command_state,
    load_note_command_state,
    load_specification_command_state,
    load_task_command_state,
    load_note_view,
)

from .domain import (
    NoteAggregate,
)


def require_note_command_state(
    db: Session, user: User, note_id: str, *, allowed: set[str]
) -> tuple[str, str | None, str | None, str | None, bool, bool]:
    state = load_note_command_state(db, note_id)
    if not state or state.is_deleted:
        raise HTTPException(status_code=404, detail="Note not found")
    if state.project_id:
        ensure_project_access(db, state.workspace_id, state.project_id, user.id, allowed)
    else:
        ensure_role(db, state.workspace_id, user.id, allowed)
    return state.workspace_id, state.project_id, state.task_id, state.specification_id, bool(state.archived), bool(state.pinned)


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


def _normalize_note_title(value: str) -> str:
    return " ".join(str(value or "").split())


def _note_title_key(value: str) -> str:
    return _normalize_note_title(value).casefold()


def _note_aggregate_id(project_id: str, title: str, *, salt: int = 0) -> str:
    key = _note_title_key(title)
    seed = f"note:{project_id}:{key}" if salt <= 0 else f"note:{project_id}:{key}:{salt}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def _resolve_note_create_id(
    db: Session,
    *,
    project_id: str,
    title: str,
    force_new: bool = False,
    max_salt: int = 1024,
) -> tuple[str, bool]:
    if force_new:
        return str(uuid.uuid4()), False
    for salt in range(0, max_salt + 1):
        candidate_id = _note_aggregate_id(project_id, title, salt=salt)
        existing_note = db.get(Note, candidate_id)
        if existing_note and existing_note.is_deleted:
            continue
        if existing_note and not existing_note.is_deleted:
            return candidate_id, True
        existing_state = load_note_command_state(db, candidate_id)
        if existing_state and existing_state.is_deleted:
            continue
        if existing_state and not existing_state.is_deleted:
            return candidate_id, True
        return candidate_id, False
    raise HTTPException(status_code=409, detail="Unable to allocate note id for this title")


def _require_project_scope(db: Session, *, workspace_id: str, project_id: str) -> Project:
    project = load_project_command_state(db, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Project does not belong to workspace")
    return project


def _require_task_scope(db: Session, *, workspace_id: str, project_id: str, task_id: str) -> None:
    task = load_task_command_state(db, task_id)
    if not task or task.is_deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Task does not belong to workspace")
    if task.project_id != project_id:
        raise HTTPException(status_code=400, detail="Task does not belong to project")


def _require_note_group_scope(db: Session, *, workspace_id: str, project_id: str, note_group_id: str) -> None:
    note_group = load_note_group_command_state(db, note_group_id)
    if not note_group or note_group.is_deleted:
        raise HTTPException(status_code=404, detail="Note group not found")
    if note_group.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Note group does not belong to workspace")
    if note_group.project_id != project_id:
        raise HTTPException(status_code=400, detail="Note group does not belong to project")


def _require_specification_scope(db: Session, *, workspace_id: str, project_id: str, specification_id: str) -> None:
    specification = load_specification_command_state(db, specification_id)
    if not specification or specification.is_deleted:
        raise HTTPException(status_code=404, detail="Specification not found")
    if specification.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Specification does not belong to workspace")
    if specification.project_id != project_id:
        raise HTTPException(status_code=400, detail="Specification does not belong to project")
    if specification.archived:
        raise HTTPException(status_code=409, detail="Specification is archived")


def _note_view_from_aggregate(*, note_id: str, aggregate: NoteAggregate) -> dict:
    return {
        "id": note_id,
        "workspace_id": getattr(aggregate, "workspace_id", None),
        "project_id": getattr(aggregate, "project_id", None),
        "note_group_id": getattr(aggregate, "note_group_id", None),
        "task_id": getattr(aggregate, "task_id", None),
        "specification_id": getattr(aggregate, "specification_id", None),
        "title": getattr(aggregate, "title", "") or "",
        "body": getattr(aggregate, "body", "") or "",
        "tags": getattr(aggregate, "tags", []) or [],
        "external_refs": getattr(aggregate, "external_refs", []) or [],
        "attachment_refs": getattr(aggregate, "attachment_refs", []) or [],
        "pinned": bool(getattr(aggregate, "pinned", False)),
        "archived": bool(getattr(aggregate, "archived", False)),
        "created_by": getattr(aggregate, "created_by", "") or "",
        "updated_by": getattr(aggregate, "updated_by", "") or "",
        "created_at": None,
        "updated_at": None,
    }


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
        ensure_project_access(
            self.ctx.db,
            self.payload.workspace_id,
            self.payload.project_id,
            self.ctx.user.id,
            {"Owner", "Admin", "Member"},
        )
        title = _normalize_note_title(self.payload.title)
        if not title:
            raise HTTPException(status_code=422, detail="title cannot be empty")
        nid, exists_active = _resolve_note_create_id(
            self.ctx.db,
            project_id=self.payload.project_id,
            title=title,
            force_new=bool(self.payload.force_new),
        )
        if exists_active:
            view = load_note_view(self.ctx.db, nid)
            if view is None:
                raise HTTPException(status_code=409, detail="Note already exists; retry")
            return view

        if self.payload.specification_id:
            _require_specification_scope(
                self.ctx.db,
                workspace_id=self.payload.workspace_id,
                project_id=self.payload.project_id,
                specification_id=self.payload.specification_id,
            )
        if self.payload.task_id:
            _require_task_scope(
                self.ctx.db,
                workspace_id=self.payload.workspace_id,
                project_id=self.payload.project_id,
                task_id=self.payload.task_id,
            )
        if self.payload.note_group_id:
            _require_note_group_scope(
                self.ctx.db,
                workspace_id=self.payload.workspace_id,
                project_id=self.payload.project_id,
                note_group_id=self.payload.note_group_id,
            )
        aggregate = NoteAggregate(
            id=coerce_originator_id(nid),
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            note_group_id=self.payload.note_group_id,
            task_id=self.payload.task_id,
            specification_id=self.payload.specification_id,
            title=title,
            body=self.payload.body or "",
            tags=_normalize_tags(self.payload.tags),
            external_refs=_normalize_external_refs([r.model_dump() for r in self.payload.external_refs]),
            attachment_refs=_normalize_attachment_refs([r.model_dump() for r in self.payload.attachment_refs]),
            pinned=bool(self.payload.pinned),
            archived=False,
            created_by=self.ctx.user.id,
            updated_by=self.ctx.user.id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        AggregateEventRepository(self.ctx.db).persist(
            aggregate,
            base_metadata={
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
        if view is not None:
            return view
        return _note_view_from_aggregate(note_id=nid, aggregate=aggregate)


@dataclass(frozen=True, slots=True)
class PatchNoteHandler:
    ctx: CommandContext
    note_id: str
    payload: NotePatch

    def __call__(self) -> dict:
        workspace_id, project_id, task_id, specification_id, _, _ = require_note_command_state(
            self.ctx.db, self.ctx.user, self.note_id, allowed={"Owner", "Admin", "Member"}
        )
        data = self.payload.model_dump(exclude_unset=True)
        effective_project_id = project_id
        current_note_state = load_note_command_state(self.ctx.db, self.note_id)
        current_note_group_id = current_note_state.note_group_id if current_note_state else None
        if "project_id" in data:
            if not data["project_id"]:
                raise HTTPException(status_code=422, detail="project_id cannot be null")
            _require_project_scope(self.ctx.db, workspace_id=workspace_id, project_id=str(data["project_id"]))
            ensure_project_access(
                self.ctx.db,
                workspace_id,
                str(data["project_id"]),
                self.ctx.user.id,
                {"Owner", "Admin", "Member"},
            )
            effective_project_id = str(data["project_id"])
            if specification_id and "specification_id" not in data:
                raise HTTPException(status_code=409, detail="Cannot change project while note is linked to specification")
            if current_note_group_id and "note_group_id" not in data:
                raise HTTPException(status_code=409, detail="Cannot change project while note is linked to note group")
        if "note_group_id" in data:
            if data["note_group_id"]:
                if not effective_project_id:
                    raise HTTPException(status_code=400, detail="project_id is required when note_group_id is set")
                _require_note_group_scope(
                    self.ctx.db,
                    workspace_id=workspace_id,
                    project_id=effective_project_id,
                    note_group_id=str(data["note_group_id"]),
                )
            else:
                data["note_group_id"] = None
        if "task_id" in data and data["task_id"]:
            if not effective_project_id:
                raise HTTPException(status_code=400, detail="project_id is required when task_id is set")
            _require_task_scope(self.ctx.db, workspace_id=workspace_id, project_id=effective_project_id or "", task_id=str(data["task_id"]))
        if "specification_id" in data:
            if data["specification_id"]:
                if not effective_project_id:
                    raise HTTPException(status_code=400, detail="project_id is required when specification_id is set")
                _require_specification_scope(
                    self.ctx.db,
                    workspace_id=workspace_id,
                    project_id=effective_project_id,
                    specification_id=str(data["specification_id"]),
                )
            else:
                data["specification_id"] = None
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
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="Note",
            aggregate_id=self.note_id,
            aggregate_cls=NoteAggregate,
        )
        aggregate.update(changes=data, updated_by=self.ctx.user.id)
        repo.persist(
            aggregate,
            base_metadata={
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
        workspace_id, project_id, task_id, _, archived, _ = require_note_command_state(
            self.ctx.db, self.ctx.user, self.note_id, allowed={"Owner", "Admin", "Member"}
        )
        if archived:
            raise HTTPException(status_code=409, detail="Note already archived")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="Note",
            aggregate_id=self.note_id,
            aggregate_cls=NoteAggregate,
        )
        aggregate.archive(updated_by=self.ctx.user.id)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": task_id,
                "note_id": self.note_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class RestoreNoteHandler:
    ctx: CommandContext
    note_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, task_id, _, archived, _ = require_note_command_state(
            self.ctx.db, self.ctx.user, self.note_id, allowed={"Owner", "Admin", "Member"}
        )
        if not archived:
            raise HTTPException(status_code=409, detail="Note is not archived")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="Note",
            aggregate_id=self.note_id,
            aggregate_cls=NoteAggregate,
        )
        aggregate.restore(updated_by=self.ctx.user.id)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": task_id,
                "note_id": self.note_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class PinNoteHandler:
    ctx: CommandContext
    note_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, task_id, _, _, pinned = require_note_command_state(
            self.ctx.db, self.ctx.user, self.note_id, allowed={"Owner", "Admin", "Member"}
        )
        if pinned:
            raise HTTPException(status_code=409, detail="Note already pinned")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="Note",
            aggregate_id=self.note_id,
            aggregate_cls=NoteAggregate,
        )
        aggregate.pin(updated_by=self.ctx.user.id)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": task_id,
                "note_id": self.note_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class UnpinNoteHandler:
    ctx: CommandContext
    note_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, task_id, _, _, pinned = require_note_command_state(
            self.ctx.db, self.ctx.user, self.note_id, allowed={"Owner", "Admin", "Member"}
        )
        if not pinned:
            raise HTTPException(status_code=409, detail="Note is not pinned")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="Note",
            aggregate_id=self.note_id,
            aggregate_cls=NoteAggregate,
        )
        aggregate.unpin(updated_by=self.ctx.user.id)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": task_id,
                "note_id": self.note_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class DeleteNoteHandler:
    ctx: CommandContext
    note_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, task_id, _, _, _ = require_note_command_state(
            self.ctx.db, self.ctx.user, self.note_id, allowed={"Owner", "Admin", "Member"}
        )
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="Note",
            aggregate_id=self.note_id,
            aggregate_cls=NoteAggregate,
        )
        aggregate.delete(updated_by=self.ctx.user.id)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": task_id,
                "note_id": self.note_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True}


def _debug_dump_notes(db: Session) -> str:  # pragma: no cover
    notes = db.query(Note).order_by(Note.updated_at.desc()).limit(10).all()
    return json.dumps([{"id": n.id, "title": n.title, "archived": n.archived, "pinned": n.pinned} for n in notes])
