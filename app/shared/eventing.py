from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from features.notifications.domain import EVENT_CREATED as NOTIFICATION_EVENT_CREATED

from .contracts import ConcurrencyConflictError, EventEnvelope
from .eventing_notifications import emit_system_notifications as _emit_system_notifications
from .eventing_projections import project_kurrent_events_once, start_projection_worker, stop_projection_worker
from .eventing_rebuild import (
    apply_project_event,
    apply_task_event,
    load_events_after,
    load_snapshot,
    maybe_snapshot,
    project_event,
    rebuild_state,
)
from .eventing_store import (
    StreamState,
    WrongCurrentVersionError,
    allocate_id,
    current_version,
    get_kurrent_client,
    serialize_envelope,
    stream_id,
)
from .models import StoredEvent
from .realtime import enqueue_realtime_channels


def _is_duplicate_projection_error(exc: IntegrityError) -> bool:
    message = str(exc).lower()
    return "duplicate key value violates unique constraint" in message or "unique constraint failed" in message


def _project_event_write_through(db: Session, env: EventEnvelope) -> None:
    try:
        with db.begin_nested():
            project_event(db, env)
            db.flush()
    except IntegrityError as exc:
        if not _is_duplicate_projection_error(exc):
            raise


def append_event(
    db: Session,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
    expected_version: int | None = None,
) -> EventEnvelope:
    cur = current_version(db, aggregate_type, aggregate_id)
    if expected_version is not None and cur != expected_version:
        raise ConcurrencyConflictError(f"Expected version {expected_version}, got {cur}")
    version = cur + 1
    env = EventEnvelope(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        version=version,
        event_type=event_type,
        payload=payload,
        metadata={"schema_version": 2, **metadata},
    )

    client = get_kurrent_client()
    if client is not None:
        if expected_version is not None:
            exp = StreamState.NO_STREAM if expected_version == 0 else expected_version - 1
        else:
            exp = StreamState.NO_STREAM if cur == 0 else cur - 1
        try:
            client.append_to_stream(stream_name=stream_id(aggregate_type, aggregate_id), current_version=exp, events=[serialize_envelope(env)])
        except WrongCurrentVersionError as exc:
            raise ConcurrencyConflictError(str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Kurrent append failed: {exc}") from exc
        # Write-through projection to keep the SQLite read-model consistent even if the
        # background projection checkpoint is stale (e.g. EventStore reset).
        _project_event_write_through(db, env)
    else:
        db.add(
            StoredEvent(
                stream_id=stream_id(aggregate_type, aggregate_id),
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                version=version,
                event_type=event_type,
                payload=json.dumps(payload),
                meta=json.dumps(metadata),
            )
        )
        project_event(db, env)

    maybe_snapshot(db, aggregate_type, aggregate_id, version)
    _queue_realtime_signals(db, env)

    return env


def emit_system_notifications(db: Session, user) -> int:
    return _emit_system_notifications(db, user, append_event)


def _queue_realtime_signals(db: Session, env: EventEnvelope) -> None:
    channels: set[str] = set()

    workspace_id = str((env.metadata or {}).get("workspace_id") or (env.payload or {}).get("workspace_id") or "").strip()
    if workspace_id:
        channels.add(f"workspace:{workspace_id}")

    if env.aggregate_type == "Notification" and env.event_type == NOTIFICATION_EVENT_CREATED:
        user_id = str((env.payload or {}).get("user_id") or "").strip()
        if user_id:
            channels.add(f"user:{user_id}")

    if channels:
        enqueue_realtime_channels(db, channels)
