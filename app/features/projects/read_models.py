from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from shared.core import (
    ActivityLog,
    DEFAULT_STATUSES,
    Project,
    ProjectMember,
    ProjectTagIndex,
    Task,
    User,
    ensure_project_access,
    serialize_task,
    to_iso_utc,
    rebuild_state,
)
from shared.task_automation import normalize_execution_triggers


def get_project_board_read_model(db: Session, user, project_id: str, tags: list[str] | None = None) -> dict:
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    ensure_project_access(db, project.workspace_id, project.id, user.id, {"Owner", "Admin", "Member", "Guest"})
    statuses = json.loads(project.custom_statuses or json.dumps(DEFAULT_STATUSES))
    stmt = select(Task).where(
        Task.project_id == project_id,
        Task.is_deleted == False,
        Task.archived == False,
    )
    if tags:
        tag_filters = [Task.labels.ilike(f'%"{tag}"%') for tag in tags]
        if tag_filters:
            stmt = stmt.where(or_(*tag_filters))
    tasks = db.execute(stmt.order_by(Task.order_index.asc())).scalars().all()
    automation_state_by_task_id: dict[str, str] = {}
    for task in tasks:
        has_automation = bool(
            str(task.instruction or task.scheduled_instruction or "").strip()
            or normalize_execution_triggers(task.execution_triggers)
        )
        if not has_automation:
            continue
        try:
            state, _ = rebuild_state(db, "Task", task.id)
            automation_state_by_task_id[task.id] = str(state.get("automation_state") or "idle")
        except Exception:
            automation_state_by_task_id[task.id] = "idle"
    lanes = {s: [] for s in statuses}
    for task in tasks:
        lanes.setdefault(task.status, [])
        lanes[task.status].append(
            serialize_task(
                task,
                automation_state=automation_state_by_task_id.get(task.id, "idle"),
            )
        )
    return {"project_id": project_id, "statuses": statuses, "lanes": lanes}


def get_project_activity_read_model(db: Session, user, project_id: str) -> list[dict]:
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    ensure_project_access(db, project.workspace_id, project.id, user.id, {"Owner", "Admin", "Member", "Guest"})
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
    ensure_project_access(db, project.workspace_id, project.id, user.id, {"Owner", "Admin", "Member", "Guest"})
    rows = db.execute(
        select(ProjectTagIndex.tag, ProjectTagIndex.usage_count)
        .where(ProjectTagIndex.project_id == project_id)
        .order_by(ProjectTagIndex.usage_count.desc(), ProjectTagIndex.tag.asc())
    ).all()
    tag_stats = [{"tag": str(tag), "usage_count": int(usage_count or 0)} for tag, usage_count in rows]
    tags = [item["tag"] for item in tag_stats]
    return {"project_id": project_id, "tags": tags, "tag_stats": tag_stats}


def get_project_members_read_model(db: Session, user, project_id: str) -> dict:
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    ensure_project_access(db, project.workspace_id, project.id, user.id, {"Owner", "Admin", "Member", "Guest"})

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
