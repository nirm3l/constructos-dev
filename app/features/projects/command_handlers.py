from __future__ import annotations

from dataclasses import dataclass
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.core import (
    AggregateEventRepository,
    DEFAULT_STATUSES,
    Note,
    Project,
    ProjectCreate,
    ProjectMember,
    ProjectPatch,
    ProjectRule,
    ProjectSkill,
    Specification,
    Task,
    User,
    WorkspaceMember,
    coerce_originator_id,
    ensure_project_access,
    ensure_role,
    load_project_view,
)
from shared.settings import ALLOWED_EMBEDDING_MODELS, DEFAULT_EMBEDDING_MODEL
from shared.chat_indexing import (
    CHAT_ATTACHMENT_INGESTION_FULL_TEXT,
    CHAT_ATTACHMENT_INGESTION_METADATA_ONLY,
    CHAT_ATTACHMENT_INGESTION_OFF,
    CHAT_INDEX_MODE_KG_AND_VECTOR,
    CHAT_INDEX_MODE_OFF,
    CHAT_INDEX_MODE_VECTOR_ONLY,
)
from ..notes.domain import NoteAggregate
from ..rules.domain import ProjectRuleAggregate
from ..specifications.domain import SpecificationAggregate
from ..tasks.domain import TaskAggregate
from .domain import ProjectAggregate


@dataclass(frozen=True, slots=True)
class CommandContext:
    db: Session
    user: User


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


def _normalize_project_statuses(values: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        status = str(raw or "").strip()
        if not status:
            continue
        key = status.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(status)
    if not out:
        out = list(DEFAULT_STATUSES)
        seen = {status.lower() for status in out}
    if "done" not in seen:
        out.append("Done")
    return out


def _normalize_project_name(value: str) -> str:
    return " ".join(str(value or "").split())


def _project_name_key(value: str) -> str:
    return _normalize_project_name(value).casefold()


def _project_aggregate_id(workspace_id: str, name: str) -> str:
    key = _project_name_key(name)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"project:{workspace_id}:{key}"))


def _normalize_embedding_model(value: str | None) -> str | None:
    model = str(value or "").strip()
    return model or None


def _resolve_project_embedding_config(*, embedding_enabled: bool, embedding_model: str | None) -> tuple[bool, str | None]:
    normalized_model = _normalize_embedding_model(embedding_model)
    allowed_map = {model.casefold(): model for model in ALLOWED_EMBEDDING_MODELS if str(model).strip()}
    default_model = _normalize_embedding_model(DEFAULT_EMBEDDING_MODEL) or next(iter(allowed_map.values()), None)
    if embedding_enabled and not normalized_model:
        normalized_model = default_model
    if normalized_model:
        canonical = allowed_map.get(normalized_model.casefold())
        if canonical is None:
            allowed = ", ".join(sorted(allowed_map.values()))
            raise HTTPException(
                status_code=422,
                detail=f"embedding_model must be one of: {allowed}",
            )
        normalized_model = canonical
    return bool(embedding_enabled), normalized_model


def _normalize_context_pack_evidence_top_k(value: int | None) -> int | None:
    if value is None:
        return None
    out = int(value)
    if out < 1 or out > 40:
        raise HTTPException(status_code=422, detail="context_pack_evidence_top_k must be between 1 and 40")
    return out


_CHAT_INDEX_MODES = {CHAT_INDEX_MODE_OFF, CHAT_INDEX_MODE_VECTOR_ONLY, CHAT_INDEX_MODE_KG_AND_VECTOR}
_CHAT_ATTACHMENT_INGESTION_MODES = {
    CHAT_ATTACHMENT_INGESTION_OFF,
    CHAT_ATTACHMENT_INGESTION_METADATA_ONLY,
    CHAT_ATTACHMENT_INGESTION_FULL_TEXT,
}


def _normalize_chat_index_mode(value: str | None) -> str:
    mode = str(value or "").strip().upper() or CHAT_INDEX_MODE_OFF
    if mode not in _CHAT_INDEX_MODES:
        allowed = ", ".join(sorted(_CHAT_INDEX_MODES))
        raise HTTPException(status_code=422, detail=f"chat_index_mode must be one of: {allowed}")
    return mode


def _normalize_chat_attachment_ingestion_mode(value: str | None) -> str:
    mode = str(value or "").strip().upper() or CHAT_ATTACHMENT_INGESTION_METADATA_ONLY
    if mode == "FULL_TEXT_OCR":
        return CHAT_ATTACHMENT_INGESTION_FULL_TEXT
    if mode not in _CHAT_ATTACHMENT_INGESTION_MODES:
        allowed = ", ".join(sorted(_CHAT_ATTACHMENT_INGESTION_MODES))
        raise HTTPException(
            status_code=422,
            detail=f"chat_attachment_ingestion_mode must be one of: {allowed}",
        )
    return mode


@dataclass(frozen=True, slots=True)
class CreateProjectHandler:
    ctx: CommandContext
    payload: ProjectCreate

    def __call__(self) -> dict:
        ensure_role(self.ctx.db, self.payload.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member"})
        name = _normalize_project_name(self.payload.name)
        if not name:
            raise HTTPException(status_code=422, detail="name cannot be empty")
        pid = _project_aggregate_id(self.payload.workspace_id, name)
        existing_project = self.ctx.db.get(Project, pid)
        if existing_project and not existing_project.is_deleted:
            existing_view = load_project_view(self.ctx.db, pid)
            if existing_view is None:
                raise HTTPException(status_code=404, detail="Project not found")
            return existing_view
        if existing_project and existing_project.is_deleted:
            raise HTTPException(
                status_code=409,
                detail="Project with this name already exists in deleted state; restore is not supported",
            )

        member_ids: list[str] = [self.ctx.user.id]
        member_ids.extend([str(uid).strip() for uid in self.payload.member_user_ids if str(uid).strip()])
        deduped_member_ids = list(dict.fromkeys(member_ids))
        workspace_users = set(
            self.ctx.db.execute(
                select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == self.payload.workspace_id)
            ).scalars().all()
        )
        for uid in deduped_member_ids:
            if uid not in workspace_users:
                raise HTTPException(status_code=422, detail=f"user_id {uid} is not a member of this workspace")

        embedding_enabled, embedding_model = _resolve_project_embedding_config(
            embedding_enabled=bool(self.payload.embedding_enabled),
            embedding_model=self.payload.embedding_model,
        )

        aggregate = ProjectAggregate(
            id=coerce_originator_id(pid),
            workspace_id=self.payload.workspace_id,
            name=name,
            description=self.payload.description,
            custom_statuses=_normalize_project_statuses(self.payload.custom_statuses),
            external_refs=_normalize_external_refs([r.model_dump() for r in self.payload.external_refs]),
            attachment_refs=_normalize_attachment_refs([r.model_dump() for r in self.payload.attachment_refs]),
            embedding_enabled=embedding_enabled,
            embedding_model=embedding_model,
            context_pack_evidence_top_k=_normalize_context_pack_evidence_top_k(self.payload.context_pack_evidence_top_k),
            chat_index_mode=_normalize_chat_index_mode(self.payload.chat_index_mode),
            chat_attachment_ingestion_mode=_normalize_chat_attachment_ingestion_mode(
                self.payload.chat_attachment_ingestion_mode
            ),
            status="Active",
        )
        for uid in deduped_member_ids:
            aggregate.upsert_member(user_id=uid, role="Owner" if uid == self.ctx.user.id else "Contributor")
        AggregateEventRepository(self.ctx.db).persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": self.payload.workspace_id,
                "project_id": pid,
            },
            expected_version=0,
        )
        self.ctx.db.commit()
        project_view = load_project_view(self.ctx.db, pid)
        if project_view is None:
            raise HTTPException(status_code=404, detail="Project not found after create")
        return project_view


@dataclass(frozen=True, slots=True)
class DeleteProjectHandler:
    ctx: CommandContext
    project_id: str

    def __call__(self) -> dict:
        project = self.ctx.db.get(Project, self.project_id)
        if not project or project.is_deleted:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_access(self.ctx.db, project.workspace_id, self.project_id, self.ctx.user.id, {"Owner", "Admin", "Member"})

        repo = AggregateEventRepository(self.ctx.db)
        tasks = self.ctx.db.execute(select(Task).where(Task.project_id == self.project_id, Task.is_deleted == False)).scalars().all()
        for t in tasks:
            task_aggregate = repo.load_with_class(
                aggregate_type="Task",
                aggregate_id=t.id,
                aggregate_cls=TaskAggregate,
            )
            task_aggregate.delete()
            repo.persist(
                task_aggregate,
                base_metadata={
                    "actor_id": self.ctx.user.id,
                    "workspace_id": project.workspace_id,
                    "task_id": t.id,
                    "project_id": self.project_id,
                },
            )
        notes = self.ctx.db.execute(select(Note).where(Note.project_id == self.project_id, Note.is_deleted == False)).scalars().all()
        for n in notes:
            note_aggregate = repo.load_with_class(
                aggregate_type="Note",
                aggregate_id=n.id,
                aggregate_cls=NoteAggregate,
            )
            note_aggregate.delete(updated_by=self.ctx.user.id)
            repo.persist(
                note_aggregate,
                base_metadata={
                    "actor_id": self.ctx.user.id,
                    "workspace_id": project.workspace_id,
                    "task_id": n.task_id,
                    "project_id": self.project_id,
                    "note_id": n.id,
                },
            )
        rules = self.ctx.db.execute(select(ProjectRule).where(ProjectRule.project_id == self.project_id, ProjectRule.is_deleted == False)).scalars().all()
        for r in rules:
            rule_aggregate = repo.load_with_class(
                aggregate_type="ProjectRule",
                aggregate_id=r.id,
                aggregate_cls=ProjectRuleAggregate,
            )
            rule_aggregate.delete(updated_by=self.ctx.user.id)
            repo.persist(
                rule_aggregate,
                base_metadata={
                    "actor_id": self.ctx.user.id,
                    "workspace_id": project.workspace_id,
                    "project_id": self.project_id,
                    "project_rule_id": r.id,
                },
            )
        specifications = self.ctx.db.execute(
            select(Specification).where(Specification.project_id == self.project_id, Specification.is_deleted == False)
        ).scalars().all()
        for specification in specifications:
            specification_aggregate = repo.load_with_class(
                aggregate_type="Specification",
                aggregate_id=specification.id,
                aggregate_cls=SpecificationAggregate,
            )
            specification_aggregate.delete(updated_by=self.ctx.user.id)
            repo.persist(
                specification_aggregate,
                base_metadata={
                    "actor_id": self.ctx.user.id,
                    "workspace_id": project.workspace_id,
                    "project_id": self.project_id,
                    "specification_id": specification.id,
                },
            )
        skills = self.ctx.db.execute(
            select(ProjectSkill).where(ProjectSkill.project_id == self.project_id, ProjectSkill.is_deleted == False)
        ).scalars().all()
        for skill in skills:
            skill.is_deleted = True
            skill.updated_by = self.ctx.user.id
        aggregate = repo.load_with_class(
            aggregate_type="Project",
            aggregate_id=self.project_id,
            aggregate_cls=ProjectAggregate,
        )
        aggregate.delete(deleted_tasks=len(tasks), deleted_notes=len(notes))
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": project.workspace_id,
                "project_id": self.project_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True, "deleted_tasks": len(tasks), "deleted_notes": len(notes)}


@dataclass(frozen=True, slots=True)
class PatchProjectHandler:
    ctx: CommandContext
    project_id: str
    payload: ProjectPatch

    def __call__(self) -> dict:
        project = self.ctx.db.get(Project, self.project_id)
        if not project or project.is_deleted:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_access(self.ctx.db, project.workspace_id, self.project_id, self.ctx.user.id, {"Owner", "Admin", "Member"})

        data = self.payload.model_dump(exclude_unset=True)
        event_payload: dict = {}
        if "name" in data and data["name"] is not None:
            name = str(data["name"]).strip()
            if not name:
                raise HTTPException(status_code=422, detail="name cannot be empty")
            event_payload["name"] = name
        if "description" in data and data["description"] is not None:
            event_payload["description"] = str(data["description"])
        if "custom_statuses" in data and data["custom_statuses"] is not None:
            event_payload["custom_statuses"] = _normalize_project_statuses(data["custom_statuses"])
        if "external_refs" in data and data["external_refs"] is not None:
            event_payload["external_refs"] = _normalize_external_refs(data["external_refs"])
        if "attachment_refs" in data and data["attachment_refs"] is not None:
            event_payload["attachment_refs"] = _normalize_attachment_refs(data["attachment_refs"])
        if "embedding_enabled" in data and data["embedding_enabled"] is None:
            raise HTTPException(status_code=422, detail="embedding_enabled cannot be null")

        if "embedding_enabled" in data or "embedding_model" in data:
            next_enabled = bool(data.get("embedding_enabled", project.embedding_enabled))
            next_model = data.get("embedding_model", project.embedding_model)
            resolved_enabled, resolved_model = _resolve_project_embedding_config(
                embedding_enabled=next_enabled,
                embedding_model=next_model,
            )
            event_payload["embedding_enabled"] = resolved_enabled
            event_payload["embedding_model"] = resolved_model

        if "context_pack_evidence_top_k" in data:
            event_payload["context_pack_evidence_top_k"] = _normalize_context_pack_evidence_top_k(
                data.get("context_pack_evidence_top_k")
            )
        if "chat_index_mode" in data and data["chat_index_mode"] is not None:
            event_payload["chat_index_mode"] = _normalize_chat_index_mode(data.get("chat_index_mode"))
        if "chat_attachment_ingestion_mode" in data and data["chat_attachment_ingestion_mode"] is not None:
            event_payload["chat_attachment_ingestion_mode"] = _normalize_chat_attachment_ingestion_mode(
                data.get("chat_attachment_ingestion_mode")
            )

        if not event_payload:
            view = load_project_view(self.ctx.db, self.project_id)
            if view is None:
                raise HTTPException(status_code=404, detail="Project not found")
            return view

        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="Project",
            aggregate_id=self.project_id,
            aggregate_cls=ProjectAggregate,
        )
        aggregate.update(**event_payload)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": project.workspace_id,
                "project_id": self.project_id,
            },
        )
        self.ctx.db.commit()
        view = load_project_view(self.ctx.db, self.project_id)
        if view is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return view


@dataclass(frozen=True, slots=True)
class AddProjectMemberHandler:
    ctx: CommandContext
    project_id: str
    user_id: str
    role: str = "Contributor"

    def __call__(self) -> dict:
        project = self.ctx.db.get(Project, self.project_id)
        if not project or project.is_deleted:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_access(self.ctx.db, project.workspace_id, self.project_id, self.ctx.user.id, {"Owner", "Admin", "Member"})
        member_exists = self.ctx.db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == project.workspace_id,
                WorkspaceMember.user_id == self.user_id,
            )
        ).scalar_one_or_none()
        if not member_exists:
            raise HTTPException(status_code=422, detail="user_id is not a member of this workspace")

        project_member = self.ctx.db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == self.project_id,
                ProjectMember.user_id == self.user_id,
            )
        ).scalar_one_or_none()
        normalized_role = str(self.role or "Contributor").strip() or "Contributor"
        if project_member is not None and project_member.role == normalized_role:
            return {"ok": True, "project_id": self.project_id, "user_id": self.user_id, "role": normalized_role}
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="Project",
            aggregate_id=self.project_id,
            aggregate_cls=ProjectAggregate,
        )
        aggregate.upsert_member(user_id=self.user_id, role=normalized_role)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": project.workspace_id,
                "project_id": self.project_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True, "project_id": self.project_id, "user_id": self.user_id, "role": normalized_role}


@dataclass(frozen=True, slots=True)
class RemoveProjectMemberHandler:
    ctx: CommandContext
    project_id: str
    user_id: str

    def __call__(self) -> dict:
        project = self.ctx.db.get(Project, self.project_id)
        if not project or project.is_deleted:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_access(self.ctx.db, project.workspace_id, self.project_id, self.ctx.user.id, {"Owner", "Admin", "Member"})
        project_member = self.ctx.db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == self.project_id,
                ProjectMember.user_id == self.user_id,
            )
        ).scalar_one_or_none()
        if project_member is None:
            return {"ok": True, "project_id": self.project_id, "user_id": self.user_id}
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="Project",
            aggregate_id=self.project_id,
            aggregate_cls=ProjectAggregate,
        )
        aggregate.remove_member(user_id=self.user_id)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": project.workspace_id,
                "project_id": self.project_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True, "project_id": self.project_id, "user_id": self.user_id}
