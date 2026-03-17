from __future__ import annotations

import json
import threading
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .contracts import EventEnvelope
from .eventing_rebuild import project_event
from .eventing_store import get_kurrent_client
from .models import ProjectionCheckpoint, SessionLocal
from .settings import (
    PERSISTENT_SUBSCRIPTION_EVENT_BUFFER_SIZE,
    PERSISTENT_SUBSCRIPTION_MAX_ACK_BATCH_SIZE,
    PERSISTENT_SUBSCRIPTION_MAX_ACK_DELAY_SECONDS,
    PERSISTENT_SUBSCRIPTION_READ_MODEL_MAX_EVENT_RETRIES,
    PERSISTENT_SUBSCRIPTION_READ_MODEL_GROUP,
    PERSISTENT_SUBSCRIPTION_RETRY_BACKOFF_SECONDS,
    PERSISTENT_SUBSCRIPTION_STOPPING_GRACE_SECONDS,
    logger,
)

_projection_stop_event = threading.Event()
_projection_thread: threading.Thread | None = None
_projection_subscription: Any | None = None
_projection_subscription_lock = threading.Lock()
_projection_event_failures: dict[str, int] = {}


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
        subscription = None
        try:
            subscription = client.read_subscription_to_all(
                group_name=PERSISTENT_SUBSCRIPTION_READ_MODEL_GROUP,
                event_buffer_size=max(1, int(PERSISTENT_SUBSCRIPTION_EVENT_BUFFER_SIZE)),
                max_ack_batch_size=max(1, int(PERSISTENT_SUBSCRIPTION_MAX_ACK_BATCH_SIZE)),
                max_ack_delay=max(0.0, float(PERSISTENT_SUBSCRIPTION_MAX_ACK_DELAY_SECONDS)),
                stopping_grace=max(0.0, float(PERSISTENT_SUBSCRIPTION_STOPPING_GRACE_SECONDS)),
            )
            _set_projection_subscription(subscription)
            for event in subscription:
                if _projection_stop_event.is_set():
                    break
                event_key = f"{getattr(event, 'stream_name', '')}:{int(getattr(event, 'stream_position', -1))}"
                with SessionLocal() as db:
                    should_ack = False
                    try:
                        _project_recorded_event(db, event)
                        db.commit()
                        _projection_event_failures.pop(event_key, None)
                        should_ack = True
                    except IntegrityError as exc:
                        db.rollback()
                        if _is_duplicate_projection_error(exc):
                            _projection_event_failures.pop(event_key, None)
                            should_ack = True
                        else:
                            failures = int(_projection_event_failures.get(event_key, 0)) + 1
                            _projection_event_failures[event_key] = failures
                            if failures >= max(1, int(PERSISTENT_SUBSCRIPTION_READ_MODEL_MAX_EVENT_RETRIES)):
                                logger.error(
                                    "Kurrent projection event failed too many times; acknowledging to unblock stream. "
                                    "event=%s failures=%s error=%s",
                                    event_key,
                                    failures,
                                    exc,
                                )
                                _projection_event_failures.pop(event_key, None)
                                should_ack = True
                            else:
                                logger.warning(
                                    "Kurrent projection event failed, retrying event: %s (attempt %s/%s)",
                                    exc,
                                    failures,
                                    max(1, int(PERSISTENT_SUBSCRIPTION_READ_MODEL_MAX_EVENT_RETRIES)),
                                )
                                subscription.nack(event, "retry")
                                continue
                    except Exception as exc:
                        db.rollback()
                        failures = int(_projection_event_failures.get(event_key, 0)) + 1
                        _projection_event_failures[event_key] = failures
                        if failures >= max(1, int(PERSISTENT_SUBSCRIPTION_READ_MODEL_MAX_EVENT_RETRIES)):
                            logger.error(
                                "Kurrent projection event failed too many times; acknowledging to unblock stream. "
                                "event=%s failures=%s error=%s",
                                event_key,
                                failures,
                                exc,
                            )
                            _projection_event_failures.pop(event_key, None)
                            should_ack = True
                        else:
                            logger.warning(
                                "Kurrent projection event failed, retrying event: %s (attempt %s/%s)",
                                exc,
                                failures,
                                max(1, int(PERSISTENT_SUBSCRIPTION_READ_MODEL_MAX_EVENT_RETRIES)),
                            )
                            subscription.nack(event, "retry")
                            continue
                if should_ack:
                    subscription.ack(event)
        except Exception as exc:
            logger.warning("Kurrent projection worker retrying after error: %s", exc)
            _projection_stop_event.wait(max(0.2, float(PERSISTENT_SUBSCRIPTION_RETRY_BACKOFF_SECONDS)))
        finally:
            _set_projection_subscription(None)
            if subscription is not None:
                try:
                    subscription.stop()
                except Exception:
                    pass


def _set_projection_subscription(subscription: Any | None) -> None:
    global _projection_subscription
    with _projection_subscription_lock:
        _projection_subscription = subscription


def _stop_projection_subscription() -> None:
    with _projection_subscription_lock:
        subscription = _projection_subscription
    if subscription is None:
        return
    try:
        subscription.stop()
    except Exception:
        pass


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
    _stop_projection_subscription()
    global _projection_thread
    if _projection_thread and _projection_thread.is_alive():
        _projection_thread.join(timeout=3)
    _projection_thread = None
