from __future__ import annotations

import json
import threading
import time
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .contracts import EventEnvelope
from .eventing_rebuild import project_event
from .eventing_store import get_kurrent_client
from .models import ProjectionCheckpoint, SessionLocal
from .settings import logger

_projection_stop_event = threading.Event()
_projection_thread: threading.Thread | None = None


def _extract_aggregate_from_stream(stream_name: str) -> tuple[str, str] | None:
    if stream_name.startswith("snapshot::"):
        return None
    base, sep, raw_id = stream_name.partition("::")
    if sep != "::" or not base or not raw_id:
        return None
    return base, raw_id


def _get_projection_checkpoint(db: Session, name: str = "read-model") -> ProjectionCheckpoint:
    checkpoint = db.get(ProjectionCheckpoint, name)
    if checkpoint is None:
        checkpoint = ProjectionCheckpoint(name=name, commit_position=0)
        db.add(checkpoint)
        db.flush()
    return checkpoint


def _project_recorded_event(db: Session, event: Any):
    if getattr(event, "is_system_event", False):
        return
    if getattr(event, "is_checkpoint", False):
        return
    if getattr(event, "is_caught_up", False):
        return
    if getattr(event, "is_fell_behind", False):
        return
    parsed = _extract_aggregate_from_stream(getattr(event, "stream_name", ""))
    if parsed is None:
        return
    aggregate_type, aggregate_id = parsed
    env = EventEnvelope(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        version=int(event.stream_position) + 1,
        event_type=event.type,
        payload=json.loads((event.data or b"{}").decode("utf-8")),
        metadata=json.loads((event.metadata or b"{}").decode("utf-8")),
    )
    project_event(db, env)


def _is_duplicate_projection_error(exc: IntegrityError) -> bool:
    message = str(exc).lower()
    return "duplicate key value violates unique constraint" in message or "unique constraint failed" in message


def project_kurrent_events_once(limit: int = 500) -> int:
    client = get_kurrent_client()
    if client is None:
        return 0
    with SessionLocal() as db:
        checkpoint = _get_projection_checkpoint(db)
        start_position = checkpoint.commit_position if checkpoint.commit_position > 0 else None
        try:
            rows = client.read_all(commit_position=start_position, limit=limit)
        except Exception as exc:
            logger.warning("Kurrent projection catch-up failed: %s", exc)
            return 0

        processed = 0
        for event in rows:
            commit_position = int(getattr(event, "commit_position", -1))
            if commit_position <= checkpoint.commit_position:
                continue
            try:
                _project_recorded_event(db, event)
            except IntegrityError as exc:
                if not _is_duplicate_projection_error(exc):
                    raise
                db.rollback()
                checkpoint = _get_projection_checkpoint(db)
                checkpoint.commit_position = commit_position
                db.commit()
                processed += 1
                continue
            checkpoint.commit_position = commit_position
            db.commit()
            processed += 1
        return processed


def _projection_worker_loop():
    client = get_kurrent_client()
    if client is None:
        return
    while not _projection_stop_event.is_set():
        try:
            project_kurrent_events_once(limit=2000)
            with SessionLocal() as db:
                checkpoint = _get_projection_checkpoint(db)
                start_position = checkpoint.commit_position if checkpoint.commit_position > 0 else None
            subscription = client.subscribe_to_all(commit_position=start_position)
            for event in subscription:
                if _projection_stop_event.is_set():
                    subscription.stop()
                    break
                commit_position = int(getattr(event, "commit_position", -1))
                with SessionLocal() as db:
                    checkpoint = _get_projection_checkpoint(db)
                    if commit_position <= checkpoint.commit_position:
                        continue
                    try:
                        _project_recorded_event(db, event)
                    except IntegrityError as exc:
                        if not _is_duplicate_projection_error(exc):
                            raise
                        db.rollback()
                        checkpoint = _get_projection_checkpoint(db)
                        checkpoint.commit_position = commit_position
                        db.commit()
                        continue
                    checkpoint.commit_position = commit_position
                    db.commit()
        except Exception as exc:
            logger.warning("Kurrent projection worker retrying after error: %s", exc)
            time.sleep(1)


def start_projection_worker():
    global _projection_thread
    if get_kurrent_client() is None:
        return
    if _projection_thread and _projection_thread.is_alive():
        return
    _projection_stop_event.clear()
    _projection_thread = threading.Thread(target=_projection_worker_loop, name="kurrent-projection-worker", daemon=True)
    _projection_thread.start()


def stop_projection_worker():
    _projection_stop_event.set()
    global _projection_thread
    if _projection_thread and _projection_thread.is_alive():
        _projection_thread.join(timeout=3)
    _projection_thread = None
