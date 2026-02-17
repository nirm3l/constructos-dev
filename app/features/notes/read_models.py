from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from shared.core import Note, User, ensure_role, serialize_note


@dataclass(frozen=True, slots=True)
class NoteListQuery:
    workspace_id: str
    project_id: str
    task_id: str | None = None
    specification_id: str | None = None
    q: str | None = None
    tags: list[str] | None = None
    archived: bool = False
    pinned: bool | None = None
    limit: int = 30
    offset: int = 0


def list_notes_read_model(db: Session, user: User, query: NoteListQuery) -> dict:
    ensure_role(db, query.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    stmt = select(Note).where(
        Note.workspace_id == query.workspace_id,
        Note.project_id == query.project_id,
        Note.is_deleted == False,
    )
    if query.task_id:
        stmt = stmt.where(Note.task_id == query.task_id)
    if query.specification_id is not None:
        stmt = stmt.where(Note.specification_id == query.specification_id)
    if query.archived:
        stmt = stmt.where(Note.archived == True)
    else:
        stmt = stmt.where(Note.archived == False)
    if query.pinned is True:
        stmt = stmt.where(Note.pinned == True)
    elif query.pinned is False:
        stmt = stmt.where(Note.pinned == False)
    if query.q:
        q = query.q.strip()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(Note.title.ilike(like), Note.body.ilike(like)))
    if query.tags:
        tag_filters = [Note.tags.ilike(f'%"{tag}"%') for tag in query.tags]
        if tag_filters:
            stmt = stmt.where(or_(*tag_filters))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    items = (
        db.execute(
            stmt.order_by(Note.pinned.desc(), Note.updated_at.desc())
            .limit(query.limit)
            .offset(query.offset)
        )
        .scalars()
        .all()
    )
    return {
        "items": [serialize_note(n) for n in items],
        "total": int(total),
        "limit": int(query.limit),
        "offset": int(query.offset),
        # Debug hint for UI; safe to remove later.
        "filters": json.loads(
            json.dumps(
                {
                    "workspace_id": query.workspace_id,
                    "project_id": query.project_id,
                    "task_id": query.task_id,
                    "specification_id": query.specification_id,
                    "q": query.q,
                    "archived": query.archived,
                    "pinned": query.pinned,
                }
            )
        ),
    }
