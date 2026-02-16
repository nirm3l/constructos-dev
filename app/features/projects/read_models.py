from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.core import ActivityLog, DEFAULT_STATUSES, Project, ProjectMember, ProjectTagIndex, Task, User, ensure_role, serialize_task, to_iso_utc


def get_project_board_read_model(db: Session, user, project_id: str) -> dict:
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    statuses = json.loads(project.custom_statuses or json.dumps(DEFAULT_STATUSES))
    tasks = db.execute(select(Task).where(Task.project_id == project_id, Task.is_deleted == False, Task.archived == False).order_by(Task.order_index.asc())).scalars().all()
    lanes = {s: [] for s in statuses}
    for task in tasks:
        lanes.setdefault(task.status, [])
        lanes[task.status].append(serialize_task(task))
    return {"project_id": project_id, "statuses": statuses, "lanes": lanes}


def get_project_activity_read_model(db: Session, user, project_id: str) -> list[dict]:
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    logs = db.execute(select(ActivityLog).where(ActivityLog.project_id == project_id).order_by(ActivityLog.created_at.desc()).limit(200)).scalars().all()
    out: list[dict] = []
    for l in logs:
        details = json.loads(l.details or "{}")
        if isinstance(details, dict):
            details.pop("_event_key", None)
        out.append({"id": l.id, "task_id": l.task_id, "action": l.action, "actor_id": l.actor_id, "details": details, "created_at": to_iso_utc(l.created_at)})
    return out


def get_project_tags_read_model(db: Session, user, project_id: str) -> dict:
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    tags = db.execute(
        select(ProjectTagIndex.tag)
        .where(ProjectTagIndex.project_id == project_id)
        .order_by(ProjectTagIndex.tag.asc())
    ).scalars().all()
    return {"project_id": project_id, "tags": tags}


def get_project_members_read_model(db: Session, user, project_id: str) -> dict:
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})

    members = db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.full_name.asc())
    ).all()
    return {
        "project_id": project_id,
        "items": [
            {
                "project_id": pm.project_id,
                "user_id": pm.user_id,
                "role": pm.role,
                "user": {
                    "id": u.id,
                    "username": u.username,
                    "full_name": u.full_name,
                    "user_type": u.user_type,
                },
            }
            for pm, u in members
        ],
        "total": len(members),
    }
