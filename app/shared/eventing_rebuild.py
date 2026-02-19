from __future__ import annotations

import json
import re
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .contracts import EventEnvelope
from features.notifications.domain import (
    EVENT_CREATED as NOTIFICATION_EVENT_CREATED,
    EVENT_MARKED_READ as NOTIFICATION_EVENT_MARKED_READ,
)
from features.projects.domain import (
    EVENT_CREATED as PROJECT_EVENT_CREATED,
    EVENT_DELETED as PROJECT_EVENT_DELETED,
    EVENT_UPDATED as PROJECT_EVENT_UPDATED,
)
from features.tasks.domain import (
    EVENT_ARCHIVED as TASK_EVENT_ARCHIVED,
    EVENT_AUTOMATION_COMPLETED as TASK_EVENT_AUTOMATION_COMPLETED,
    EVENT_AUTOMATION_FAILED as TASK_EVENT_AUTOMATION_FAILED,
    EVENT_AUTOMATION_REQUESTED as TASK_EVENT_AUTOMATION_REQUESTED,
    EVENT_AUTOMATION_STARTED as TASK_EVENT_AUTOMATION_STARTED,
    EVENT_COMMENT_ADDED as TASK_EVENT_COMMENT_ADDED,
    EVENT_COMMENT_DELETED as TASK_EVENT_COMMENT_DELETED,
    EVENT_COMPLETED as TASK_EVENT_COMPLETED,
    EVENT_CREATED as TASK_EVENT_CREATED,
    EVENT_DELETED as TASK_EVENT_DELETED,
    EVENT_MOVED_TO_INBOX as TASK_EVENT_MOVED_TO_INBOX,
    EVENT_REOPENED as TASK_EVENT_REOPENED,
    EVENT_REORDERED as TASK_EVENT_REORDERED,
    EVENT_RESTORED as TASK_EVENT_RESTORED,
    EVENT_SCHEDULE_COMPLETED as TASK_EVENT_SCHEDULE_COMPLETED,
    EVENT_SCHEDULE_CONFIGURED as TASK_EVENT_SCHEDULE_CONFIGURED,
    EVENT_SCHEDULE_DISABLED as TASK_EVENT_SCHEDULE_DISABLED,
    EVENT_SCHEDULE_FAILED as TASK_EVENT_SCHEDULE_FAILED,
    EVENT_SCHEDULE_QUEUED as TASK_EVENT_SCHEDULE_QUEUED,
    EVENT_SCHEDULE_STARTED as TASK_EVENT_SCHEDULE_STARTED,
    EVENT_UPDATED as TASK_EVENT_UPDATED,
    EVENT_WATCH_TOGGLED as TASK_EVENT_WATCH_TOGGLED,
    MUTATION_EVENTS as TASK_MUTATION_EVENTS,
)
from features.notes.domain import (
    EVENT_ARCHIVED as NOTE_EVENT_ARCHIVED,
    EVENT_CREATED as NOTE_EVENT_CREATED,
    EVENT_DELETED as NOTE_EVENT_DELETED,
    EVENT_PINNED as NOTE_EVENT_PINNED,
    EVENT_RESTORED as NOTE_EVENT_RESTORED,
    EVENT_UNPINNED as NOTE_EVENT_UNPINNED,
    EVENT_UPDATED as NOTE_EVENT_UPDATED,
    MUTATION_EVENTS as NOTE_MUTATION_EVENTS,
)
from features.rules.domain import (
    EVENT_CREATED as PROJECT_RULE_EVENT_CREATED,
    EVENT_DELETED as PROJECT_RULE_EVENT_DELETED,
    EVENT_UPDATED as PROJECT_RULE_EVENT_UPDATED,
    MUTATION_EVENTS as PROJECT_RULE_MUTATION_EVENTS,
)
from features.specifications.domain import (
    EVENT_ARCHIVED as SPECIFICATION_EVENT_ARCHIVED,
    EVENT_CREATED as SPECIFICATION_EVENT_CREATED,
    EVENT_DELETED as SPECIFICATION_EVENT_DELETED,
    EVENT_RESTORED as SPECIFICATION_EVENT_RESTORED,
    EVENT_UPDATED as SPECIFICATION_EVENT_UPDATED,
    MUTATION_EVENTS as SPECIFICATION_MUTATION_EVENTS,
)
from features.users.domain import EVENT_PREFERENCES_UPDATED as USER_EVENT_PREFERENCES_UPDATED
from features.views.domain import EVENT_CREATED as SAVED_VIEW_EVENT_CREATED
from .models import (
    ActivityLog,
    AggregateSnapshot,
    Note,
    Notification,
    Project,
    ProjectTagIndex,
    ProjectRule,
    SavedView,
    Specification,
    StoredEvent,
    Task,
    TaskComment,
    TaskWatcher,
    User,
)
from .settings import DEFAULT_STATUSES, SNAPSHOT_EVERY
from .event_upcasters import upcast_event, upcast_snapshot
from .eventing_store import StreamState, get_kurrent_client, kurrent_read_stream, snapshot_stream_id, stream_id, NotFoundError, serialize_snapshot_event

logger = logging.getLogger(__name__)


def _parse_tag_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except Exception:
        return []
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        tag = str(value or "").strip().lower()
        if tag:
            out.append(tag)
    return out


def _recompute_project_tag_index(db: Session, project_id: str | None) -> None:
    if not project_id:
        return
    db.flush()
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        db.execute(delete(ProjectTagIndex).where(ProjectTagIndex.project_id == project_id))
        return

    counts: dict[str, int] = {}

    task_rows = db.execute(
        select(Task.labels).where(
            Task.project_id == project_id,
            Task.is_deleted == False,
            Task.archived == False,
        )
    ).all()
    for (labels_raw,) in task_rows:
        for tag in _parse_tag_list(labels_raw):
            counts[tag] = counts.get(tag, 0) + 1

    note_rows = db.execute(
        select(Note.tags).where(
            Note.project_id == project_id,
            Note.is_deleted == False,
            Note.archived == False,
        )
    ).all()
    for (tags_raw,) in note_rows:
        for tag in _parse_tag_list(tags_raw):
            counts[tag] = counts.get(tag, 0) + 1

    specification_rows = db.execute(
        select(Specification.tags).where(
            Specification.project_id == project_id,
            Specification.is_deleted == False,
            Specification.archived == False,
        )
    ).all()
    for (tags_raw,) in specification_rows:
        for tag in _parse_tag_list(tags_raw):
            counts[tag] = counts.get(tag, 0) + 1

    db.execute(delete(ProjectTagIndex).where(ProjectTagIndex.project_id == project_id))
    for tag, usage_count in sorted(counts.items(), key=lambda item: item[0]):
        db.add(
            ProjectTagIndex(
                workspace_id=project.workspace_id,
                project_id=project_id,
                tag=tag,
                usage_count=usage_count,
            )
        )


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
            return upcast_snapshot(payload, fallback_version=int(payload.get("version", 0)))
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
    raw_payload = json.loads(snap.state or "{}")
    return upcast_snapshot(raw_payload, fallback_version=snap.version)


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
            "specification_id": p.get("specification_id"),
            "title": p["title"],
            "description": p.get("description", ""),
            "status": p.get("status", "To do"),
            "priority": p.get("priority", "Med"),
            "due_date": p.get("due_date"),
            "assignee_id": p.get("assignee_id"),
            "labels": p.get("labels", []),
            "subtasks": p.get("subtasks", []),
            "attachments": p.get("attachments", []),
            "external_refs": p.get("external_refs", []),
            "attachment_refs": p.get("attachment_refs", p.get("attachments", [])),
            "recurring_rule": p.get("recurring_rule"),
            "task_type": p.get("task_type", "manual"),
            "scheduled_instruction": p.get("scheduled_instruction"),
            "scheduled_at_utc": p.get("scheduled_at_utc"),
            "schedule_timezone": p.get("schedule_timezone"),
            "schedule_state": p.get("schedule_state", "idle"),
            "last_schedule_run_at": None,
            "last_schedule_error": None,
            "archived": False,
            "is_deleted": False,
            "completed_at": None,
            "order_index": p.get("order_index", 0),
            "automation_state": "idle",
            "last_agent_run_at": None,
            "last_agent_error": None,
            "last_agent_comment": None,
            "last_requested_instruction": None,
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
    elif event.event_type == TASK_EVENT_AUTOMATION_REQUESTED:
        s["automation_state"] = "queued"
        s["last_agent_error"] = None
        s["last_requested_instruction"] = p.get("instruction")
    elif event.event_type == TASK_EVENT_AUTOMATION_STARTED:
        s["automation_state"] = "running"
        s["last_agent_error"] = None
        s["last_agent_run_at"] = p.get("started_at")
    elif event.event_type == TASK_EVENT_AUTOMATION_COMPLETED:
        s["automation_state"] = "completed"
        s["last_agent_run_at"] = p.get("completed_at")
        s["last_agent_error"] = None
        s["last_agent_comment"] = p.get("summary")
    elif event.event_type == TASK_EVENT_AUTOMATION_FAILED:
        s["automation_state"] = "failed"
        s["last_agent_run_at"] = p.get("failed_at")
        s["last_agent_error"] = p.get("error")
        s["last_agent_comment"] = p.get("summary")
    elif event.event_type == TASK_EVENT_SCHEDULE_CONFIGURED:
        s["task_type"] = "scheduled_instruction"
        s["scheduled_instruction"] = p.get("scheduled_instruction")
        s["scheduled_at_utc"] = p.get("scheduled_at_utc")
        s["schedule_timezone"] = p.get("schedule_timezone")
        s["schedule_state"] = p.get("schedule_state", "idle")
        s["last_schedule_error"] = None
    elif event.event_type == TASK_EVENT_SCHEDULE_QUEUED:
        s["schedule_state"] = "queued"
        s["last_schedule_error"] = None
    elif event.event_type == TASK_EVENT_SCHEDULE_STARTED:
        s["schedule_state"] = "running"
        s["last_schedule_error"] = None
        s["last_schedule_run_at"] = p.get("started_at")
    elif event.event_type == TASK_EVENT_SCHEDULE_COMPLETED:
        s["schedule_state"] = "done"
        s["last_schedule_error"] = None
        s["last_schedule_run_at"] = p.get("completed_at")
    elif event.event_type == TASK_EVENT_SCHEDULE_FAILED:
        s["schedule_state"] = "failed"
        s["last_schedule_error"] = p.get("error")
        s["last_schedule_run_at"] = p.get("failed_at")
    elif event.event_type == TASK_EVENT_SCHEDULE_DISABLED:
        s["task_type"] = "manual"
        s["scheduled_instruction"] = None
        s["scheduled_at_utc"] = None
        s["schedule_timezone"] = None
        s["schedule_state"] = "idle"
        s["last_schedule_error"] = None
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
            "custom_statuses": p.get("custom_statuses", DEFAULT_STATUSES) or DEFAULT_STATUSES,
            "external_refs": p.get("external_refs", []),
            "attachment_refs": p.get("attachment_refs", []),
            "embedding_enabled": bool(p.get("embedding_enabled", False)),
            "embedding_model": p.get("embedding_model"),
            "context_pack_evidence_top_k": p.get("context_pack_evidence_top_k"),
            "is_deleted": False,
        }
    elif event.event_type == PROJECT_EVENT_DELETED:
        s["is_deleted"] = True
    elif event.event_type == PROJECT_EVENT_UPDATED:
        if "name" in p:
            s["name"] = p.get("name")
        if "description" in p:
            s["description"] = p.get("description", "")
        if "custom_statuses" in p:
            statuses = p.get("custom_statuses")
            s["custom_statuses"] = statuses if statuses else DEFAULT_STATUSES
        if "external_refs" in p:
            s["external_refs"] = p.get("external_refs", [])
        if "attachment_refs" in p:
            s["attachment_refs"] = p.get("attachment_refs", [])
        if "embedding_enabled" in p:
            s["embedding_enabled"] = bool(p.get("embedding_enabled", False))
        if "embedding_model" in p:
            s["embedding_model"] = p.get("embedding_model")
        if "context_pack_evidence_top_k" in p:
            s["context_pack_evidence_top_k"] = p.get("context_pack_evidence_top_k")
    return s


def apply_note_event(state: dict[str, Any], event: EventEnvelope) -> dict[str, Any]:
    s = dict(state)
    p = event.payload
    if event.event_type == NOTE_EVENT_CREATED:
        s = {
            "id": event.aggregate_id,
            "workspace_id": p["workspace_id"],
            "project_id": p.get("project_id"),
            "task_id": p.get("task_id"),
            "specification_id": p.get("specification_id"),
            "title": p.get("title", ""),
            "body": p.get("body", ""),
            "tags": p.get("tags", []),
            "external_refs": p.get("external_refs", []),
            "attachment_refs": p.get("attachment_refs", []),
            "pinned": bool(p.get("pinned", False)),
            "archived": bool(p.get("archived", False)),
            "is_deleted": bool(p.get("is_deleted", False)),
            "created_by": p.get("created_by"),
            "updated_by": p.get("updated_by"),
        }
    elif event.event_type == NOTE_EVENT_UPDATED:
        s.update(p)
    elif event.event_type == NOTE_EVENT_ARCHIVED:
        s["archived"] = True
        if "updated_by" in p:
            s["updated_by"] = p.get("updated_by")
    elif event.event_type == NOTE_EVENT_RESTORED:
        s["archived"] = False
        if "updated_by" in p:
            s["updated_by"] = p.get("updated_by")
    elif event.event_type == NOTE_EVENT_PINNED:
        s["pinned"] = True
        if "updated_by" in p:
            s["updated_by"] = p.get("updated_by")
    elif event.event_type == NOTE_EVENT_UNPINNED:
        s["pinned"] = False
        if "updated_by" in p:
            s["updated_by"] = p.get("updated_by")
    elif event.event_type == NOTE_EVENT_DELETED:
        s["is_deleted"] = True
        if "updated_by" in p:
            s["updated_by"] = p.get("updated_by")
    return s


def apply_project_rule_event(state: dict[str, Any], event: EventEnvelope) -> dict[str, Any]:
    s = dict(state)
    p = event.payload
    if event.event_type == PROJECT_RULE_EVENT_CREATED:
        s = {
            "id": event.aggregate_id,
            "workspace_id": p["workspace_id"],
            "project_id": p["project_id"],
            "title": p.get("title", ""),
            "body": p.get("body", ""),
            "created_by": p.get("created_by"),
            "updated_by": p.get("updated_by"),
            "is_deleted": bool(p.get("is_deleted", False)),
        }
    elif event.event_type == PROJECT_RULE_EVENT_UPDATED:
        s.update(p)
    elif event.event_type == PROJECT_RULE_EVENT_DELETED:
        s["is_deleted"] = True
        if "updated_by" in p:
            s["updated_by"] = p.get("updated_by")
    return s


def apply_specification_event(state: dict[str, Any], event: EventEnvelope) -> dict[str, Any]:
    s = dict(state)
    p = event.payload
    if event.event_type == SPECIFICATION_EVENT_CREATED:
        s = {
            "id": event.aggregate_id,
            "workspace_id": p["workspace_id"],
            "project_id": p["project_id"],
            "title": p.get("title", ""),
            "body": p.get("body", ""),
            "status": p.get("status", "Draft"),
            "tags": p.get("tags", []),
            "external_refs": p.get("external_refs", []),
            "attachment_refs": p.get("attachment_refs", []),
            "created_by": p.get("created_by"),
            "updated_by": p.get("updated_by"),
            "archived": bool(p.get("archived", False)),
            "is_deleted": bool(p.get("is_deleted", False)),
        }
    elif event.event_type == SPECIFICATION_EVENT_UPDATED:
        s.update(p)
    elif event.event_type == SPECIFICATION_EVENT_ARCHIVED:
        s["archived"] = True
        s["status"] = "Archived"
        if "updated_by" in p:
            s["updated_by"] = p.get("updated_by")
    elif event.event_type == SPECIFICATION_EVENT_RESTORED:
        s["archived"] = False
        if s.get("status") == "Archived":
            s["status"] = "Ready"
        if "updated_by" in p:
            s["updated_by"] = p.get("updated_by")
    elif event.event_type == SPECIFICATION_EVENT_DELETED:
        s["is_deleted"] = True
        if "updated_by" in p:
            s["updated_by"] = p.get("updated_by")
    return s


def rebuild_state(db: Session, aggregate_type: str, aggregate_id: str) -> tuple[dict[str, Any], int]:
    state, version = load_snapshot(db, aggregate_type, aggregate_id)
    for ev in load_events_after(db, aggregate_type, aggregate_id, version):
        if aggregate_type == "Task":
            state = apply_task_event(state, ev)
        elif aggregate_type == "Project":
            state = apply_project_event(state, ev)
        elif aggregate_type == "Note":
            state = apply_note_event(state, ev)
        elif aggregate_type == "ProjectRule":
            state = apply_project_rule_event(state, ev)
        elif aggregate_type == "Specification":
            state = apply_specification_event(state, ev)
        version = ev.version
    return state, version


def maybe_snapshot(db: Session, aggregate_type: str, aggregate_id: str, version: int):
    if version % SNAPSHOT_EVERY != 0:
        return
    state, cur_version = rebuild_state(db, aggregate_type, aggregate_id)
    client = get_kurrent_client()
    if client is not None:
        try:
            snap_stream = snapshot_stream_id(aggregate_type, aggregate_id)
            try:
                latest = kurrent_read_stream(snap_stream, backwards=True, limit=1)
                expected = StreamState.NO_STREAM if not latest else int(latest[0].stream_position)
            except NotFoundError:
                expected = StreamState.NO_STREAM
            client.append_to_stream(
                stream_name=snap_stream,
                current_version=expected,
                events=[serialize_snapshot_event(aggregate_type, aggregate_id, state, cur_version)],
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("snapshot.append_failed aggregate=%s id=%s version=%s err=%s", aggregate_type, aggregate_id, cur_version, exc)
        return
    db.add(
        AggregateSnapshot(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            version=cur_version,
            state=json.dumps({"snapshot_schema_version": 2, "state": state, "version": cur_version}),
        )
    )


def project_event(db: Session, ev: EventEnvelope):
    p = ev.payload
    m = ev.metadata

    if ev.event_type == PROJECT_EVENT_CREATED:
        project = db.get(Project, ev.aggregate_id)
        if project is None:
            project = Project(id=ev.aggregate_id, workspace_id=p["workspace_id"], name=p["name"])
            db.add(project)
        project.workspace_id = p["workspace_id"]
        project.name = p["name"]
        project.description = p.get("description", "") or ""
        project.status = p.get("status", "Active")
        project.custom_statuses = json.dumps(p.get("custom_statuses", DEFAULT_STATUSES) or DEFAULT_STATUSES)
        project.external_refs = json.dumps(p.get("external_refs", []))
        project.attachment_refs = json.dumps(p.get("attachment_refs", []))
        project.embedding_enabled = bool(p.get("embedding_enabled", False))
        project.embedding_model = p.get("embedding_model")
        project.context_pack_evidence_top_k = p.get("context_pack_evidence_top_k")
    elif ev.event_type == PROJECT_EVENT_DELETED:
        project = db.get(Project, ev.aggregate_id)
        if project:
            project.is_deleted = True
        db.execute(delete(ProjectTagIndex).where(ProjectTagIndex.project_id == ev.aggregate_id))
    elif ev.event_type == PROJECT_EVENT_UPDATED:
        project = db.get(Project, ev.aggregate_id)
        if project:
            if "name" in p:
                project.name = p.get("name") or project.name
            if "description" in p:
                project.description = p.get("description", "") or ""
            if "custom_statuses" in p:
                project.custom_statuses = json.dumps(p.get("custom_statuses", DEFAULT_STATUSES) or DEFAULT_STATUSES)
            if "external_refs" in p:
                project.external_refs = json.dumps(p.get("external_refs", []))
            if "attachment_refs" in p:
                project.attachment_refs = json.dumps(p.get("attachment_refs", []))
            if "embedding_enabled" in p:
                project.embedding_enabled = bool(p.get("embedding_enabled", False))
            if "embedding_model" in p:
                project.embedding_model = p.get("embedding_model")
            if "context_pack_evidence_top_k" in p:
                project.context_pack_evidence_top_k = p.get("context_pack_evidence_top_k")
    elif ev.event_type == NOTE_EVENT_CREATED:
        note = db.get(Note, ev.aggregate_id)
        if note is None:
            note = Note(id=ev.aggregate_id, workspace_id=p["workspace_id"], title=p.get("title", ""))
            db.add(note)
        note.workspace_id = p["workspace_id"]
        note.project_id = p.get("project_id")
        note.task_id = p.get("task_id")
        note.specification_id = p.get("specification_id")
        note.title = p.get("title", "") or ""
        note.body = p.get("body", "") or ""
        note.tags = json.dumps(p.get("tags", []))
        note.external_refs = json.dumps(p.get("external_refs", []))
        note.attachment_refs = json.dumps(p.get("attachment_refs", []))
        note.pinned = bool(p.get("pinned", False))
        note.archived = bool(p.get("archived", False))
        note.is_deleted = bool(p.get("is_deleted", False))
        note.created_by = p.get("created_by") or m.get("actor_id") or ""
        note.updated_by = p.get("updated_by") or m.get("actor_id") or ""
        _recompute_project_tag_index(db, note.project_id)
    elif ev.event_type == PROJECT_RULE_EVENT_CREATED:
        rule = db.get(ProjectRule, ev.aggregate_id)
        if rule is None:
            rule = ProjectRule(id=ev.aggregate_id, workspace_id=p["workspace_id"], project_id=p["project_id"], title=p.get("title", ""))
            db.add(rule)
        rule.workspace_id = p["workspace_id"]
        rule.project_id = p["project_id"]
        rule.title = p.get("title", "") or ""
        rule.body = p.get("body", "") or ""
        rule.created_by = p.get("created_by") or m.get("actor_id") or ""
        rule.updated_by = p.get("updated_by") or m.get("actor_id") or ""
        rule.is_deleted = bool(p.get("is_deleted", False))
    elif ev.event_type == SPECIFICATION_EVENT_CREATED:
        specification = db.get(Specification, ev.aggregate_id)
        if specification is None:
            specification = Specification(
                id=ev.aggregate_id,
                workspace_id=p["workspace_id"],
                project_id=p["project_id"],
                title=p.get("title", ""),
            )
            db.add(specification)
        specification.workspace_id = p["workspace_id"]
        specification.project_id = p["project_id"]
        specification.title = p.get("title", "") or ""
        specification.body = p.get("body", "") or ""
        specification.status = p.get("status", "Draft")
        specification.tags = json.dumps(p.get("tags", []))
        specification.external_refs = json.dumps(p.get("external_refs", []))
        specification.attachment_refs = json.dumps(p.get("attachment_refs", []))
        specification.created_by = p.get("created_by") or m.get("actor_id") or ""
        specification.updated_by = p.get("updated_by") or m.get("actor_id") or ""
        specification.archived = bool(p.get("archived", False))
        specification.is_deleted = bool(p.get("is_deleted", False))
        _recompute_project_tag_index(db, specification.project_id)
    elif ev.event_type == TASK_EVENT_CREATED:
        task = db.get(Task, ev.aggregate_id)
        if task is None:
            task = Task(id=ev.aggregate_id, workspace_id=p["workspace_id"], title=p["title"])
            db.add(task)
        task.workspace_id = p["workspace_id"]
        task.project_id = p.get("project_id")
        task.specification_id = p.get("specification_id")
        task.title = p["title"]
        task.description = p.get("description", "") or ""
        task.status = p.get("status", "To do")
        task.priority = p.get("priority", "Med")
        task.due_date = datetime.fromisoformat(p["due_date"]) if p.get("due_date") else None
        task.assignee_id = p.get("assignee_id")
        task.labels = json.dumps(p.get("labels", []))
        task.subtasks = json.dumps(p.get("subtasks", []))
        task.attachments = json.dumps(p.get("attachments", []))
        task.external_refs = json.dumps(p.get("external_refs", []))
        task.attachment_refs = json.dumps(p.get("attachment_refs", p.get("attachments", [])))
        task.recurring_rule = p.get("recurring_rule")
        task.task_type = p.get("task_type", "manual")
        task.scheduled_instruction = p.get("scheduled_instruction")
        task.scheduled_at_utc = datetime.fromisoformat(p["scheduled_at_utc"]) if p.get("scheduled_at_utc") else None
        task.schedule_timezone = p.get("schedule_timezone")
        task.schedule_state = p.get("schedule_state", "idle")
        task.last_schedule_run_at = None
        task.last_schedule_error = None
        task.order_index = p.get("order_index", 0)
        _recompute_project_tag_index(db, task.project_id)
    elif ev.event_type in NOTE_MUTATION_EVENTS:
        note = db.get(Note, ev.aggregate_id)
        if note:
            old_project_id = note.project_id
            if ev.event_type == NOTE_EVENT_UPDATED:
                for k, v in p.items():
                    if k == "tags" and v is not None:
                        note.tags = json.dumps(v)
                    elif k == "external_refs" and v is not None:
                        note.external_refs = json.dumps(v)
                    elif k == "attachment_refs" and v is not None:
                        note.attachment_refs = json.dumps(v)
                    else:
                        setattr(note, k, v)
            elif ev.event_type == NOTE_EVENT_ARCHIVED:
                note.archived = True
                if p.get("updated_by"):
                    note.updated_by = p["updated_by"]
            elif ev.event_type == NOTE_EVENT_RESTORED:
                note.archived = False
                if p.get("updated_by"):
                    note.updated_by = p["updated_by"]
            elif ev.event_type == NOTE_EVENT_PINNED:
                note.pinned = True
                if p.get("updated_by"):
                    note.updated_by = p["updated_by"]
            elif ev.event_type == NOTE_EVENT_UNPINNED:
                note.pinned = False
                if p.get("updated_by"):
                    note.updated_by = p["updated_by"]
            elif ev.event_type == NOTE_EVENT_DELETED:
                note.is_deleted = True
                if p.get("updated_by"):
                    note.updated_by = p["updated_by"]
            _recompute_project_tag_index(db, old_project_id)
            _recompute_project_tag_index(db, note.project_id)
    elif ev.event_type in PROJECT_RULE_MUTATION_EVENTS:
        rule = db.get(ProjectRule, ev.aggregate_id)
        if rule:
            if ev.event_type == PROJECT_RULE_EVENT_UPDATED:
                for k, v in p.items():
                    setattr(rule, k, v)
            elif ev.event_type == PROJECT_RULE_EVENT_DELETED:
                rule.is_deleted = True
                if p.get("updated_by"):
                    rule.updated_by = p["updated_by"]
    elif ev.event_type in SPECIFICATION_MUTATION_EVENTS:
        specification = db.get(Specification, ev.aggregate_id)
        if specification:
            old_project_id = specification.project_id
            if ev.event_type == SPECIFICATION_EVENT_UPDATED:
                for k, v in p.items():
                    if k == "tags" and v is not None:
                        specification.tags = json.dumps(v)
                    elif k == "external_refs" and v is not None:
                        specification.external_refs = json.dumps(v)
                    elif k == "attachment_refs" and v is not None:
                        specification.attachment_refs = json.dumps(v)
                    else:
                        setattr(specification, k, v)
            elif ev.event_type == SPECIFICATION_EVENT_ARCHIVED:
                specification.archived = True
                specification.status = "Archived"
                if p.get("updated_by"):
                    specification.updated_by = p["updated_by"]
            elif ev.event_type == SPECIFICATION_EVENT_RESTORED:
                specification.archived = False
                if specification.status == "Archived":
                    specification.status = "Ready"
                if p.get("updated_by"):
                    specification.updated_by = p["updated_by"]
            elif ev.event_type == SPECIFICATION_EVENT_DELETED:
                specification.is_deleted = True
                if p.get("updated_by"):
                    specification.updated_by = p["updated_by"]
            _recompute_project_tag_index(db, old_project_id)
            _recompute_project_tag_index(db, specification.project_id)
    elif ev.event_type in TASK_MUTATION_EVENTS:
        task = db.get(Task, ev.aggregate_id)
        if task:
            old_project_id = task.project_id
            if ev.event_type == TASK_EVENT_UPDATED:
                for k, v in p.items():
                    if k in {"labels", "subtasks", "attachments", "external_refs", "attachment_refs"} and v is not None:
                        setattr(task, k, json.dumps(v))
                    elif k == "due_date":
                        task.due_date = datetime.fromisoformat(v) if v else None
                    elif k in {"scheduled_at_utc", "last_schedule_run_at"}:
                        setattr(task, k, datetime.fromisoformat(v) if v else None)
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
            elif ev.event_type == TASK_EVENT_SCHEDULE_CONFIGURED:
                task.task_type = "scheduled_instruction"
                task.scheduled_instruction = p.get("scheduled_instruction")
                task.scheduled_at_utc = datetime.fromisoformat(p["scheduled_at_utc"]) if p.get("scheduled_at_utc") else None
                task.schedule_timezone = p.get("schedule_timezone")
                task.schedule_state = p.get("schedule_state", "idle")
                task.last_schedule_error = None
            elif ev.event_type == TASK_EVENT_SCHEDULE_QUEUED:
                task.schedule_state = "queued"
                task.last_schedule_error = None
            elif ev.event_type == TASK_EVENT_SCHEDULE_STARTED:
                task.schedule_state = "running"
                task.last_schedule_run_at = datetime.fromisoformat(p["started_at"]) if p.get("started_at") else None
                task.last_schedule_error = None
            elif ev.event_type == TASK_EVENT_SCHEDULE_COMPLETED:
                task.schedule_state = "done"
                task.last_schedule_run_at = datetime.fromisoformat(p["completed_at"]) if p.get("completed_at") else None
                task.last_schedule_error = None
            elif ev.event_type == TASK_EVENT_SCHEDULE_FAILED:
                task.schedule_state = "failed"
                task.last_schedule_run_at = datetime.fromisoformat(p["failed_at"]) if p.get("failed_at") else None
                task.last_schedule_error = p.get("error")
            elif ev.event_type == TASK_EVENT_SCHEDULE_DISABLED:
                task.task_type = "manual"
                task.scheduled_instruction = None
                task.scheduled_at_utc = None
                task.schedule_timezone = None
                task.schedule_state = "idle"
                task.last_schedule_error = None
            _recompute_project_tag_index(db, old_project_id)
            _recompute_project_tag_index(db, task.project_id)
    elif ev.event_type == TASK_EVENT_COMMENT_ADDED:
        pending_exists = any(
            isinstance(obj, TaskComment)
            and obj.task_id == p["task_id"]
            and obj.event_version == ev.version
            for obj in db.new
        )
        existing_comment = db.execute(
            select(TaskComment).where(
                TaskComment.task_id == p["task_id"],
                TaskComment.event_version == ev.version,
            )
        ).scalar_one_or_none()
        if existing_comment is None and not pending_exists:
            db.add(TaskComment(task_id=p["task_id"], user_id=p["user_id"], body=p["body"], event_version=ev.version))
        task = db.get(Task, p["task_id"])
        mentions = re.findall(r"@([A-Za-z0-9_\-]+)", p["body"])
        if mentions:
            users = db.execute(select(User).where(User.username.in_(mentions))).scalars().all()
            actor = db.get(User, p["user_id"])
            actor_username = actor.username if actor else "Someone"
            for mentioned in users:
                db.add(
                    Notification(
                        user_id=mentioned.id,
                        workspace_id=task.workspace_id if task else m.get("workspace_id"),
                        project_id=task.project_id if task else m.get("project_id"),
                        task_id=p["task_id"],
                        message=f"{actor_username} mentioned you on task #{p['task_id']}",
                    )
                )
    elif ev.event_type == TASK_EVENT_COMMENT_DELETED:
        comment = db.get(TaskComment, p["comment_id"])
        if comment and comment.task_id == p["task_id"]:
            db.delete(comment)
    elif ev.event_type == TASK_EVENT_WATCH_TOGGLED:
        task_id = p.get("task_id")
        user_id = p.get("user_id")
        if task_id and user_id:
            rows = db.execute(
                select(TaskWatcher)
                .where(TaskWatcher.task_id == task_id, TaskWatcher.user_id == user_id)
                .order_by(TaskWatcher.id.asc())
            ).scalars().all()
            watched_payload = p.get("watched")
            if watched_payload is None:
                # Legacy event shape: toggle.
                if rows:
                    for row in rows:
                        db.delete(row)
                else:
                    db.add(TaskWatcher(task_id=task_id, user_id=user_id))
            elif bool(watched_payload):
                if not rows:
                    db.add(TaskWatcher(task_id=task_id, user_id=user_id))
                else:
                    for row in rows[1:]:
                        db.delete(row)
            else:
                for row in rows:
                    db.delete(row)
    elif ev.event_type == NOTIFICATION_EVENT_MARKED_READ:
        n = db.get(Notification, p["notification_id"])
        if n and n.user_id == p["user_id"]:
            n.is_read = True
    elif ev.event_type == NOTIFICATION_EVENT_CREATED:
        # Idempotent projection: in EventStore mode we can project the same event
        # via write-through append + later catch-up, so inserts must be safe.
        n = db.get(Notification, ev.aggregate_id)
        if n is None:
            n = Notification(
                id=ev.aggregate_id,
                user_id=p["user_id"],
                workspace_id=p.get("workspace_id") or m.get("workspace_id"),
                project_id=p.get("project_id") or m.get("project_id"),
                task_id=p.get("task_id") or m.get("task_id"),
                note_id=p.get("note_id") or m.get("note_id"),
                specification_id=p.get("specification_id") or m.get("specification_id"),
                message=p["message"],
                is_read=False,
            )
            db.add(n)
        else:
            n.user_id = p["user_id"]
            n.workspace_id = p.get("workspace_id") or m.get("workspace_id")
            n.project_id = p.get("project_id") or m.get("project_id")
            n.task_id = p.get("task_id") or m.get("task_id")
            n.note_id = p.get("note_id") or m.get("note_id")
            n.specification_id = p.get("specification_id") or m.get("specification_id")
            n.message = p["message"]
            # Preserve any existing read state; newly created events are unread.
            if n.is_read is None:
                n.is_read = False
    elif ev.event_type == SAVED_VIEW_EVENT_CREATED:
        saved = db.get(SavedView, ev.aggregate_id)
        if saved is None:
            saved = SavedView(
                id=ev.aggregate_id,
                workspace_id=p["workspace_id"],
                project_id=p.get("project_id"),
                user_id=p.get("user_id"),
                name=p["name"],
                shared=p.get("shared", False),
                filters=json.dumps(p.get("filters", {})),
            )
            db.add(saved)
        else:
            saved.workspace_id = p["workspace_id"]
            saved.project_id = p.get("project_id")
            saved.user_id = p.get("user_id")
            saved.name = p["name"]
            saved.shared = p.get("shared", False)
            saved.filters = json.dumps(p.get("filters", {}))
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
        # Ensure projected entities are persisted before writing FK-bound activity rows.
        db.flush()
        project_id = m.get("project_id")
        task_id = m.get("task_id")
        if project_id and db.get(Project, project_id) is None:
            project_id = None
        if task_id and db.get(Task, task_id) is None:
            task_id = None
        event_key = f"{ev.aggregate_type}:{ev.aggregate_id}:{ev.version}:{ev.event_type}"
        details_payload = dict(p)
        details_payload["_event_key"] = event_key
        details_json = json.dumps(details_payload, sort_keys=True)
        existing_activity = db.execute(
            select(ActivityLog.id).where(
                ActivityLog.workspace_id == workspace_id,
                ActivityLog.project_id == project_id,
                ActivityLog.task_id == task_id,
                ActivityLog.actor_id == actor_id,
                ActivityLog.action == ev.event_type,
                ActivityLog.details == details_json,
            )
        ).first()
        if existing_activity:
            return
        db.add(
            ActivityLog(
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=task_id,
                actor_id=actor_id,
                action=ev.event_type,
                details=details_json,
            )
        )
