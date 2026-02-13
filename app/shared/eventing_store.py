from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .contracts import EventEnvelope
from .models import StoredEvent
from .settings import EVENTSTORE_URI

try:
    from kurrentdbclient import KurrentDBClient, NewEvent, StreamState
    from kurrentdbclient.exceptions import NotFoundError, WrongCurrentVersionError

    EventStoreDBClient = KurrentDBClient
except Exception:  # pragma: no cover
    try:
        from esdbclient import EventStoreDBClient, NewEvent, StreamState
        try:
            from esdbclient.exceptions import NotFoundError, WrongCurrentVersion

            WrongCurrentVersionError = WrongCurrentVersion
        except Exception:
            from esdbclient.exceptions import NotFound as NotFoundError
            from esdbclient.exceptions import WrongCurrentVersion as WrongCurrentVersionError
    except Exception:
        EventStoreDBClient = None
        NewEvent = None
        StreamState = None
        NotFoundError = Exception
        WrongCurrentVersionError = Exception


_kurrent_client: EventStoreDBClient | None = None


def stream_id(aggregate_type: str, aggregate_id: str) -> str:
    return f"{aggregate_type}::{aggregate_id}"


def snapshot_stream_id(aggregate_type: str, aggregate_id: str) -> str:
    return f"snapshot::{aggregate_type}::{aggregate_id}"


def get_kurrent_client() -> EventStoreDBClient | None:
    global _kurrent_client
    if not EVENTSTORE_URI or EventStoreDBClient is None:
        return None
    if _kurrent_client is None:
        _kurrent_client = EventStoreDBClient(EVENTSTORE_URI)
    return _kurrent_client


def allocate_id(_db: Session) -> str:
    return str(uuid.uuid4())


def serialize_envelope(env: EventEnvelope) -> NewEvent:
    return NewEvent(
        id=uuid.uuid4(),
        type=env.event_type,
        data=json.dumps(env.payload).encode("utf-8"),
        metadata=json.dumps(
            {
                "aggregate_type": env.aggregate_type,
                "aggregate_id": env.aggregate_id,
                **env.metadata,
            }
        ).encode("utf-8"),
    )


def serialize_snapshot_event(aggregate_type: str, aggregate_id: str, state: dict[str, Any], version: int) -> NewEvent:
    return NewEvent(
        id=uuid.uuid4(),
        type="Snapshot",
        data=json.dumps({"snapshot_schema_version": 2, "state": state, "version": version}).encode("utf-8"),
        metadata=json.dumps(
            {
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "schema_version": 2,
            }
        ).encode("utf-8"),
    )


def kurrent_read_stream(stream: str, *, backwards: bool = False, limit: int | None = None, from_position: int | None = None) -> tuple[Any, ...]:
    client = get_kurrent_client()
    if client is None:
        return tuple()
    return client.get_stream(
        stream_name=stream,
        stream_position=from_position,
        backwards=backwards,
        limit=limit or 2**63 - 1,
    )


def current_version(db: Session, aggregate_type: str, aggregate_id: str) -> int:
    client = get_kurrent_client()
    if client is not None:
        try:
            events = kurrent_read_stream(stream_id(aggregate_type, aggregate_id), backwards=True, limit=1)
        except NotFoundError:
            return 0
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Kurrent read failed: {exc}") from exc
        if not events:
            return 0
        return int(events[0].stream_position) + 1
    val = db.execute(
        select(func.max(StoredEvent.version)).where(
            StoredEvent.aggregate_type == aggregate_type,
            StoredEvent.aggregate_id == aggregate_id,
        )
    ).scalar()
    return int(val or 0)
