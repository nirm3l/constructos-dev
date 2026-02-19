from __future__ import annotations

import json
import threading
import time
from typing import Any

from sqlalchemy import select

from features.projects.domain import (
    EVENT_CREATED as PROJECT_EVENT_CREATED,
    EVENT_DELETED as PROJECT_EVENT_DELETED,
    EVENT_UPDATED as PROJECT_EVENT_UPDATED,
)

from .contracts import EventEnvelope
from .eventing_rebuild import rebuild_state
from .eventing_store import get_kurrent_client
from .settings import AGENT_SYSTEM_USER_ID, GRAPH_PROJECTION_BATCH_SIZE, GRAPH_PROJECTION_POLL_INTERVAL_SECONDS, logger
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


def _project_vector_event(db, ev: EventEnvelope) -> None:
    if ev.event_type == PROJECT_EVENT_DELETED:
        purge_project_chunks(db, project_id=ev.aggregate_id)
        return

    if ev.event_type in {PROJECT_EVENT_CREATED, PROJECT_EVENT_UPDATED}:
        payload = ev.payload or {}
        should_reindex = False
        if ev.event_type == PROJECT_EVENT_CREATED and bool(payload.get("embedding_enabled", False)):
            should_reindex = True
        if "embedding_enabled" in payload or "embedding_model" in payload:
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
        try:
            project_kurrent_vector_once(limit=GRAPH_PROJECTION_BATCH_SIZE)
            with SessionLocal() as db:
                checkpoint = _get_vector_checkpoint(db)
                start_position = checkpoint.commit_position if checkpoint.commit_position > 0 else None
            subscription = client.subscribe_to_all(commit_position=start_position)
            for event in subscription:
                if _vector_stop_event.is_set():
                    subscription.stop()
                    break
                commit_position = int(getattr(event, "commit_position", -1))
                if commit_position < 0:
                    continue
                packed = _recorded_to_envelope(event)
                envelope = packed[1] if packed is not None else None
                with SessionLocal() as db:
                    checkpoint = _get_vector_checkpoint(db)
                    if commit_position <= checkpoint.commit_position:
                        continue
                    if envelope is not None:
                        _project_vector_event(db, envelope)
                    checkpoint.commit_position = commit_position
                    db.commit()
        except Exception as exc:
            logger.warning("Vector projection worker retrying after error: %s", exc)
            time.sleep(max(0.5, GRAPH_PROJECTION_POLL_INTERVAL_SECONDS))


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
    if _vector_thread and _vector_thread.is_alive():
        _vector_thread.join(timeout=3)
    _vector_thread = None
