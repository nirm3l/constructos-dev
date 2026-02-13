from __future__ import annotations

import json
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from shared.models import Notification, Project, SavedView, User, Workspace, WorkspaceMember
from shared.serializers import serialize_notification


def bootstrap_payload_read_model(db: Session, user: User) -> dict[str, Any]:
    memberships = db.execute(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)).scalars().all()
    workspace_ids = [m.workspace_id for m in memberships]
    workspaces = db.execute(select(Workspace).where(Workspace.id.in_(workspace_ids), Workspace.is_deleted == False)).scalars().all()
    projects = db.execute(select(Project).where(Project.workspace_id.in_(workspace_ids), Project.is_deleted == False)).scalars().all()
    users = db.execute(select(User)).scalars().all()
    notifications = db.execute(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(20)).scalars().all()
    saved = db.execute(
        select(SavedView).where(
            SavedView.workspace_id.in_(workspace_ids),
            or_(SavedView.user_id == user.id, SavedView.shared == True),
        )
    ).scalars().all()
    return {
        "current_user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "theme": user.theme,
            "timezone": user.timezone,
        },
        "workspaces": [{"id": w.id, "name": w.name, "type": w.type} for w in workspaces],
        "memberships": [{"workspace_id": m.workspace_id, "role": m.role} for m in memberships],
        "projects": [
            {
                "id": p.id,
                "workspace_id": p.workspace_id,
                "name": p.name,
                "description": p.description,
                "status": p.status,
                "custom_statuses": json.loads(p.custom_statuses),
            }
            for p in projects
        ],
        "users": [{"id": u.id, "username": u.username, "full_name": u.full_name} for u in users],
        "notifications": [serialize_notification(n) for n in notifications],
        "saved_views": [
            {
                "id": s.id,
                "workspace_id": s.workspace_id,
                "user_id": s.user_id,
                "name": s.name,
                "shared": s.shared,
                "filters": json.loads(s.filters),
            }
            for s in saved
        ],
    }
