from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.core import (
    ActivityLog,
    DEFAULT_STATUSES,
    Note,
    Project,
    ProjectCreate,
    ProjectMember,
    ProjectPatch,
    ProjectRule,
    SavedView,
    Task,
    User,
    WorkspaceMember,
    append_event,
    allocate_id,
    ensure_role,
    load_project_view,
)
from ..notes.domain import EVENT_DELETED as NOTE_EVENT_DELETED
from ..rules.domain import EVENT_DELETED as PROJECT_RULE_EVENT_DELETED
from ..tasks.domain import EVENT_DELETED as TASK_EVENT_DELETED
from .domain import EVENT_CREATED as PROJECT_EVENT_CREATED
from .domain import EVENT_DELETED as PROJECT_EVENT_DELETED
from .domain import EVENT_UPDATED as PROJECT_EVENT_UPDATED


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


@dataclass(frozen=True, slots=True)
class CreateProjectHandler:
    ctx: CommandContext
    payload: ProjectCreate

    def __call__(self) -> dict:
        ensure_role(self.ctx.db, self.payload.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member"})
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

        pid = allocate_id(self.ctx.db)
        append_event(
            self.ctx.db,
            aggregate_type="Project",
            aggregate_id=pid,
            event_type=PROJECT_EVENT_CREATED,
            payload={
                "workspace_id": self.payload.workspace_id,
                "name": self.payload.name.strip(),
                "description": self.payload.description,
                "custom_statuses": self.payload.custom_statuses or DEFAULT_STATUSES,
                "external_refs": _normalize_external_refs([r.model_dump() for r in self.payload.external_refs]),
                "attachment_refs": _normalize_attachment_refs([r.model_dump() for r in self.payload.attachment_refs]),
                "status": "Active",
            },
            metadata={"actor_id": self.ctx.user.id, "workspace_id": self.payload.workspace_id, "project_id": pid},
            expected_version=0,
        )
        self.ctx.db.commit()
        # Assign project members (creator is always assigned as Owner).
        for uid in deduped_member_ids:
            existing = self.ctx.db.execute(
                select(ProjectMember).where(ProjectMember.project_id == pid, ProjectMember.user_id == uid)
            ).scalar_one_or_none()
            if existing:
                continue
            self.ctx.db.add(
                ProjectMember(
                    workspace_id=self.payload.workspace_id,
                    project_id=pid,
                    user_id=uid,
                    role="Owner" if uid == self.ctx.user.id else "Contributor",
                )
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
        ensure_role(self.ctx.db, project.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member"})

        tasks = self.ctx.db.execute(select(Task).where(Task.project_id == self.project_id, Task.is_deleted == False)).scalars().all()
        for t in tasks:
            append_event(
                self.ctx.db,
                aggregate_type="Task",
                aggregate_id=t.id,
                event_type=TASK_EVENT_DELETED,
                payload={},
                metadata={"actor_id": self.ctx.user.id, "workspace_id": project.workspace_id, "task_id": t.id, "project_id": self.project_id},
            )
        notes = self.ctx.db.execute(select(Note).where(Note.project_id == self.project_id, Note.is_deleted == False)).scalars().all()
        for n in notes:
            append_event(
                self.ctx.db,
                aggregate_type="Note",
                aggregate_id=n.id,
                event_type=NOTE_EVENT_DELETED,
                payload={"updated_by": self.ctx.user.id},
                metadata={"actor_id": self.ctx.user.id, "workspace_id": project.workspace_id, "task_id": n.task_id, "project_id": self.project_id, "note_id": n.id},
            )
        rules = self.ctx.db.execute(select(ProjectRule).where(ProjectRule.project_id == self.project_id, ProjectRule.is_deleted == False)).scalars().all()
        for r in rules:
            append_event(
                self.ctx.db,
                aggregate_type="ProjectRule",
                aggregate_id=r.id,
                event_type=PROJECT_RULE_EVENT_DELETED,
                payload={"updated_by": self.ctx.user.id},
                metadata={"actor_id": self.ctx.user.id, "workspace_id": project.workspace_id, "project_id": self.project_id, "project_rule_id": r.id},
            )
        for view in self.ctx.db.execute(select(SavedView).where(SavedView.project_id == self.project_id)).scalars().all():
            self.ctx.db.delete(view)
        for log in self.ctx.db.execute(select(ActivityLog).where(ActivityLog.project_id == self.project_id)).scalars().all():
            self.ctx.db.delete(log)
        for member in self.ctx.db.execute(select(ProjectMember).where(ProjectMember.project_id == self.project_id)).scalars().all():
            self.ctx.db.delete(member)
        append_event(
            self.ctx.db,
            aggregate_type="Project",
            aggregate_id=self.project_id,
            event_type=PROJECT_EVENT_DELETED,
            payload={"deleted_tasks": len(tasks), "deleted_notes": len(notes)},
            metadata={"actor_id": self.ctx.user.id, "workspace_id": project.workspace_id, "project_id": self.project_id},
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
        ensure_role(self.ctx.db, project.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member"})

        data = self.payload.model_dump(exclude_unset=True)
        event_payload: dict = {}
        if "name" in data and data["name"] is not None:
            name = str(data["name"]).strip()
            if not name:
                raise HTTPException(status_code=422, detail="name cannot be empty")
            event_payload["name"] = name
        if "description" in data and data["description"] is not None:
            event_payload["description"] = str(data["description"])
        if "external_refs" in data and data["external_refs"] is not None:
            event_payload["external_refs"] = _normalize_external_refs(data["external_refs"])
        if "attachment_refs" in data and data["attachment_refs"] is not None:
            event_payload["attachment_refs"] = _normalize_attachment_refs(data["attachment_refs"])

        if not event_payload:
            view = load_project_view(self.ctx.db, self.project_id)
            if view is None:
                raise HTTPException(status_code=404, detail="Project not found")
            return view

        append_event(
            self.ctx.db,
            aggregate_type="Project",
            aggregate_id=self.project_id,
            event_type=PROJECT_EVENT_UPDATED,
            payload=event_payload,
            metadata={"actor_id": self.ctx.user.id, "workspace_id": project.workspace_id, "project_id": self.project_id},
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
        ensure_role(self.ctx.db, project.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member"})
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
        if project_member is None:
            self.ctx.db.add(
                ProjectMember(
                    workspace_id=project.workspace_id,
                    project_id=self.project_id,
                    user_id=self.user_id,
                    role=normalized_role,
                )
            )
        else:
            project_member.role = normalized_role
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
        ensure_role(self.ctx.db, project.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member"})
        project_member = self.ctx.db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == self.project_id,
                ProjectMember.user_id == self.user_id,
            )
        ).scalar_one_or_none()
        if project_member is not None:
            self.ctx.db.delete(project_member)
            self.ctx.db.commit()
        return {"ok": True, "project_id": self.project_id, "user_id": self.user_id}
