from __future__ import annotations

from dataclasses import dataclass
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from shared.core import (
    AggregateEventRepository,
    Project,
    Specification,
    SpecificationCreate,
    SpecificationPatch,
    User,
    coerce_originator_id,
    ensure_project_access,
    ensure_role,
    load_specification_command_state,
    load_specification_view,
)

from .domain import SpecificationAggregate

ALLOWED_SPEC_STATUSES = {"Draft", "Ready", "In progress", "Implemented", "Archived"}
SPEC_STATUS_ALIASES = {
    "draft": "Draft",
    "todo": "Draft",
    "to do": "Draft",
    "planned": "Draft",
    "plan": "Draft",
    "ready": "Ready",
    "in progress": "In progress",
    "inprogress": "In progress",
    "wip": "In progress",
    "implemented": "Implemented",
    "done": "Implemented",
    "complete": "Implemented",
    "completed": "Implemented",
    "archived": "Archived",
    "archive": "Archived",
}


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


def _normalize_specification_title(value: str) -> str:
    return " ".join(str(value or "").split())


def _specification_title_key(value: str) -> str:
    return _normalize_specification_title(value).casefold()


def _specification_aggregate_id(project_id: str, title: str) -> str:
    key = _specification_title_key(title)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"specification:{project_id}:{key}"))


def _normalize_status(value: str | None) -> str:
    status = str(value or "").strip()
    if status in ALLOWED_SPEC_STATUSES:
        return status

    normalized = " ".join(status.lower().replace("_", " ").replace("-", " ").split())
    if normalized in SPEC_STATUS_ALIASES:
        return SPEC_STATUS_ALIASES[normalized]

    raise HTTPException(status_code=422, detail=f"status must be one of: {', '.join(sorted(ALLOWED_SPEC_STATUSES))}")


def _require_project_scope(db: Session, *, workspace_id: str, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Project does not belong to workspace")
    return project


def require_specification_command_state(
    db: Session, user: User, specification_id: str, *, allowed: set[str]
) -> tuple[str, str, str, bool]:
    state = load_specification_command_state(db, specification_id)
    if not state or state.is_deleted:
        raise HTTPException(status_code=404, detail="Specification not found")
    ensure_project_access(db, state.workspace_id, state.project_id, user.id, allowed)
    return state.workspace_id, state.project_id, state.status, bool(state.archived)


@dataclass(frozen=True, slots=True)
class CommandContext:
    db: Session
    user: User


@dataclass(frozen=True, slots=True)
class CreateSpecificationHandler:
    ctx: CommandContext
    payload: SpecificationCreate

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

        title = _normalize_specification_title(self.payload.title)
        if not title:
            raise HTTPException(status_code=422, detail="title cannot be empty")

        status = _normalize_status(self.payload.status)
        sid = _specification_aggregate_id(self.payload.project_id, title)
        existing_specification = self.ctx.db.get(Specification, sid)
        if existing_specification and not existing_specification.is_deleted:
            view = load_specification_view(self.ctx.db, sid)
            if view is None:
                raise HTTPException(status_code=404, detail="Specification not found")
            return view
        if existing_specification and existing_specification.is_deleted:
            raise HTTPException(
                status_code=409,
                detail="Specification with this title already exists in deleted state; restore is not supported",
            )

        aggregate = SpecificationAggregate(
            id=coerce_originator_id(sid),
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            title=title,
            body=self.payload.body or "",
            status=status,
            tags=_normalize_tags(self.payload.tags),
            external_refs=_normalize_external_refs([r.model_dump() for r in self.payload.external_refs]),
            attachment_refs=_normalize_attachment_refs([r.model_dump() for r in self.payload.attachment_refs]),
            created_by=self.ctx.user.id,
        )
        AggregateEventRepository(self.ctx.db).persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": self.payload.workspace_id,
                "project_id": self.payload.project_id,
                "specification_id": sid,
            },
            expected_version=0,
        )
        self.ctx.db.commit()
        view = load_specification_view(self.ctx.db, sid)
        if view is None:
            raise HTTPException(status_code=404, detail="Specification not found after create")
        return view


@dataclass(frozen=True, slots=True)
class PatchSpecificationHandler:
    ctx: CommandContext
    specification_id: str
    payload: SpecificationPatch

    def __call__(self) -> dict:
        workspace_id, project_id, _, archived = require_specification_command_state(
            self.ctx.db,
            self.ctx.user,
            self.specification_id,
            allowed={"Owner", "Admin", "Member"},
        )
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="Specification",
            aggregate_id=self.specification_id,
            aggregate_cls=SpecificationAggregate,
        )
        if bool(getattr(aggregate, "is_deleted", False)):
            raise HTTPException(status_code=404, detail="Specification not found")
        if not getattr(aggregate, "workspace_id", ""):
            aggregate.workspace_id = workspace_id
        if not getattr(aggregate, "project_id", ""):
            aggregate.project_id = project_id
        data = self.payload.model_dump(exclude_unset=True)

        event_payload: dict[str, object] = {}
        if "title" in data and data["title"] is not None:
            title = str(data["title"]).strip()
            if not title:
                raise HTTPException(status_code=422, detail="title cannot be empty")
            event_payload["title"] = title
        if "body" in data and data["body"] is not None:
            event_payload["body"] = str(data["body"])
        if "status" in data and data["status"] is not None:
            event_payload["status"] = _normalize_status(data["status"])
        if "tags" in data and data["tags"] is not None:
            event_payload["tags"] = _normalize_tags(data["tags"])
        if "external_refs" in data and data["external_refs"] is not None:
            event_payload["external_refs"] = _normalize_external_refs(data["external_refs"])
        if "attachment_refs" in data and data["attachment_refs"] is not None:
            event_payload["attachment_refs"] = _normalize_attachment_refs(data["attachment_refs"])

        if "archived" in data and data["archived"] is not None:
            requested_archived = bool(data["archived"])
            if requested_archived and not archived:
                try:
                    aggregate.archive(updated_by=self.ctx.user.id)
                except ValueError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                archived = True
            elif not requested_archived and archived:
                try:
                    aggregate.restore_archived(updated_by=self.ctx.user.id)
                except ValueError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                archived = False

        if event_payload:
            aggregate.update(changes=dict(event_payload), updated_by=self.ctx.user.id)

        if not event_payload and "archived" not in data:
            view = load_specification_view(self.ctx.db, self.specification_id)
            if view is None:
                raise HTTPException(status_code=404, detail="Specification not found")
            return view

        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "specification_id": self.specification_id,
            },
        )
        self.ctx.db.commit()
        view = load_specification_view(self.ctx.db, self.specification_id)
        if view is None:
            raise HTTPException(status_code=404, detail="Specification not found")
        return view


@dataclass(frozen=True, slots=True)
class ArchiveSpecificationHandler:
    ctx: CommandContext
    specification_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, _, archived = require_specification_command_state(
            self.ctx.db,
            self.ctx.user,
            self.specification_id,
            allowed={"Owner", "Admin", "Member"},
        )
        if archived:
            raise HTTPException(status_code=409, detail="Specification already archived")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="Specification",
            aggregate_id=self.specification_id,
            aggregate_cls=SpecificationAggregate,
        )
        try:
            aggregate.archive(updated_by=self.ctx.user.id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "specification_id": self.specification_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class RestoreSpecificationHandler:
    ctx: CommandContext
    specification_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, _, archived = require_specification_command_state(
            self.ctx.db,
            self.ctx.user,
            self.specification_id,
            allowed={"Owner", "Admin", "Member"},
        )
        if not archived:
            raise HTTPException(status_code=409, detail="Specification is not archived")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="Specification",
            aggregate_id=self.specification_id,
            aggregate_cls=SpecificationAggregate,
        )
        try:
            aggregate.restore_archived(updated_by=self.ctx.user.id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "specification_id": self.specification_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class DeleteSpecificationHandler:
    ctx: CommandContext
    specification_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, _, _ = require_specification_command_state(
            self.ctx.db,
            self.ctx.user,
            self.specification_id,
            allowed={"Owner", "Admin", "Member"},
        )
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="Specification",
            aggregate_id=self.specification_id,
            aggregate_cls=SpecificationAggregate,
        )
        if bool(getattr(aggregate, "is_deleted", False)):
            return {"ok": True}
        try:
            aggregate.delete(updated_by=self.ctx.user.id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "specification_id": self.specification_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True}
