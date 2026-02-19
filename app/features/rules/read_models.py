from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from shared.core import ProjectRule, User, ensure_project_access, serialize_project_rule


@dataclass(frozen=True, slots=True)
class ProjectRuleListQuery:
    workspace_id: str
    project_id: str
    q: str | None = None
    limit: int = 30
    offset: int = 0


def list_project_rules_read_model(db: Session, user: User, query: ProjectRuleListQuery) -> dict:
    ensure_project_access(db, query.workspace_id, query.project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    stmt = select(ProjectRule).where(
        ProjectRule.workspace_id == query.workspace_id,
        ProjectRule.project_id == query.project_id,
        ProjectRule.is_deleted == False,
    )
    if query.q:
        q = query.q.strip()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(ProjectRule.title.ilike(like), ProjectRule.body.ilike(like)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    items = (
        db.execute(
            stmt.order_by(ProjectRule.updated_at.desc()).limit(query.limit).offset(query.offset)
        )
        .scalars()
        .all()
    )
    return {
        "items": [serialize_project_rule(item) for item in items],
        "total": int(total),
        "limit": int(query.limit),
        "offset": int(query.offset),
    }
