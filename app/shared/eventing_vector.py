from __future__ import annotations

import json
import threading
from typing import Any

from sqlalchemy import select

from features.chat.domain import (
    EVENT_ASSISTANT_MESSAGE_APPENDED as CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_APPENDED,
    EVENT_ASSISTANT_MESSAGE_UPDATED as CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_UPDATED,
    EVENT_ATTACHMENT_LINKED as CHAT_SESSION_EVENT_ATTACHMENT_LINKED,
    EVENT_MESSAGE_DELETED as CHAT_SESSION_EVENT_MESSAGE_DELETED,
    EVENT_USER_MESSAGE_APPENDED as CHAT_SESSION_EVENT_USER_MESSAGE_APPENDED,
)
from features.projects.domain import (
    EVENT_CREATED as PROJECT_EVENT_CREATED,
    EVENT_DELETED as PROJECT_EVENT_DELETED,
    EVENT_UPDATED as PROJECT_EVENT_UPDATED,
)

from .chat_indexing import project_chat_indexing_policy
from .contracts import EventEnvelope
from .eventing_rebuild import rebuild_state
from .eventing_store import get_kurrent_client
from .settings import (
    AGENT_SYSTEM_USER_ID,
    GRAPH_PROJECTION_BATCH_SIZE,
    PERSISTENT_SUBSCRIPTION_EVENT_BUFFER_SIZE,
    PERSISTENT_SUBSCRIPTION_MAX_ACK_BATCH_SIZE,
    PERSISTENT_SUBSCRIPTION_MAX_ACK_DELAY_SECONDS,
    PERSISTENT_SUBSCRIPTION_RETRY_BACKOFF_SECONDS,
    PERSISTENT_SUBSCRIPTION_STOPPING_GRACE_SECONDS,
    PERSISTENT_SUBSCRIPTION_VECTOR_GROUP,
    logger,
)
from .realtime import enqueue_realtime_channel
from .vector_store import (
    index_entity_state,
    maybe_reindex_project,
    project_embedding_index_status,
    purge_project_chunks,
    vector_store_enabled,
)

_VECTOR_CHECKPOINT_NAME = "vector-store"
_PROJECT_EMBEDDING_INDEX_UPDATED = "ProjectEmbeddingIndexUpdated"
_vector_stop_event = threading.Event()
_vector_thread: threading.Thread | None = None
_vector_subscription: Any | None = None
_vector_subscription_lock = threading.Lock()


def _extract_aggregate_from_stream(stream_name: str) -> tuple[str, str] | None:
    if stream_name.startswith("snapshot::"):
        return None
    base, sep, raw_id = stream_name.partition("::")
    if sep != "::" or not base or not raw_id:
        return None
    return base, raw_id


def _get_vector_checkpoint(db, name: str = _VECTOR_CHECKPOINT_NAME) -> ProjectionCheckpoint:
    from .models import ProjectionCheckpoint

    checkpoint = db.get(ProjectionCheckpoint, name)
    if checkpoint is None:
        checkpoint = ProjectionCheckpoint(name=name, commit_position=0)
        db.add(checkpoint)
        db.flush()
    return checkpoint


def _recorded_to_envelope(event: Any) -> tuple[int, EventEnvelope] | None:
    if getattr(event, "is_system_event", False):
        return None
    if getattr(event, "is_checkpoint", False):
        return None
    if getattr(event, "is_caught_up", False):
        return None
    if getattr(event, "is_fell_behind", False):
        return None
    commit_position = int(getattr(event, "commit_position", -1))
    parsed = _extract_aggregate_from_stream(getattr(event, "stream_name", ""))
    if parsed is None:
        return None
    aggregate_type, aggregate_id = parsed
    envelope = EventEnvelope(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        version=int(event.stream_position) + 1,
        event_type=event.type,
        payload=json.loads((event.data or b"{}").decode("utf-8")),
        metadata=json.loads((event.metadata or b"{}").decode("utf-8")),
    )
    return commit_position, envelope


def _project_workspace_id(db, *, project_id: str, metadata: dict[str, Any]) -> str | None:
    from .models import Project

    workspace_id = str(metadata.get("workspace_id") or "").strip()
    if workspace_id:
        return workspace_id
    project = db.get(Project, project_id)
    if project is None:
        return None
    resolved = str(project.workspace_id or "").strip()
    return resolved or None


def _emit_project_index_activity(
    db,
    *,
    project_id: str,
    workspace_id: str | None,
    event_key: str,
    status: str,
    indexed_chunks: int,
    embedding_model: str | None,
) -> None:
    from .models import ActivityLog

    if not workspace_id:
        return
    details_payload = {
        "_event_key": event_key,
        "project_id": project_id,
        "status": status,
        "indexed_chunks": int(indexed_chunks),
        "embedding_model": embedding_model,
    }
    details_json = json.dumps(details_payload, sort_keys=True)
    existing = db.execute(
        select(ActivityLog.id).where(
            ActivityLog.workspace_id == workspace_id,
            ActivityLog.project_id == project_id,
            ActivityLog.task_id.is_(None),
            ActivityLog.actor_id == AGENT_SYSTEM_USER_ID,
            ActivityLog.action == _PROJECT_EMBEDDING_INDEX_UPDATED,
            ActivityLog.details == details_json,
        )
    ).first()
    if existing:
        return
    db.add(
        ActivityLog(
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=None,
            actor_id=AGENT_SYSTEM_USER_ID,
            action=_PROJECT_EMBEDDING_INDEX_UPDATED,
            details=details_json,
        )
    )
    enqueue_realtime_channel(db, f"workspace:{workspace_id}")


def _load_project_chat_policy(db, *, project_id: str):
    from .models import Project

    project = db.get(Project, project_id)
    if project is None or bool(project.is_deleted):
        return None, None
    policy = project_chat_indexing_policy(
        chat_index_mode=getattr(project, "chat_index_mode", None),
        chat_attachment_ingestion_mode=getattr(project, "chat_attachment_ingestion_mode", None),
    )
    return project, policy


def _index_chat_message_state(db, *, message_id: str) -> None:
    from .models import ChatMessage

    message = db.get(ChatMessage, message_id)
    if message is None:
        return
    project_id = str(message.project_id or "").strip()
    if not project_id:
        return
    _, policy = _load_project_chat_policy(db, project_id=project_id)
    if policy is None or not policy.vector_enabled:
        return
    index_entity_state(
        db,
        entity_type="ChatMessage",
        entity_id=message.id,
        state={
            "workspace_id": message.workspace_id,
            "project_id": message.project_id,
            "role": message.role or "",
            "content": message.content or "",
            "is_deleted": bool(message.is_deleted),
            "updated_at": message.updated_at,
        },
    )


def _index_chat_attachment_state(db, *, attachment_id: str) -> None:
    from .models import ChatAttachment

    attachment = db.get(ChatAttachment, attachment_id)
    if attachment is None:
        return
    project_id = str(attachment.project_id or "").strip()
    if not project_id:
        return
    _, policy = _load_project_chat_policy(db, project_id=project_id)
    if policy is None or not policy.vector_enabled:
        return
    index_entity_state(
        db,
        entity_type="ChatAttachment",
        entity_id=attachment.id,
        state={
            "workspace_id": attachment.workspace_id,
            "project_id": attachment.project_id,
            "path": attachment.path or "",
            "name": attachment.name or "",
            "mime_type": attachment.mime_type or "",
            "size_bytes": attachment.size_bytes,
            "extraction_status": attachment.extraction_status or "pending",
            "extracted_text": attachment.extracted_text or "",
            "chat_attachment_ingestion_mode": policy.attachment_ingestion_mode,
            "is_deleted": bool(attachment.is_deleted),
            "updated_at": attachment.updated_at,
        },
    )


def _project_vector_event(db, ev: EventEnvelope) -> None:
    if ev.event_type == PROJECT_EVENT_DELETED:
        purge_project_chunks(db, project_id=ev.aggregate_id)
        return

    if ev.event_type in {PROJECT_EVENT_CREATED, PROJECT_EVENT_UPDATED}:
        payload = ev.payload or {}
        should_reindex = False
        if ev.event_type == PROJECT_EVENT_CREATED and bool(payload.get("embedding_enabled", False)):
            should_reindex = True
        if (
            "embedding_enabled" in payload
            or "embedding_model" in payload
            or "chat_index_mode" in payload
            or "chat_attachment_ingestion_mode" in payload
        ):
            should_reindex = True
        if should_reindex:
            indexed_chunks = maybe_reindex_project(
                db,
                project_id=ev.aggregate_id,
                embedding_enabled=payload.get("embedding_enabled"),
                embedding_model=payload.get("embedding_model"),
            )
            status = project_embedding_index_status(
                db,
                project_id=ev.aggregate_id,
                embedding_enabled=payload.get("embedding_enabled"),
                embedding_model=payload.get("embedding_model"),
            )
            metadata = ev.metadata or {}
            workspace_id = _project_workspace_id(db, project_id=ev.aggregate_id, metadata=metadata)
            event_key = f"{ev.aggregate_type}:{ev.aggregate_id}:{ev.version}:{ev.event_type}"
            _emit_project_index_activity(
                db,
                project_id=ev.aggregate_id,
                workspace_id=workspace_id,
                event_key=event_key,
                status=status,
                indexed_chunks=indexed_chunks,
                embedding_model=payload.get("embedding_model"),
            )
            return

    if ev.aggregate_type == "ChatSession":
        payload = ev.payload or {}
        if ev.event_type in {
            CHAT_SESSION_EVENT_USER_MESSAGE_APPENDED,
            CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_APPENDED,
            CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_UPDATED,
            CHAT_SESSION_EVENT_MESSAGE_DELETED,
        }:
            message_id = str(payload.get("message_id") or "").strip()
            if message_id:
                _index_chat_message_state(db, message_id=message_id)
            return
        if ev.event_type == CHAT_SESSION_EVENT_ATTACHMENT_LINKED:
            attachment_id = str(payload.get("attachment_id") or "").strip()
            if attachment_id:
                _index_chat_attachment_state(db, attachment_id=attachment_id)
            return

    if ev.aggregate_type not in {"Task", "Note", "Specification", "ProjectRule"}:
        return
    state, _ = rebuild_state(db, ev.aggregate_type, ev.aggregate_id)
    if not state:
        return
    index_entity_state(
        db,
        entity_type=ev.aggregate_type,
        entity_id=ev.aggregate_id,
        state=state,
    )


def project_kurrent_vector_once(limit: int | None = None) -> int:
    from .models import SessionLocal

    if not vector_store_enabled():
        return 0
    client = get_kurrent_client()
    if client is None:
        return 0
    processed = 0
    try:
        with SessionLocal() as db:
            checkpoint = _get_vector_checkpoint(db)
            start_position = checkpoint.commit_position if checkpoint.commit_position > 0 else None
            rows = client.read_all(commit_position=start_position, limit=max(1, int(limit or GRAPH_PROJECTION_BATCH_SIZE)))
            for event in rows:
                commit_position = int(getattr(event, "commit_position", -1))
                if commit_position <= checkpoint.commit_position:
                    continue
                packed = _recorded_to_envelope(event)
                if packed is not None:
                    _, envelope = packed
                    _project_vector_event(db, envelope)
                    processed += 1
                checkpoint.commit_position = commit_position
                db.commit()
    except Exception as exc:
        logger.warning("Vector projection catch-up failed: %s", exc)
        return 0
    return processed


def _vector_worker_loop() -> None:
    from .models import SessionLocal

    client = get_kurrent_client()
    if client is None:
        return
    while not _vector_stop_event.is_set():
        subscription = None
        try:
            subscription = client.read_subscription_to_all(
                group_name=PERSISTENT_SUBSCRIPTION_VECTOR_GROUP,
                event_buffer_size=max(1, int(PERSISTENT_SUBSCRIPTION_EVENT_BUFFER_SIZE)),
                max_ack_batch_size=max(1, int(PERSISTENT_SUBSCRIPTION_MAX_ACK_BATCH_SIZE)),
                max_ack_delay=max(0.0, float(PERSISTENT_SUBSCRIPTION_MAX_ACK_DELAY_SECONDS)),
                stopping_grace=max(0.0, float(PERSISTENT_SUBSCRIPTION_STOPPING_GRACE_SECONDS)),
            )
            _set_vector_subscription(subscription)
            for event in subscription:
                if _vector_stop_event.is_set():
                    break
                packed = _recorded_to_envelope(event)
                envelope = packed[1] if packed is not None else None
                with SessionLocal() as db:
                    try:
                        if envelope is not None:
                            _project_vector_event(db, envelope)
                        db.commit()
                    except Exception as exc:
                        db.rollback()
                        logger.warning("Vector projection event failed, retrying event: %s", exc)
                        subscription.nack(event, "retry")
                        continue
                subscription.ack(event)
        except Exception as exc:
            logger.warning("Vector projection worker retrying after error: %s", exc)
            _vector_stop_event.wait(max(0.2, float(PERSISTENT_SUBSCRIPTION_RETRY_BACKOFF_SECONDS)))
        finally:
            _set_vector_subscription(None)
            if subscription is not None:
                try:
                    subscription.stop()
                except Exception:
                    pass


def _set_vector_subscription(subscription: Any | None) -> None:
    global _vector_subscription
    with _vector_subscription_lock:
        _vector_subscription = subscription


def _stop_vector_subscription() -> None:
    with _vector_subscription_lock:
        subscription = _vector_subscription
    if subscription is None:
        return
    try:
        subscription.stop()
    except Exception:
        pass


def start_vector_projection_worker() -> None:
    global _vector_thread
    if not vector_store_enabled():
        return
    if get_kurrent_client() is None:
        return
    if _vector_thread and _vector_thread.is_alive():
        return
    _vector_stop_event.clear()
    _vector_thread = threading.Thread(target=_vector_worker_loop, name="vector-projection-worker", daemon=True)
    _vector_thread.start()


def stop_vector_projection_worker() -> None:
    global _vector_thread
    _vector_stop_event.set()
    _stop_vector_subscription()
    if _vector_thread and _vector_thread.is_alive():
        _vector_thread.join(timeout=3)
    _vector_thread = None
