from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.core import DEFAULT_STATUSES, Project, ProjectCreate, Task, User, append_event, allocate_id, ensure_role, load_project_view
from ..tasks.domain import EVENT_MOVED_TO_INBOX as TASK_EVENT_MOVED_TO_INBOX
from .domain import EVENT_CREATED as PROJECT_EVENT_CREATED
from .domain import EVENT_DELETED as PROJECT_EVENT_DELETED


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
                event_type=TASK_EVENT_MOVED_TO_INBOX,
                payload={"from_project_id": self.project_id},
                metadata={"actor_id": self.ctx.user.id, "workspace_id": project.workspace_id, "task_id": t.id, "project_id": self.project_id},
            )
        append_event(
            self.ctx.db,
            aggregate_type="Project",
            aggregate_id=self.project_id,
            event_type=PROJECT_EVENT_DELETED,
            payload={"moved_tasks": len(tasks)},
            metadata={"actor_id": self.ctx.user.id, "workspace_id": project.workspace_id, "project_id": self.project_id},
        )
        self.ctx.db.commit()
        return {"ok": True, "moved_tasks": len(tasks)}
