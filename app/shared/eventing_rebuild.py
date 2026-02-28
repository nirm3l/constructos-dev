from __future__ import annotations

import hashlib
import json
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
    EVENT_MEMBER_REMOVED as PROJECT_EVENT_MEMBER_REMOVED,
    EVENT_MEMBER_UPSERTED as PROJECT_EVENT_MEMBER_UPSERTED,
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
from features.note_groups.domain import (
    EVENT_CREATED as NOTE_GROUP_EVENT_CREATED,
    EVENT_DELETED as NOTE_GROUP_EVENT_DELETED,
    EVENT_REORDERED as NOTE_GROUP_EVENT_REORDERED,
    EVENT_UPDATED as NOTE_GROUP_EVENT_UPDATED,
    MUTATION_EVENTS as NOTE_GROUP_MUTATION_EVENTS,
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
from features.task_groups.domain import (
    EVENT_CREATED as TASK_GROUP_EVENT_CREATED,
    EVENT_DELETED as TASK_GROUP_EVENT_DELETED,
    EVENT_REORDERED as TASK_GROUP_EVENT_REORDERED,
    EVENT_UPDATED as TASK_GROUP_EVENT_UPDATED,
    MUTATION_EVENTS as TASK_GROUP_MUTATION_EVENTS,
)
from features.project_templates.domain import (
    EVENT_BOUND as PROJECT_TEMPLATE_EVENT_BOUND,
)
from features.chat.domain import (
    EVENT_ARCHIVED as CHAT_SESSION_EVENT_ARCHIVED,
    EVENT_ASSISTANT_MESSAGE_APPENDED as CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_APPENDED,
    EVENT_ASSISTANT_MESSAGE_UPDATED as CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_UPDATED,
    EVENT_ATTACHMENT_LINKED as CHAT_SESSION_EVENT_ATTACHMENT_LINKED,
    EVENT_CONTEXT_UPDATED as CHAT_SESSION_EVENT_CONTEXT_UPDATED,
    EVENT_MESSAGE_DELETED as CHAT_SESSION_EVENT_MESSAGE_DELETED,
    EVENT_RENAMED as CHAT_SESSION_EVENT_RENAMED,
    EVENT_RESOURCE_LINKED as CHAT_SESSION_EVENT_RESOURCE_LINKED,
    EVENT_STARTED as CHAT_SESSION_EVENT_STARTED,
    EVENT_USER_MESSAGE_APPENDED as CHAT_SESSION_EVENT_USER_MESSAGE_APPENDED,
)
from features.users.domain import (
    EVENT_CREATED as USER_EVENT_CREATED,
    EVENT_DEACTIVATED as USER_EVENT_DEACTIVATED,
    EVENT_PASSWORD_CHANGED as USER_EVENT_PASSWORD_CHANGED,
    EVENT_PASSWORD_RESET as USER_EVENT_PASSWORD_RESET,
    EVENT_PREFERENCES_UPDATED as USER_EVENT_PREFERENCES_UPDATED,
    EVENT_WORKSPACE_ROLE_SET as USER_EVENT_WORKSPACE_ROLE_SET,
)
from features.views.domain import EVENT_CREATED as SAVED_VIEW_EVENT_CREATED
from .models import (
    ActivityLog,
    AggregateSnapshot,
    AuthSession,
    ChatAttachment,
    ChatMessage,
    ChatMessageResourceLink,
    ChatSession,
    Note,
    NoteGroup,
    Notification,
    Project,
    ProjectTemplateBinding,
    ProjectMember,
    ProjectTagIndex,
    ProjectRule,
    SavedView,
    Specification,
    StoredEvent,
    Task,
    TaskComment,
    TaskGroup,
    TaskWatcher,
    User,
    WorkspaceMember,
)
from .settings import DEFAULT_STATUSES, SNAPSHOT_EVERY
from .typed_notifications import (
    DEFAULT_NOTIFICATION_SEVERITY,
    DEFAULT_NOTIFICATION_TYPE,
    dumps_payload_json,
    normalize_dedupe_key,
    normalize_notification_type,
    normalize_severity,
)
from .task_automation import (
    TRIGGER_KIND_SCHEDULE,
    build_legacy_schedule_trigger,
    derive_legacy_schedule_fields,
    normalize_execution_triggers,
)
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


def _normalize_task_row_automation_fields(task: Task) -> None:
    instruction = str(task.instruction or task.scheduled_instruction or "").strip() or None
    execution_triggers = normalize_execution_triggers(task.execution_triggers)
    if str(task.task_type or "").strip().lower() == "manual":
        execution_triggers = [
            trigger
            for trigger in execution_triggers
            if str(trigger.get("kind") or "") != TRIGGER_KIND_SCHEDULE
        ]
    if not execution_triggers:
        legacy_trigger = build_legacy_schedule_trigger(
            scheduled_at_utc=task.scheduled_at_utc.isoformat() if task.scheduled_at_utc else None,
            schedule_timezone=task.schedule_timezone,
            recurring_rule=task.recurring_rule,
        )
        if legacy_trigger is not None:
            execution_triggers = [legacy_trigger]
    legacy = derive_legacy_schedule_fields(
        instruction=instruction,
        execution_triggers=execution_triggers,
    )
    task.instruction = instruction
    task.execution_triggers = json.dumps(execution_triggers)
    task.task_type = str(legacy.get("task_type") or "manual")
    task.scheduled_instruction = legacy.get("scheduled_instruction")
    raw_scheduled_at = legacy.get("scheduled_at_utc")
    task.scheduled_at_utc = datetime.fromisoformat(raw_scheduled_at) if raw_scheduled_at else None
    task.schedule_timezone = legacy.get("schedule_timezone")
    task.recurring_rule = legacy.get("recurring_rule")


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
    def _normalize_task_automation_state(payload: dict[str, Any]) -> dict[str, Any]:
        s_local = dict(payload)
        try:
            pending_requests = int(s_local.get("automation_pending_requests") or 0)
        except Exception:
            pending_requests = 0
        s_local["automation_pending_requests"] = max(0, pending_requests)
        s_local.setdefault("last_requested_instruction", None)
        s_local.setdefault("last_requested_source", None)
        s_local.setdefault("last_requested_trigger_task_id", None)
        s_local.setdefault("last_requested_from_status", None)
        s_local.setdefault("last_requested_to_status", None)
        s_local.setdefault("last_requested_triggered_at", None)
        instruction = str(s_local.get("instruction") or s_local.get("scheduled_instruction") or "").strip() or None
        execution_triggers = normalize_execution_triggers(s_local.get("execution_triggers"))
        if str(s_local.get("task_type") or "").strip().lower() == "manual":
            execution_triggers = [
                trigger
                for trigger in execution_triggers
                if str(trigger.get("kind") or "") != TRIGGER_KIND_SCHEDULE
            ]
        if not execution_triggers:
            legacy_trigger = build_legacy_schedule_trigger(
                scheduled_at_utc=s_local.get("scheduled_at_utc"),
                schedule_timezone=s_local.get("schedule_timezone"),
                recurring_rule=s_local.get("recurring_rule"),
            )
            if legacy_trigger is not None:
                execution_triggers = [legacy_trigger]
        legacy = derive_legacy_schedule_fields(
            instruction=instruction,
            execution_triggers=execution_triggers,
        )
        s_local["instruction"] = instruction
        s_local["execution_triggers"] = execution_triggers
        s_local["task_type"] = legacy.get("task_type") or "manual"
        s_local["scheduled_instruction"] = legacy.get("scheduled_instruction")
        s_local["scheduled_at_utc"] = legacy.get("scheduled_at_utc")
        s_local["schedule_timezone"] = legacy.get("schedule_timezone")
        s_local["recurring_rule"] = legacy.get("recurring_rule")
        return s_local

    s = dict(state)
    p = event.payload
    if event.event_type == TASK_EVENT_CREATED:
        instruction = str(p.get("instruction") or p.get("scheduled_instruction") or "").strip() or None
        execution_triggers = normalize_execution_triggers(p.get("execution_triggers"))
        if not execution_triggers:
            legacy_trigger = build_legacy_schedule_trigger(
                scheduled_at_utc=p.get("scheduled_at_utc"),
                schedule_timezone=p.get("schedule_timezone"),
                recurring_rule=p.get("recurring_rule"),
            )
            if legacy_trigger is not None:
                execution_triggers = [legacy_trigger]
        legacy = derive_legacy_schedule_fields(instruction=instruction, execution_triggers=execution_triggers)
        s = {
            "id": event.aggregate_id,
            "workspace_id": p["workspace_id"],
            "project_id": p.get("project_id"),
            "task_group_id": p.get("task_group_id"),
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
            "instruction": instruction,
            "execution_triggers": execution_triggers,
            "recurring_rule": legacy.get("recurring_rule"),
            "task_type": legacy.get("task_type", "manual"),
            "scheduled_instruction": legacy.get("scheduled_instruction"),
            "scheduled_at_utc": legacy.get("scheduled_at_utc"),
            "schedule_timezone": legacy.get("schedule_timezone"),
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
            "last_requested_source": None,
            "last_requested_trigger_task_id": None,
            "last_requested_from_status": None,
            "last_requested_to_status": None,
            "last_requested_triggered_at": None,
            "automation_pending_requests": 0,
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
        s["task_group_id"] = None
    elif event.event_type == TASK_EVENT_AUTOMATION_REQUESTED:
        s["automation_state"] = "queued"
        s["last_agent_error"] = None
        s["last_requested_instruction"] = p.get("instruction")
        s["last_requested_source"] = p.get("source")
        s["last_requested_trigger_task_id"] = p.get("trigger_task_id")
        s["last_requested_from_status"] = p.get("from_status")
        s["last_requested_to_status"] = p.get("to_status")
        s["last_requested_triggered_at"] = p.get("triggered_at")
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
    return _normalize_task_automation_state(s)


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
            "chat_index_mode": str(p.get("chat_index_mode") or "OFF"),
            "chat_attachment_ingestion_mode": str(
                p.get("chat_attachment_ingestion_mode") or "METADATA_ONLY"
            ),
            "event_storming_enabled": bool(p.get("event_storming_enabled", True)),
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
        if "chat_index_mode" in p:
            s["chat_index_mode"] = str(p.get("chat_index_mode") or "OFF")
        if "chat_attachment_ingestion_mode" in p:
            s["chat_attachment_ingestion_mode"] = str(
                p.get("chat_attachment_ingestion_mode") or "METADATA_ONLY"
            )
        if "event_storming_enabled" in p:
            s["event_storming_enabled"] = bool(p.get("event_storming_enabled", True))
    return s


def apply_note_event(state: dict[str, Any], event: EventEnvelope) -> dict[str, Any]:
    s = dict(state)
    p = event.payload
    if event.event_type == NOTE_EVENT_CREATED:
        s = {
            "id": event.aggregate_id,
            "workspace_id": p["workspace_id"],
            "project_id": p.get("project_id"),
            "note_group_id": p.get("note_group_id"),
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


def apply_task_group_event(state: dict[str, Any], event: EventEnvelope) -> dict[str, Any]:
    s = dict(state)
    p = event.payload
    if event.event_type == TASK_GROUP_EVENT_CREATED:
        s = {
            "id": event.aggregate_id,
            "workspace_id": p["workspace_id"],
            "project_id": p["project_id"],
            "name": p.get("name", ""),
            "description": p.get("description", ""),
            "color": p.get("color"),
            "order_index": int(p.get("order_index", 0)),
            "is_deleted": bool(p.get("is_deleted", False)),
        }
    elif event.event_type == TASK_GROUP_EVENT_UPDATED:
        s.update(p)
    elif event.event_type == TASK_GROUP_EVENT_REORDERED:
        if "order_index" in p:
            s["order_index"] = int(p.get("order_index") or 0)
    elif event.event_type == TASK_GROUP_EVENT_DELETED:
        s["is_deleted"] = True
    return s


def apply_note_group_event(state: dict[str, Any], event: EventEnvelope) -> dict[str, Any]:
    s = dict(state)
    p = event.payload
    if event.event_type == NOTE_GROUP_EVENT_CREATED:
        s = {
            "id": event.aggregate_id,
            "workspace_id": p["workspace_id"],
            "project_id": p["project_id"],
            "name": p.get("name", ""),
            "description": p.get("description", ""),
            "color": p.get("color"),
            "order_index": int(p.get("order_index", 0)),
            "is_deleted": bool(p.get("is_deleted", False)),
        }
    elif event.event_type == NOTE_GROUP_EVENT_UPDATED:
        s.update(p)
    elif event.event_type == NOTE_GROUP_EVENT_REORDERED:
        if "order_index" in p:
            s["order_index"] = int(p.get("order_index") or 0)
    elif event.event_type == NOTE_GROUP_EVENT_DELETED:
        s["is_deleted"] = True
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


def _parse_datetime_or_none(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text_value = str(value).strip()
    if not text_value:
        return None
    try:
        return datetime.fromisoformat(text_value)
    except ValueError:
        return None


def _normalize_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _normalize_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _placeholder_chat_message_order_index(message_id: str) -> int:
    digest = hashlib.sha1(str(message_id or "").encode("utf-8")).hexdigest()
    # Keep placeholder order indices negative so normal chat order remains positive.
    return -((int(digest[:8], 16) % 1_000_000_000) + 1)


def _ensure_chat_message_placeholder(
    db: Session,
    *,
    aggregate_id: str,
    message_id: str,
    workspace_id: str,
    project_id: str | None,
    actor_id: str,
    session_key: str | None = None,
) -> ChatMessage:
    existing = db.get(ChatMessage, message_id)
    if existing is not None:
        return existing

    session = db.get(ChatSession, aggregate_id)
    if session is None:
        session = ChatSession(
            id=aggregate_id,
            workspace_id=workspace_id,
            project_id=project_id,
            session_key=str(session_key or aggregate_id),
            title="Session",
            created_by=str(actor_id or ""),
        )
        db.add(session)
    else:
        if not session.workspace_id and workspace_id:
            session.workspace_id = workspace_id
        if session.project_id is None and project_id is not None:
            session.project_id = project_id
        if not session.session_key:
            session.session_key = str(session_key or aggregate_id)
        if not session.created_by and actor_id:
            session.created_by = str(actor_id)

    placeholder = ChatMessage(
        id=message_id,
        workspace_id=session.workspace_id or workspace_id,
        project_id=session.project_id if session.project_id is not None else project_id,
        session_id=session.id,
        role="user",
        content="",
        order_index=_placeholder_chat_message_order_index(message_id),
        attachment_refs="[]",
        usage_json="{}",
        is_deleted=False,
        turn_created_at=None,
    )
    db.add(placeholder)
    return placeholder


def apply_chat_session_event(state: dict[str, Any], event: EventEnvelope) -> dict[str, Any]:
    s = dict(state)
    p = event.payload or {}

    if event.event_type == CHAT_SESSION_EVENT_STARTED:
        s = {
            "id": event.aggregate_id,
            "workspace_id": p.get("workspace_id"),
            "project_id": p.get("project_id"),
            "session_key": p.get("session_key", event.aggregate_id),
            "title": p.get("title", "Session"),
            "created_by": p.get("created_by"),
            "is_archived": bool(p.get("is_archived", False)),
            "codex_session_id": p.get("codex_session_id"),
            "mcp_servers": _normalize_json_list(p.get("mcp_servers")),
            "session_attachment_refs": _normalize_json_list(p.get("session_attachment_refs")),
            "usage": _normalize_json_dict(p.get("usage")),
            "last_message_at": p.get("last_message_at"),
            "last_message_preview": p.get("last_message_preview", ""),
            "last_task_event_at": p.get("last_task_event_at"),
            "next_message_index": int(p.get("next_message_index", 0) or 0),
        }
        return s

    if event.event_type == CHAT_SESSION_EVENT_RENAMED:
        s["title"] = str(p.get("title") or s.get("title") or "Session")
        return s

    if event.event_type == CHAT_SESSION_EVENT_ARCHIVED:
        s["is_archived"] = True
        return s

    if event.event_type == CHAT_SESSION_EVENT_CONTEXT_UPDATED:
        if "project_id" in p:
            s["project_id"] = p.get("project_id")
        if "mcp_servers" in p and p.get("mcp_servers") is not None:
            s["mcp_servers"] = _normalize_json_list(p.get("mcp_servers"))
        if "session_attachment_refs" in p and p.get("session_attachment_refs") is not None:
            s["session_attachment_refs"] = _normalize_json_list(p.get("session_attachment_refs"))
        if "codex_session_id" in p:
            s["codex_session_id"] = p.get("codex_session_id")
        if "usage" in p:
            s["usage"] = _normalize_json_dict(p.get("usage"))
        if "last_task_event_at" in p:
            s["last_task_event_at"] = p.get("last_task_event_at")
        return s

    if event.event_type in {CHAT_SESSION_EVENT_USER_MESSAGE_APPENDED, CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_APPENDED}:
        order_index = int(p.get("order_index") or 0)
        if order_index > int(s.get("next_message_index") or 0):
            s["next_message_index"] = order_index
        s["last_message_preview"] = str(p.get("content") or "")[:240]
        s["last_message_at"] = p.get("created_at")
        if event.event_type == CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_APPENDED:
            if "codex_session_id" in p:
                s["codex_session_id"] = p.get("codex_session_id")
            if "usage" in p:
                s["usage"] = _normalize_json_dict(p.get("usage"))
        return s

    if event.event_type == CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_UPDATED:
        s["last_message_preview"] = str(p.get("content") or "")[:240]
        if "codex_session_id" in p:
            s["codex_session_id"] = p.get("codex_session_id")
        if "usage" in p:
            s["usage"] = _normalize_json_dict(p.get("usage"))
        return s

    if event.event_type in {
        CHAT_SESSION_EVENT_MESSAGE_DELETED,
        CHAT_SESSION_EVENT_ATTACHMENT_LINKED,
        CHAT_SESSION_EVENT_RESOURCE_LINKED,
    }:
        return s

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
        elif aggregate_type == "TaskGroup":
            state = apply_task_group_event(state, ev)
        elif aggregate_type == "NoteGroup":
            state = apply_note_group_event(state, ev)
        elif aggregate_type == "ProjectRule":
            state = apply_project_rule_event(state, ev)
        elif aggregate_type == "Specification":
            state = apply_specification_event(state, ev)
        elif aggregate_type == "ChatSession":
            state = apply_chat_session_event(state, ev)
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
    p, m = upcast_event(ev.event_type, ev.payload, ev.metadata)

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
        project.chat_index_mode = str(p.get("chat_index_mode") or "OFF")
        project.chat_attachment_ingestion_mode = str(
            p.get("chat_attachment_ingestion_mode") or "METADATA_ONLY"
        )
        project.event_storming_enabled = bool(p.get("event_storming_enabled", True))
    elif ev.event_type == PROJECT_EVENT_DELETED:
        project = db.get(Project, ev.aggregate_id)
        if project:
            project.is_deleted = True
        db.execute(delete(ProjectTagIndex).where(ProjectTagIndex.project_id == ev.aggregate_id))
        db.execute(delete(ProjectMember).where(ProjectMember.project_id == ev.aggregate_id))
        db.execute(delete(SavedView).where(SavedView.project_id == ev.aggregate_id))
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
            if "chat_index_mode" in p:
                project.chat_index_mode = str(p.get("chat_index_mode") or "OFF")
            if "chat_attachment_ingestion_mode" in p:
                project.chat_attachment_ingestion_mode = str(
                    p.get("chat_attachment_ingestion_mode") or "METADATA_ONLY"
                )
            if "event_storming_enabled" in p:
                project.event_storming_enabled = bool(p.get("event_storming_enabled", True))
    elif ev.event_type == PROJECT_EVENT_MEMBER_UPSERTED:
        project_id = p.get("project_id") or ev.aggregate_id
        workspace_id = p.get("workspace_id") or m.get("workspace_id")
        user_id = p.get("user_id")
        role = str(p.get("role") or "Contributor")
        if project_id and workspace_id and user_id:
            existing = db.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == user_id,
                )
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    ProjectMember(
                        workspace_id=workspace_id,
                        project_id=project_id,
                        user_id=user_id,
                        role=role,
                    )
                )
            else:
                existing.role = role
    elif ev.event_type == PROJECT_EVENT_MEMBER_REMOVED:
        project_id = p.get("project_id") or ev.aggregate_id
        user_id = p.get("user_id")
        if project_id and user_id:
            db.execute(
                delete(ProjectMember).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == user_id,
                )
            )
    elif ev.event_type == NOTE_EVENT_CREATED:
        note = db.get(Note, ev.aggregate_id)
        if note is None:
            note = Note(id=ev.aggregate_id, workspace_id=p["workspace_id"], title=p.get("title", ""))
            db.add(note)
        note.workspace_id = p["workspace_id"]
        note.project_id = p.get("project_id")
        note.note_group_id = p.get("note_group_id")
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
        instruction = str(p.get("instruction") or p.get("scheduled_instruction") or "").strip() or None
        execution_triggers = normalize_execution_triggers(p.get("execution_triggers"))
        if not execution_triggers:
            legacy_trigger = build_legacy_schedule_trigger(
                scheduled_at_utc=p.get("scheduled_at_utc"),
                schedule_timezone=p.get("schedule_timezone"),
                recurring_rule=p.get("recurring_rule"),
            )
            if legacy_trigger is not None:
                execution_triggers = [legacy_trigger]
        legacy_schedule = derive_legacy_schedule_fields(
            instruction=instruction,
            execution_triggers=execution_triggers,
        )
        task.workspace_id = p["workspace_id"]
        task.project_id = p.get("project_id")
        task.task_group_id = p.get("task_group_id")
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
        task.instruction = instruction
        task.execution_triggers = json.dumps(execution_triggers)
        task.recurring_rule = legacy_schedule.get("recurring_rule")
        task.task_type = legacy_schedule.get("task_type", "manual")
        task.scheduled_instruction = legacy_schedule.get("scheduled_instruction")
        task.scheduled_at_utc = datetime.fromisoformat(legacy_schedule["scheduled_at_utc"]) if legacy_schedule.get("scheduled_at_utc") else None
        task.schedule_timezone = legacy_schedule.get("schedule_timezone")
        task.schedule_state = p.get("schedule_state", "idle")
        task.last_schedule_run_at = None
        task.last_schedule_error = None
        task.order_index = p.get("order_index", 0)
        _normalize_task_row_automation_fields(task)
        _recompute_project_tag_index(db, task.project_id)
    elif ev.event_type == TASK_GROUP_EVENT_CREATED:
        group = db.get(TaskGroup, ev.aggregate_id)
        if group is None:
            group = TaskGroup(
                id=ev.aggregate_id,
                workspace_id=p["workspace_id"],
                project_id=p["project_id"],
                name=p.get("name", ""),
            )
            db.add(group)
        group.workspace_id = p["workspace_id"]
        group.project_id = p["project_id"]
        group.name = p.get("name", "") or ""
        group.description = p.get("description", "") or ""
        group.color = p.get("color")
        group.order_index = int(p.get("order_index", 0))
        group.is_deleted = bool(p.get("is_deleted", False))
    elif ev.event_type == NOTE_GROUP_EVENT_CREATED:
        group = db.get(NoteGroup, ev.aggregate_id)
        if group is None:
            group = NoteGroup(
                id=ev.aggregate_id,
                workspace_id=p["workspace_id"],
                project_id=p["project_id"],
                name=p.get("name", ""),
            )
            db.add(group)
        group.workspace_id = p["workspace_id"]
        group.project_id = p["project_id"]
        group.name = p.get("name", "") or ""
        group.description = p.get("description", "") or ""
        group.color = p.get("color")
        group.order_index = int(p.get("order_index", 0))
        group.is_deleted = bool(p.get("is_deleted", False))
    elif ev.event_type == CHAT_SESSION_EVENT_STARTED:
        session = db.get(ChatSession, ev.aggregate_id)
        if session is None:
            session = ChatSession(
                id=ev.aggregate_id,
                workspace_id=p.get("workspace_id") or m.get("workspace_id") or "",
                project_id=p.get("project_id") or m.get("project_id"),
                session_key=str(p.get("session_key") or m.get("session_id") or ev.aggregate_id),
                title=str(p.get("title") or "Session"),
                created_by=str(p.get("created_by") or m.get("actor_id") or ""),
            )
            db.add(session)
        session.workspace_id = p.get("workspace_id") or m.get("workspace_id") or session.workspace_id
        session.project_id = p.get("project_id") if "project_id" in p else (m.get("project_id") or session.project_id)
        session.session_key = str(p.get("session_key") or session.session_key or ev.aggregate_id)
        session.title = str(p.get("title") or session.title or "Session")
        session.created_by = str(p.get("created_by") or session.created_by or m.get("actor_id") or "")
        session.is_archived = bool(p.get("is_archived", False))
        session.codex_session_id = p.get("codex_session_id")
        session.mcp_servers = json.dumps(_normalize_json_list(p.get("mcp_servers")), ensure_ascii=True)
        session.session_attachment_refs = json.dumps(
            _normalize_json_list(p.get("session_attachment_refs")),
            ensure_ascii=True,
        )
        session.usage_json = json.dumps(_normalize_json_dict(p.get("usage")), ensure_ascii=True)
        session.last_message_at = _parse_datetime_or_none(p.get("last_message_at"))
        session.last_message_preview = str(p.get("last_message_preview") or "")
        session.last_task_event_at = _parse_datetime_or_none(p.get("last_task_event_at"))
    elif ev.event_type == CHAT_SESSION_EVENT_RENAMED:
        session = db.get(ChatSession, ev.aggregate_id)
        if session:
            session.title = str(p.get("title") or session.title or "Session")
    elif ev.event_type == CHAT_SESSION_EVENT_ARCHIVED:
        session = db.get(ChatSession, ev.aggregate_id)
        if session:
            session.is_archived = True
    elif ev.event_type == CHAT_SESSION_EVENT_CONTEXT_UPDATED:
        session = db.get(ChatSession, ev.aggregate_id)
        if session:
            if "project_id" in p:
                session.project_id = p.get("project_id")
            if "mcp_servers" in p and p.get("mcp_servers") is not None:
                session.mcp_servers = json.dumps(_normalize_json_list(p.get("mcp_servers")), ensure_ascii=True)
            if "session_attachment_refs" in p and p.get("session_attachment_refs") is not None:
                session.session_attachment_refs = json.dumps(
                    _normalize_json_list(p.get("session_attachment_refs")),
                    ensure_ascii=True,
                )
            if "codex_session_id" in p:
                session.codex_session_id = p.get("codex_session_id")
            if "usage" in p:
                session.usage_json = json.dumps(_normalize_json_dict(p.get("usage")), ensure_ascii=True)
            if "last_task_event_at" in p:
                session.last_task_event_at = _parse_datetime_or_none(p.get("last_task_event_at"))
    elif ev.event_type in {CHAT_SESSION_EVENT_USER_MESSAGE_APPENDED, CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_APPENDED}:
        role = "assistant" if ev.event_type == CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_APPENDED else "user"
        message_id = str(p.get("message_id") or "").strip()
        order_index = int(p.get("order_index") or 0)
        turn_created_at = _parse_datetime_or_none(p.get("created_at")) or datetime.now(timezone.utc)
        attachment_refs = _normalize_json_list(p.get("attachment_refs"))
        usage_payload = _normalize_json_dict(p.get("usage"))
        session = db.get(ChatSession, ev.aggregate_id)
        if session is None:
            session = ChatSession(
                id=ev.aggregate_id,
                workspace_id=str(p.get("workspace_id") or m.get("workspace_id") or ""),
                project_id=p.get("project_id") if "project_id" in p else m.get("project_id"),
                session_key=str(p.get("session_key") or m.get("session_id") or ev.aggregate_id),
                title="Session",
                created_by=str(m.get("actor_id") or ""),
            )
            db.add(session)
        if "project_id" in p:
            session.project_id = p.get("project_id")
        if "mcp_servers" in p:
            session.mcp_servers = json.dumps(_normalize_json_list(p.get("mcp_servers")), ensure_ascii=True)
        if role == "assistant":
            if "codex_session_id" in p:
                session.codex_session_id = p.get("codex_session_id")
            if "usage" in p:
                session.usage_json = json.dumps(usage_payload, ensure_ascii=True)
        session.last_message_at = turn_created_at
        session.last_message_preview = str(p.get("content") or "")[:240]

        if message_id:
            message = db.get(ChatMessage, message_id)
            if message is None:
                message = ChatMessage(
                    id=message_id,
                    workspace_id=session.workspace_id,
                    project_id=session.project_id,
                    session_id=session.id,
                    role=role,
                    content=str(p.get("content") or ""),
                    order_index=order_index,
                    attachment_refs=json.dumps(attachment_refs, ensure_ascii=True),
                    usage_json=json.dumps(usage_payload if role == "assistant" else {}, ensure_ascii=True),
                    is_deleted=False,
                    turn_created_at=turn_created_at,
                )
                db.add(message)
            else:
                message.workspace_id = session.workspace_id
                message.project_id = session.project_id
                message.session_id = session.id
                message.role = role
                message.content = str(p.get("content") or "")
                message.order_index = order_index
                message.attachment_refs = json.dumps(attachment_refs, ensure_ascii=True)
                if role == "assistant":
                    message.usage_json = json.dumps(usage_payload, ensure_ascii=True)
                message.turn_created_at = turn_created_at
                message.is_deleted = False
    elif ev.event_type == CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_UPDATED:
        message_id = str(p.get("message_id") or "").strip()
        usage_payload = _normalize_json_dict(p.get("usage"))
        message = db.get(ChatMessage, message_id) if message_id else None
        if message:
            message.content = str(p.get("content") or message.content or "")
            if "usage" in p:
                message.usage_json = json.dumps(usage_payload, ensure_ascii=True)
            if "is_deleted" in p:
                message.is_deleted = bool(p.get("is_deleted"))
        session = db.get(ChatSession, ev.aggregate_id)
        if session:
            session.last_message_preview = str(p.get("content") or session.last_message_preview or "")[:240]
            if "codex_session_id" in p:
                session.codex_session_id = p.get("codex_session_id")
            if "usage" in p:
                session.usage_json = json.dumps(usage_payload, ensure_ascii=True)
    elif ev.event_type == CHAT_SESSION_EVENT_MESSAGE_DELETED:
        message_id = str(p.get("message_id") or "").strip()
        message = db.get(ChatMessage, message_id) if message_id else None
        if message:
            message.is_deleted = True
    elif ev.event_type == CHAT_SESSION_EVENT_ATTACHMENT_LINKED:
        attachment_id = str(p.get("attachment_id") or "").strip()
        message_id = str(p.get("message_id") or "").strip()
        if attachment_id and message_id:
            workspace_id = str(p.get("workspace_id") or m.get("workspace_id") or "")
            project_id = p.get("project_id") if "project_id" in p else m.get("project_id")
            _ensure_chat_message_placeholder(
                db,
                aggregate_id=ev.aggregate_id,
                message_id=message_id,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_id=str(m.get("actor_id") or ""),
                session_key=str(p.get("session_key") or m.get("session_id") or ev.aggregate_id),
            )
            attachment = db.get(ChatAttachment, attachment_id)
            if attachment is None:
                attachment = ChatAttachment(
                    id=attachment_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    session_id=ev.aggregate_id,
                    message_id=message_id,
                    path=str(p.get("path") or ""),
                    name=str(p.get("name") or ""),
                    mime_type=p.get("mime_type"),
                    size_bytes=p.get("size_bytes"),
                    checksum=p.get("checksum"),
                    extraction_status=str(p.get("extraction_status") or "pending"),
                    extracted_text=p.get("extracted_text"),
                    is_deleted=bool(p.get("is_deleted", False)),
                )
                db.add(attachment)
            else:
                attachment.workspace_id = str(p.get("workspace_id") or m.get("workspace_id") or attachment.workspace_id)
                if "project_id" in p:
                    attachment.project_id = p.get("project_id")
                attachment.session_id = ev.aggregate_id
                attachment.message_id = message_id
                attachment.path = str(p.get("path") or attachment.path or "")
                attachment.name = str(p.get("name") or attachment.name or "")
                attachment.mime_type = p.get("mime_type")
                attachment.size_bytes = p.get("size_bytes")
                attachment.checksum = p.get("checksum")
                if "extraction_status" in p:
                    attachment.extraction_status = str(p.get("extraction_status") or "pending")
                if "extracted_text" in p:
                    attachment.extracted_text = p.get("extracted_text")
                if "is_deleted" in p:
                    attachment.is_deleted = bool(p.get("is_deleted"))
    elif ev.event_type == CHAT_SESSION_EVENT_RESOURCE_LINKED:
        message_id = str(p.get("message_id") or "").strip()
        resource_type = str(p.get("resource_type") or "").strip()
        resource_id = str(p.get("resource_id") or "").strip()
        relation = str(p.get("relation") or "created").strip() or "created"
        if message_id and resource_type and resource_id:
            workspace_id = str(p.get("workspace_id") or m.get("workspace_id") or "")
            project_id = p.get("project_id") if "project_id" in p else m.get("project_id")
            _ensure_chat_message_placeholder(
                db,
                aggregate_id=ev.aggregate_id,
                message_id=message_id,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_id=str(m.get("actor_id") or ""),
                session_key=str(p.get("session_key") or m.get("session_id") or ev.aggregate_id),
            )
            existing = db.execute(
                select(ChatMessageResourceLink).where(
                    ChatMessageResourceLink.session_id == ev.aggregate_id,
                    ChatMessageResourceLink.message_id == message_id,
                    ChatMessageResourceLink.resource_type == resource_type,
                    ChatMessageResourceLink.resource_id == resource_id,
                    ChatMessageResourceLink.relation == relation,
                )
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    ChatMessageResourceLink(
                        workspace_id=workspace_id,
                        project_id=project_id,
                        session_id=ev.aggregate_id,
                        message_id=message_id,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        relation=relation,
                    )
                )
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
                    if k in {"labels", "subtasks", "attachments", "external_refs", "attachment_refs", "execution_triggers"} and v is not None:
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
                task.task_group_id = None
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
            _normalize_task_row_automation_fields(task)
            _recompute_project_tag_index(db, old_project_id)
            _recompute_project_tag_index(db, task.project_id)
    elif ev.event_type in TASK_GROUP_MUTATION_EVENTS:
        group = db.get(TaskGroup, ev.aggregate_id)
        if group:
            if ev.event_type == TASK_GROUP_EVENT_UPDATED:
                for k, v in p.items():
                    setattr(group, k, v)
            elif ev.event_type == TASK_GROUP_EVENT_REORDERED:
                if "order_index" in p:
                    group.order_index = int(p.get("order_index") or 0)
            elif ev.event_type == TASK_GROUP_EVENT_DELETED:
                group.is_deleted = True
                db.execute(
                    Task.__table__.update()
                    .where(Task.task_group_id == ev.aggregate_id)
                    .values(task_group_id=None)
                )
    elif ev.event_type in NOTE_GROUP_MUTATION_EVENTS:
        group = db.get(NoteGroup, ev.aggregate_id)
        if group:
            if ev.event_type == NOTE_GROUP_EVENT_UPDATED:
                for k, v in p.items():
                    setattr(group, k, v)
            elif ev.event_type == NOTE_GROUP_EVENT_REORDERED:
                if "order_index" in p:
                    group.order_index = int(p.get("order_index") or 0)
            elif ev.event_type == NOTE_GROUP_EVENT_DELETED:
                group.is_deleted = True
                db.execute(
                    Note.__table__.update()
                    .where(Note.note_group_id == ev.aggregate_id)
                    .values(note_group_id=None)
                )
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
        payload_json = p.get("payload_json")
        if isinstance(payload_json, dict):
            payload_json = dumps_payload_json(payload_json)
        else:
            payload_json = str(payload_json or "{}")
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
                notification_type=normalize_notification_type(p.get("notification_type") or DEFAULT_NOTIFICATION_TYPE),
                severity=normalize_severity(p.get("severity") or DEFAULT_NOTIFICATION_SEVERITY),
                dedupe_key=normalize_dedupe_key(p.get("dedupe_key")),
                payload_json=payload_json or "{}",
                source_event=str(p.get("source_event") or "").strip() or None,
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
            n.notification_type = normalize_notification_type(p.get("notification_type") or DEFAULT_NOTIFICATION_TYPE)
            n.severity = normalize_severity(p.get("severity") or DEFAULT_NOTIFICATION_SEVERITY)
            n.dedupe_key = normalize_dedupe_key(p.get("dedupe_key"))
            n.payload_json = payload_json or "{}"
            n.source_event = str(p.get("source_event") or "").strip() or None
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
    elif ev.event_type == PROJECT_TEMPLATE_EVENT_BOUND:
        project_id = p.get("project_id") or ev.aggregate_id
        if project_id:
            binding = db.execute(
                select(ProjectTemplateBinding).where(ProjectTemplateBinding.project_id == project_id)
            ).scalar_one_or_none()
            if binding is None:
                binding = ProjectTemplateBinding(
                    workspace_id=p.get("workspace_id") or m.get("workspace_id") or "",
                    project_id=project_id,
                    template_key=str(p.get("template_key") or ""),
                    template_version=str(p.get("template_version") or ""),
                    applied_by=str(p.get("applied_by") or m.get("actor_id") or ""),
                    parameters_json=str(p.get("parameters_json") or "{}"),
                )
                db.add(binding)
            else:
                if p.get("workspace_id"):
                    binding.workspace_id = p["workspace_id"]
                if p.get("template_key"):
                    binding.template_key = p["template_key"]
                if p.get("template_version"):
                    binding.template_version = p["template_version"]
                if p.get("applied_by"):
                    binding.applied_by = p["applied_by"]
                if p.get("parameters_json") is not None:
                    binding.parameters_json = str(p.get("parameters_json") or "{}")
    elif ev.event_type == USER_EVENT_CREATED:
        user = db.get(User, ev.aggregate_id)
        if user is None:
            user = User(
                id=ev.aggregate_id,
                username=str(p.get("username") or ""),
                full_name=str(p.get("full_name") or ""),
                user_type=str(p.get("user_type") or "human"),
            )
            db.add(user)
        user.username = str(p.get("username") or user.username)
        user.full_name = str(p.get("full_name") or user.full_name)
        user.user_type = str(p.get("user_type") or user.user_type or "human")
        user.password_hash = p.get("password_hash")
        user.must_change_password = bool(p.get("must_change_password", True))
        changed_at = p.get("password_changed_at")
        user.password_changed_at = datetime.fromisoformat(changed_at) if changed_at else None
        user.is_active = bool(p.get("is_active", True))
        user.theme = str(p.get("theme") or user.theme or "light")
        user.timezone = str(p.get("timezone") or user.timezone or "UTC")
        user.notifications_enabled = bool(p.get("notifications_enabled", True))
        user.agent_chat_model = str(p.get("agent_chat_model") or user.agent_chat_model or "")
        user.agent_chat_reasoning_effort = str(
            p.get("agent_chat_reasoning_effort") or user.agent_chat_reasoning_effort or "medium"
        )

        workspace_id = p.get("workspace_id")
        workspace_role = p.get("workspace_role")
        if workspace_id and workspace_role:
            membership = db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == ev.aggregate_id,
                )
            ).scalar_one_or_none()
            if membership is None:
                db.add(
                    WorkspaceMember(
                        workspace_id=workspace_id,
                        user_id=ev.aggregate_id,
                        role=str(workspace_role),
                    )
                )
            else:
                membership.role = str(workspace_role)
    elif ev.event_type == USER_EVENT_WORKSPACE_ROLE_SET:
        workspace_id = p.get("workspace_id")
        role = str(p.get("role") or "Member")
        if workspace_id:
            membership = db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == ev.aggregate_id,
                )
            ).scalar_one_or_none()
            if membership is None:
                db.add(
                    WorkspaceMember(
                        workspace_id=workspace_id,
                        user_id=ev.aggregate_id,
                        role=role,
                    )
                )
            else:
                membership.role = role
    elif ev.event_type in {USER_EVENT_PASSWORD_CHANGED, USER_EVENT_PASSWORD_RESET}:
        user = db.get(User, ev.aggregate_id)
        if user:
            if "password_hash" in p:
                user.password_hash = p.get("password_hash")
            if "must_change_password" in p:
                user.must_change_password = bool(p.get("must_change_password"))
            changed_at = p.get("password_changed_at")
            user.password_changed_at = datetime.fromisoformat(changed_at) if changed_at else None
        keep_session_hash = str(p.get("keep_session_hash") or "").strip()
        stmt = delete(AuthSession).where(AuthSession.user_id == ev.aggregate_id)
        if keep_session_hash:
            stmt = stmt.where(AuthSession.token_hash != keep_session_hash)
        db.execute(stmt)
    elif ev.event_type == USER_EVENT_DEACTIVATED:
        user = db.get(User, ev.aggregate_id)
        if user:
            user.is_active = False
        db.execute(delete(AuthSession).where(AuthSession.user_id == ev.aggregate_id))
    elif ev.event_type == USER_EVENT_PREFERENCES_UPDATED:
        user = db.get(User, ev.aggregate_id)
        if user:
            if "theme" in p and p["theme"] in {"light", "dark"}:
                user.theme = p["theme"]
            if "timezone" in p and p["timezone"]:
                user.timezone = p["timezone"]
            if "notifications_enabled" in p:
                user.notifications_enabled = bool(p["notifications_enabled"])
            if "agent_chat_model" in p:
                user.agent_chat_model = str(p.get("agent_chat_model") or "")
            if "agent_chat_reasoning_effort" in p and p.get("agent_chat_reasoning_effort"):
                user.agent_chat_reasoning_effort = str(p.get("agent_chat_reasoning_effort"))

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
