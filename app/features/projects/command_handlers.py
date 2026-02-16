from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.core import ActivityLog, DEFAULT_STATUSES, Note, Project, ProjectCreate, ProjectPatch, SavedView, Task, User, append_event, allocate_id, ensure_role, load_project_view
from ..notes.domain import EVENT_DELETED as NOTE_EVENT_DELETED
from ..tasks.domain import EVENT_DELETED as TASK_EVENT_DELETED
from .domain import EVENT_CREATED as PROJECT_EVENT_CREATED
from .domain import EVENT_DELETED as PROJECT_EVENT_DELETED
from .domain import EVENT_UPDATED as PROJECT_EVENT_UPDATED


@dataclass(frozen=True, slots=True)
class CommandContext:
    db: Session
    user: User


@dataclass(frozen=True, slots=True)
class CreateProjectHandler:
    ctx: CommandContext
    payload: ProjectCreate

    def __call__(self) -> dict:
        ensure_role(self.ctx.db, self.payload.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member"})
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
                "status": "Active",
            },
            metadata={"actor_id": self.ctx.user.id, "workspace_id": self.payload.workspace_id, "project_id": pid},
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
        for view in self.ctx.db.execute(select(SavedView).where(SavedView.project_id == self.project_id)).scalars().all():
            self.ctx.db.delete(view)
        for log in self.ctx.db.execute(select(ActivityLog).where(ActivityLog.project_id == self.project_id)).scalars().all():
            self.ctx.db.delete(log)
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
        event_payload: dict[str, str] = {}
        if "name" in data and data["name"] is not None:
            name = str(data["name"]).strip()
            if not name:
                raise HTTPException(status_code=422, detail="name cannot be empty")
            event_payload["name"] = name
        if "description" in data and data["description"] is not None:
            event_payload["description"] = str(data["description"])

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
