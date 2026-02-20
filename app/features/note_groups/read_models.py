from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from shared.core import NoteGroup, User, ensure_project_access, serialize_note_group


@dataclass(frozen=True, slots=True)
class NoteGroupListQuery:
    workspace_id: str
    project_id: str
    q: str | None = None
    limit: int = 50
    offset: int = 0


def list_note_groups_read_model(db: Session, user: User, query: NoteGroupListQuery) -> dict:
    ensure_project_access(db, query.workspace_id, query.project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    stmt = select(NoteGroup).where(
        NoteGroup.workspace_id == query.workspace_id,
        NoteGroup.project_id == query.project_id,
        NoteGroup.is_deleted == False,
    )
    if query.q:
        q = query.q.strip()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(NoteGroup.name.ilike(like), NoteGroup.description.ilike(like)))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    items = (
        db.execute(
            stmt.order_by(NoteGroup.order_index.asc(), NoteGroup.created_at.asc()).limit(query.limit).offset(query.offset)
        )
        .scalars()
        .all()
    )
    return {
        "items": [serialize_note_group(item) for item in items],
        "total": int(total),
        "limit": int(query.limit),
        "offset": int(query.offset),
    }
