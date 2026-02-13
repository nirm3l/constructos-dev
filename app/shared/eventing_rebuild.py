from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .contracts import EventEnvelope
from features.notifications.domain import (
    EVENT_CREATED as NOTIFICATION_EVENT_CREATED,
    EVENT_MARKED_READ as NOTIFICATION_EVENT_MARKED_READ,
)
from features.projects.domain import (
    EVENT_CREATED as PROJECT_EVENT_CREATED,
    EVENT_DELETED as PROJECT_EVENT_DELETED,
)
from features.tasks.domain import (
    EVENT_ARCHIVED as TASK_EVENT_ARCHIVED,
    EVENT_COMMENT_ADDED as TASK_EVENT_COMMENT_ADDED,
    EVENT_COMPLETED as TASK_EVENT_COMPLETED,
    EVENT_CREATED as TASK_EVENT_CREATED,
    EVENT_DELETED as TASK_EVENT_DELETED,
    EVENT_MOVED_TO_INBOX as TASK_EVENT_MOVED_TO_INBOX,
    EVENT_REOPENED as TASK_EVENT_REOPENED,
    EVENT_REORDERED as TASK_EVENT_REORDERED,
    EVENT_RESTORED as TASK_EVENT_RESTORED,
    EVENT_UPDATED as TASK_EVENT_UPDATED,
    EVENT_WATCH_TOGGLED as TASK_EVENT_WATCH_TOGGLED,
    MUTATION_EVENTS as TASK_MUTATION_EVENTS,
)
from features.users.domain import EVENT_PREFERENCES_UPDATED as USER_EVENT_PREFERENCES_UPDATED
from features.views.domain import EVENT_CREATED as SAVED_VIEW_EVENT_CREATED
from .models import (
    ActivityLog,
    AggregateSnapshot,
    Notification,
    Project,
    SavedView,
    StoredEvent,
    Task,
    TaskComment,
    TaskWatcher,
    User,
)
from .settings import DEFAULT_STATUSES, SNAPSHOT_EVERY
from .event_upcasters import upcast_event
from .eventing_store import get_kurrent_client, kurrent_read_stream, snapshot_stream_id, stream_id, NotFoundError


def load_snapshot(db: Session, aggregate_type: str, aggregate_id: str) -> tuple[dict[str, Any], int]:
    client = get_kurrent_client()
    if client is not None:
        try:
            snaps = kurrent_read_stream(snapshot_stream_id(aggregate_type, aggregate_id), backwards=True, limit=1)
        except NotFoundError:
            return {}, 0
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Kurrent snapshot read failed: {exc}") from exc
        if snaps:
            payload = json.loads((snaps[0].data or b"{}").decode("utf-8"))
            return payload.get("state", {}), int(payload.get("version", 0))
        return {}, 0
    snap = (
        db.execute(
            select(AggregateSnapshot)
            .where(
                AggregateSnapshot.aggregate_type == aggregate_type,
                AggregateSnapshot.aggregate_id == aggregate_id,
            )
            .order_by(AggregateSnapshot.version.desc())
            .limit(1)
        )
        .scalar_one_or_none()
    )
    if not snap:
        return {}, 0
    return json.loads(snap.state or "{}"), snap.version


def load_events_after(db: Session, aggregate_type: str, aggregate_id: str, version: int) -> list[EventEnvelope]:
    client = get_kurrent_client()
    if client is not None:
        try:
            rows = kurrent_read_stream(
                stream_id(aggregate_type, aggregate_id),
                backwards=False,
                from_position=version if version > 0 else None,
            )
        except NotFoundError:
            return []
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Kurrent read failed: {exc}") from exc
        out: list[EventEnvelope] = []
        for event in rows:
            ev_meta = json.loads((event.metadata or b"{}").decode("utf-8"))
            ev_payload = json.loads((event.data or b"{}").decode("utf-8"))
            ev_payload, ev_meta = upcast_event(event.type, ev_payload, ev_meta)
            ev_version = int(event.stream_position) + 1
            if ev_version <= version:
                continue
            out.append(
                EventEnvelope(
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate_id,
                    version=ev_version,
                    event_type=event.type,
                    payload=ev_payload,
                    metadata=ev_meta,
                )
            )
        return out

    rows = (
        db.execute(
            select(StoredEvent)
            .where(
                StoredEvent.aggregate_type == aggregate_type,
                StoredEvent.aggregate_id == aggregate_id,
                StoredEvent.version > version,
            )
            .order_by(StoredEvent.version.asc())
        )
        .scalars()
        .all()
    )
    out: list[EventEnvelope] = []
    for r in rows:
        payload = json.loads(r.payload or "{}")
        metadata = json.loads(r.meta or "{}")
        payload, metadata = upcast_event(r.event_type, payload, metadata)
        out.append(
            EventEnvelope(
                aggregate_type=r.aggregate_type,
                aggregate_id=r.aggregate_id,
                version=r.version,
                event_type=r.event_type,
                payload=payload,
                metadata=metadata,
            )
        )
    return out


def apply_task_event(state: dict[str, Any], event: EventEnvelope) -> dict[str, Any]:
    s = dict(state)
    p = event.payload
    if event.event_type == TASK_EVENT_CREATED:
        s = {
            "id": event.aggregate_id,
            "workspace_id": p["workspace_id"],
            "project_id": p.get("project_id"),
            "title": p["title"],
            "description": p.get("description", ""),
            "status": p.get("status", "To do"),
            "priority": p.get("priority", "Med"),
            "due_date": p.get("due_date"),
            "assignee_id": p.get("assignee_id"),
            "labels": p.get("labels", []),
            "subtasks": p.get("subtasks", []),
            "attachments": p.get("attachments", []),
            "recurring_rule": p.get("recurring_rule"),
            "archived": False,
            "is_deleted": False,
            "completed_at": None,
            "order_index": p.get("order_index", 0),
        }
    elif event.event_type in {TASK_EVENT_UPDATED, TASK_EVENT_REORDERED}:
        s.update(p)
    elif event.event_type == TASK_EVENT_COMPLETED:
        s["status"] = "Done"
        s["completed_at"] = p.get("completed_at")
    elif event.event_type == TASK_EVENT_REOPENED:
        s["status"] = p.get("status", "To do")
        s["completed_at"] = None
    elif event.event_type == TASK_EVENT_ARCHIVED:
        s["archived"] = True
    elif event.event_type == TASK_EVENT_RESTORED:
        s["archived"] = False
    elif event.event_type == TASK_EVENT_DELETED:
        s["is_deleted"] = True
    elif event.event_type == TASK_EVENT_MOVED_TO_INBOX:
        s["project_id"] = None
    return s


def apply_project_event(state: dict[str, Any], event: EventEnvelope) -> dict[str, Any]:
    s = dict(state)
    p = event.payload
    if event.event_type == PROJECT_EVENT_CREATED:
        s = {
            "id": event.aggregate_id,
            "workspace_id": p["workspace_id"],
            "name": p["name"],
            "description": p.get("description", ""),
            "status": p.get("status", "Active"),
            "custom_statuses": p.get("custom_statuses", DEFAULT_STATUSES),
            "is_deleted": False,
        }
    elif event.event_type == PROJECT_EVENT_DELETED:
        s["is_deleted"] = True
    return s


def rebuild_state(db: Session, aggregate_type: str, aggregate_id: str) -> tuple[dict[str, Any], int]:
    state, version = load_snapshot(db, aggregate_type, aggregate_id)
    for ev in load_events_after(db, aggregate_type, aggregate_id, version):
        if aggregate_type == "Task":
            state = apply_task_event(state, ev)
        elif aggregate_type == "Project":
            state = apply_project_event(state, ev)
        version = ev.version
    return state, version


def maybe_snapshot(db: Session, aggregate_type: str, aggregate_id: str, version: int):
    if version % SNAPSHOT_EVERY != 0:
        return
    if get_kurrent_client() is not None:
        return
    state, cur_version = rebuild_state(db, aggregate_type, aggregate_id)
    db.add(
        AggregateSnapshot(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            version=cur_version,
            state=json.dumps(state),
        )
    )


def project_event(db: Session, ev: EventEnvelope):
    p = ev.payload
    m = ev.metadata

    if ev.event_type == PROJECT_EVENT_CREATED:
        db.add(
            Project(
                id=ev.aggregate_id,
                workspace_id=p["workspace_id"],
                name=p["name"],
                description=p.get("description", ""),
                status=p.get("status", "Active"),
                custom_statuses=json.dumps(p.get("custom_statuses", DEFAULT_STATUSES)),
            )
        )
    elif ev.event_type == PROJECT_EVENT_DELETED:
        project = db.get(Project, ev.aggregate_id)
        if project:
            project.is_deleted = True
    elif ev.event_type == TASK_EVENT_CREATED:
        db.add(
            Task(
                id=ev.aggregate_id,
                workspace_id=p["workspace_id"],
                project_id=p.get("project_id"),
                title=p["title"],
                description=p.get("description", ""),
                status=p.get("status", "To do"),
                priority=p.get("priority", "Med"),
                due_date=datetime.fromisoformat(p["due_date"]) if p.get("due_date") else None,
                assignee_id=p.get("assignee_id"),
                labels=json.dumps(p.get("labels", [])),
                subtasks=json.dumps(p.get("subtasks", [])),
                attachments=json.dumps(p.get("attachments", [])),
                recurring_rule=p.get("recurring_rule"),
                order_index=p.get("order_index", 0),
            )
        )
    elif ev.event_type in TASK_MUTATION_EVENTS:
        task = db.get(Task, ev.aggregate_id)
        if task:
            if ev.event_type == TASK_EVENT_UPDATED:
                for k, v in p.items():
                    if k in {"labels", "subtasks", "attachments"} and v is not None:
                        setattr(task, k, json.dumps(v))
                    elif k == "due_date":
                        task.due_date = datetime.fromisoformat(v) if v else None
                    else:
                        setattr(task, k, v)
                if p.get("status") == "Done" and not task.completed_at:
                    task.completed_at = datetime.now(timezone.utc)
                elif p.get("status") and p.get("status") != "Done":
                    task.completed_at = None
            elif ev.event_type == TASK_EVENT_REORDERED:
                if "order_index" in p:
                    task.order_index = p["order_index"]
                if p.get("status"):
                    task.status = p["status"]
                    if p["status"] != "Done":
                        task.completed_at = None
            elif ev.event_type == TASK_EVENT_COMPLETED:
                task.status = "Done"
                task.completed_at = datetime.fromisoformat(p["completed_at"])
            elif ev.event_type == TASK_EVENT_REOPENED:
                task.status = p.get("status", "To do")
                task.completed_at = None
            elif ev.event_type == TASK_EVENT_ARCHIVED:
                task.archived = True
            elif ev.event_type == TASK_EVENT_RESTORED:
                task.archived = False
            elif ev.event_type == TASK_EVENT_DELETED:
                task.is_deleted = True
            elif ev.event_type == TASK_EVENT_MOVED_TO_INBOX:
                task.project_id = None
    elif ev.event_type == TASK_EVENT_COMMENT_ADDED:
        db.add(TaskComment(task_id=p["task_id"], user_id=p["user_id"], body=p["body"]))
        mentions = re.findall(r"@([A-Za-z0-9_\-]+)", p["body"])
        if mentions:
            users = db.execute(select(User).where(User.username.in_(mentions))).scalars().all()
            actor = db.get(User, p["user_id"])
            actor_username = actor.username if actor else "Someone"
            for mentioned in users:
                db.add(Notification(user_id=mentioned.id, message=f"{actor_username} mentioned you on task #{p['task_id']}"))
    elif ev.event_type == TASK_EVENT_WATCH_TOGGLED:
        existing = db.execute(
            select(TaskWatcher).where(
                TaskWatcher.task_id == p["task_id"],
                TaskWatcher.user_id == p["user_id"],
            )
        ).scalar_one_or_none()
        if existing:
            db.delete(existing)
        else:
            db.add(TaskWatcher(task_id=p["task_id"], user_id=p["user_id"]))
    elif ev.event_type == NOTIFICATION_EVENT_MARKED_READ:
        n = db.get(Notification, p["notification_id"])
        if n and n.user_id == p["user_id"]:
            n.is_read = True
    elif ev.event_type == NOTIFICATION_EVENT_CREATED:
        db.add(Notification(id=ev.aggregate_id, user_id=p["user_id"], message=p["message"], is_read=False))
    elif ev.event_type == SAVED_VIEW_EVENT_CREATED:
        db.add(
            SavedView(
                id=ev.aggregate_id,
                workspace_id=p["workspace_id"],
                user_id=p.get("user_id"),
                name=p["name"],
                shared=p.get("shared", False),
                filters=json.dumps(p.get("filters", {})),
            )
        )
    elif ev.event_type == USER_EVENT_PREFERENCES_UPDATED:
        user = db.get(User, ev.aggregate_id)
        if user:
            if "theme" in p and p["theme"] in {"light", "dark"}:
                user.theme = p["theme"]
            if "timezone" in p and p["timezone"]:
                user.timezone = p["timezone"]
            if "notifications_enabled" in p:
                user.notifications_enabled = bool(p["notifications_enabled"])

    workspace_id = m.get("workspace_id")
    actor_id = m.get("actor_id")
    if workspace_id and actor_id:
        db.add(
            ActivityLog(
                workspace_id=workspace_id,
                project_id=m.get("project_id"),
                task_id=m.get("task_id"),
                actor_id=actor_id,
                action=ev.event_type,
                details=json.dumps(p),
            )
        )
