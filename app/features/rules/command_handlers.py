from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session

from shared.core import (
    AggregateEventRepository,
    Project,
    ProjectRuleCreate,
    ProjectRulePatch,
    User,
    ensure_project_access,
    allocate_id,
    ensure_role,
    load_project_rule_command_state,
    load_project_rule_view,
)

from .domain import ProjectRuleAggregate


def _require_project_scope(db: Session, *, workspace_id: str, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Project does not belong to workspace")
    return project


def require_project_rule_command_state(db: Session, user: User, rule_id: str, *, allowed: set[str]) -> tuple[str, str]:
    state = load_project_rule_command_state(db, rule_id)
    if not state or state.is_deleted:
        raise HTTPException(status_code=404, detail="Project rule not found")
    ensure_project_access(db, state.workspace_id, state.project_id, user.id, allowed)
    return state.workspace_id, state.project_id


@dataclass(frozen=True, slots=True)
class CommandContext:
    db: Session
    user: User


@dataclass(frozen=True, slots=True)
class CreateProjectRuleHandler:
    ctx: CommandContext
    payload: ProjectRuleCreate

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
        rid = allocate_id(self.ctx.db)
        title = self.payload.title.strip()
        if not title:
            raise HTTPException(status_code=422, detail="title cannot be empty")
        aggregate = ProjectRuleAggregate(rid, version=0)
        aggregate.create(
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            title=title,
            body=self.payload.body or "",
            created_by=self.ctx.user.id,
        )
        AggregateEventRepository(self.ctx.db).persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": self.payload.workspace_id,
                "project_id": self.payload.project_id,
                "project_rule_id": rid,
            },
            expected_version=0,
        )
        self.ctx.db.commit()
        view = load_project_rule_view(self.ctx.db, rid)
        if view is None:
            raise HTTPException(status_code=404, detail="Project rule not found after create")
        return view


@dataclass(frozen=True, slots=True)
class PatchProjectRuleHandler:
    ctx: CommandContext
    rule_id: str
    payload: ProjectRulePatch

    def __call__(self) -> dict:
        workspace_id, project_id = require_project_rule_command_state(
            self.ctx.db, self.ctx.user, self.rule_id, allowed={"Owner", "Admin", "Member"}
        )
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="ProjectRule",
            aggregate_id=self.rule_id,
            aggregate_cls=ProjectRuleAggregate,
        )
        if not getattr(aggregate, "workspace_id", ""):
            aggregate.workspace_id = workspace_id
        if not getattr(aggregate, "project_id", ""):
            aggregate.project_id = project_id
        if bool(getattr(aggregate, "is_deleted", False)):
            raise HTTPException(status_code=404, detail="Project rule not found")
        data = self.payload.model_dump(exclude_unset=True)
        event_payload: dict[str, str] = {}
        if "title" in data and data["title"] is not None:
            title = str(data["title"]).strip()
            if not title:
                raise HTTPException(status_code=422, detail="title cannot be empty")
            event_payload["title"] = title
        if "body" in data and data["body"] is not None:
            event_payload["body"] = str(data["body"])
        if not event_payload:
            view = load_project_rule_view(self.ctx.db, self.rule_id)
            if view is None:
                raise HTTPException(status_code=404, detail="Project rule not found")
            return view
        aggregate.update(changes=event_payload, updated_by=self.ctx.user.id)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "project_rule_id": self.rule_id,
            },
        )
        self.ctx.db.commit()
        view = load_project_rule_view(self.ctx.db, self.rule_id)
        if view is None:
            raise HTTPException(status_code=404, detail="Project rule not found")
        return view


@dataclass(frozen=True, slots=True)
class DeleteProjectRuleHandler:
    ctx: CommandContext
    rule_id: str

    def __call__(self) -> dict:
        workspace_id, project_id = require_project_rule_command_state(
            self.ctx.db, self.ctx.user, self.rule_id, allowed={"Owner", "Admin", "Member"}
        )
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="ProjectRule",
            aggregate_id=self.rule_id,
            aggregate_cls=ProjectRuleAggregate,
        )
        if bool(getattr(aggregate, "is_deleted", False)):
            return {"ok": True}
        aggregate.delete(updated_by=self.ctx.user.id)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "project_rule_id": self.rule_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True}
