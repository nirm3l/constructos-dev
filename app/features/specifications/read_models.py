from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from shared.core import Specification, User, ensure_project_access, serialize_specification


@dataclass(frozen=True, slots=True)
class SpecificationListQuery:
    workspace_id: str
    project_id: str
    q: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    archived: bool = False
    limit: int = 30
    offset: int = 0


def list_specifications_read_model(db: Session, user: User, query: SpecificationListQuery) -> dict:
    ensure_project_access(db, query.workspace_id, query.project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    stmt = select(Specification).where(
        Specification.workspace_id == query.workspace_id,
        Specification.project_id == query.project_id,
        Specification.is_deleted == False,
        Specification.archived == query.archived,
    )
    if query.q:
        q = query.q.strip()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(Specification.title.ilike(like), Specification.body.ilike(like)))
    if query.status:
        stmt = stmt.where(Specification.status == query.status)
    if query.tags:
        tag_filters = [Specification.tags.ilike(f'%"{tag}"%') for tag in query.tags]
        if tag_filters:
            stmt = stmt.where(or_(*tag_filters))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    items = db.execute(stmt.order_by(Specification.updated_at.desc()).limit(query.limit).offset(query.offset)).scalars().all()
    return {
        "items": [serialize_specification(item) for item in items],
        "total": int(total),
        "limit": int(query.limit),
        "offset": int(query.offset),
    }
