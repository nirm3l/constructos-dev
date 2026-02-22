from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from shared.core import User, ensure_project_access, ensure_role, to_iso_utc
from shared.models import ProjectSkill, WorkspaceSkill


def _parse_manifest(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def serialize_project_skill(skill: ProjectSkill) -> dict[str, Any]:
    return {
        "id": skill.id,
        "workspace_id": skill.workspace_id,
        "project_id": skill.project_id,
        "skill_key": skill.skill_key,
        "name": skill.name,
        "summary": skill.summary or "",
        "source_type": skill.source_type,
        "source_locator": skill.source_locator,
        "source_version": skill.source_version,
        "trust_level": skill.trust_level,
        "mode": skill.mode,
        "generated_rule_id": skill.generated_rule_id,
        "manifest": _parse_manifest(skill.manifest_json),
        "created_by": skill.created_by,
        "updated_by": skill.updated_by,
        "created_at": to_iso_utc(skill.created_at),
        "updated_at": to_iso_utc(skill.updated_at),
    }


def serialize_workspace_skill(skill: WorkspaceSkill) -> dict[str, Any]:
    return {
        "id": skill.id,
        "workspace_id": skill.workspace_id,
        "skill_key": skill.skill_key,
        "name": skill.name,
        "summary": skill.summary or "",
        "source_type": skill.source_type,
        "source_locator": skill.source_locator,
        "source_version": skill.source_version,
        "trust_level": skill.trust_level,
        "mode": skill.mode,
        "is_seeded": bool(skill.is_seeded),
        "manifest": _parse_manifest(skill.manifest_json),
        "created_by": skill.created_by,
        "updated_by": skill.updated_by,
        "created_at": to_iso_utc(skill.created_at),
        "updated_at": to_iso_utc(skill.updated_at),
    }


@dataclass(frozen=True, slots=True)
class ProjectSkillListQuery:
    workspace_id: str
    project_id: str
    q: str | None = None
    limit: int = 30
    offset: int = 0


@dataclass(frozen=True, slots=True)
class WorkspaceSkillListQuery:
    workspace_id: str
    q: str | None = None
    limit: int = 30
    offset: int = 0


def list_project_skills_read_model(db: Session, user: User, query: ProjectSkillListQuery) -> dict[str, Any]:
    ensure_project_access(db, query.workspace_id, query.project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    stmt = select(ProjectSkill).where(
        ProjectSkill.workspace_id == query.workspace_id,
        ProjectSkill.project_id == query.project_id,
        ProjectSkill.is_deleted == False,
    )
    if query.q:
        q = query.q.strip()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    ProjectSkill.name.ilike(like),
                    ProjectSkill.skill_key.ilike(like),
                    ProjectSkill.summary.ilike(like),
                    ProjectSkill.source_locator.ilike(like),
                )
            )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    items = db.execute(stmt.order_by(ProjectSkill.updated_at.desc()).limit(query.limit).offset(query.offset)).scalars().all()
    return {
        "items": [serialize_project_skill(item) for item in items],
        "total": int(total),
        "limit": int(query.limit),
        "offset": int(query.offset),
    }


def load_project_skill_view(db: Session, skill_id: str) -> dict[str, Any] | None:
    skill = db.get(ProjectSkill, skill_id)
    if skill is None or bool(skill.is_deleted):
        return None
    return serialize_project_skill(skill)


def list_workspace_skills_read_model(db: Session, user: User, query: WorkspaceSkillListQuery) -> dict[str, Any]:
    ensure_role(db, query.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    stmt = select(WorkspaceSkill).where(
        WorkspaceSkill.workspace_id == query.workspace_id,
        WorkspaceSkill.is_deleted == False,
    )
    if query.q:
        q = query.q.strip()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    WorkspaceSkill.name.ilike(like),
                    WorkspaceSkill.skill_key.ilike(like),
                    WorkspaceSkill.summary.ilike(like),
                    WorkspaceSkill.source_locator.ilike(like),
                )
            )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    items = db.execute(stmt.order_by(WorkspaceSkill.updated_at.desc()).limit(query.limit).offset(query.offset)).scalars().all()
    return {
        "items": [serialize_workspace_skill(item) for item in items],
        "total": int(total),
        "limit": int(query.limit),
        "offset": int(query.offset),
    }


def load_workspace_skill_view(db: Session, skill_id: str) -> dict[str, Any] | None:
    skill = db.get(WorkspaceSkill, skill_id)
    if skill is None or bool(skill.is_deleted):
        return None
    return serialize_workspace_skill(skill)
