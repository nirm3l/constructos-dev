from __future__ import annotations

from dataclasses import dataclass
import json
import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from shared.core import (
    AggregateEventRepository,
    ProjectRuleCreate,
    ProjectRulePatch,
    User,
    coerce_originator_id,
    ensure_project_access,
    allocate_id,
    ensure_role,
    load_project_command_state,
    load_project_rule_command_state,
    load_project_rule_view,
)

from .domain import ProjectRuleAggregate
from features.agents.gates import DEFAULT_GATE_POLICY, merge_gate_policy_dict

_GATE_POLICY_RULE_TITLES = ("gate policy", "delivery gates", "workflow gates")


def _should_prettify_rule_body(title: str) -> bool:
    normalized_title = str(title or "").strip().lower()
    return any(marker in normalized_title for marker in _GATE_POLICY_RULE_TITLES)


def _extract_json_candidate(body: str) -> str:
    raw = str(body or "").strip()
    if not raw:
        return raw
    fenced_match = re.search(r"```(?:json)?\s*(\{[\s\S]*\}|\[[\s\S]*\])\s*```", raw, flags=re.IGNORECASE)
    if fenced_match:
        return str(fenced_match.group(1) or "").strip()
    return raw


def _prettify_gate_policy_body_if_needed(*, title: str, body: str) -> str:
    raw_body = str(body or "")
    if not _should_prettify_rule_body(title):
        return raw_body
    candidate = _extract_json_candidate(raw_body)
    if not candidate:
        return raw_body
    try:
        parsed = json.loads(candidate)
    except Exception:
        return raw_body
    if not _validate_gate_policy_shape(parsed):
        raise HTTPException(
            status_code=422,
            detail="Gate Policy JSON is invalid: required_checks must be an object whose values are arrays of non-empty check ids.",
        )
    parsed = _normalize_gate_policy(parsed)
    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    return f"```json\n{pretty}\n```"


def _validate_gate_policy_shape(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    required_checks = value.get("required_checks")
    if required_checks is None:
        return True
    if not isinstance(required_checks, dict):
        return False
    for scope_name, scope_checks in required_checks.items():
        if str(scope_name or "").strip() == "":
            return False
        if not isinstance(scope_checks, list):
            return False
        for check_name in scope_checks:
            if str(check_name or "").strip() == "":
                return False
    return True


def _normalize_gate_policy(policy: dict) -> dict:
    return merge_gate_policy_dict(dict(DEFAULT_GATE_POLICY), dict(policy or {}))


def _require_project_scope(db: Session, *, workspace_id: str, project_id: str) -> None:
    project = load_project_command_state(db, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Project does not belong to workspace")


def _project_rule_view_from_aggregate(*, rule_id: str, aggregate: ProjectRuleAggregate) -> dict:
    return {
        "id": rule_id,
        "workspace_id": getattr(aggregate, "workspace_id", None),
        "project_id": getattr(aggregate, "project_id", None),
        "title": getattr(aggregate, "title", "") or "",
        "body": getattr(aggregate, "body", "") or "",
        "created_by": getattr(aggregate, "created_by", "") or "",
        "updated_by": getattr(aggregate, "updated_by", "") or "",
        "created_at": None,
        "updated_at": None,
    }


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
        body = _prettify_gate_policy_body_if_needed(
            title=title,
            body=self.payload.body or "",
        )
        aggregate = ProjectRuleAggregate(
            id=coerce_originator_id(rid),
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            title=title,
            body=body,
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
        if view is not None:
            return view
        return _project_rule_view_from_aggregate(rule_id=rid, aggregate=aggregate)


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
            effective_title = event_payload.get("title", str(getattr(aggregate, "title", "") or ""))
            event_payload["body"] = _prettify_gate_policy_body_if_needed(
                title=effective_title,
                body=str(data["body"]),
            )
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
