from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, TypeVar
from uuid import UUID

from eventsourcing.domain import Aggregate
from sqlalchemy.orm import Session

from .contracts import EventEnvelope

_AggregateT = TypeVar("_AggregateT", bound=Aggregate)
_RESERVED_EVENT_KEYS = {"originator_id", "originator_version", "originator_topic", "timestamp"}


def coerce_originator_id(value: str) -> UUID:
    text = str(value or "").strip()
    if not text:
        raise ValueError("aggregate_id cannot be empty")
    return UUID(text)


def initialize_aggregate(
    aggregate_cls: type[_AggregateT],
    *,
    aggregate_id: str,
    version: int = 0,
    state: Mapping[str, Any] | None = None,
) -> _AggregateT:
    aggregate = object.__new__(aggregate_cls)
    aggregate.__base_init__(
        originator_id=coerce_originator_id(aggregate_id),
        originator_version=int(version),
        timestamp=datetime.now(timezone.utc),
    )
    for key, value in dict(state or {}).items():
        if key in {"id", "version", "created_on", "modified_on"}:
            continue
        try:
            setattr(aggregate, key, value)
        except AttributeError:
            # Ignore read-only aggregate attributes managed by eventsourcing internals.
            continue
    return aggregate


def _aggregate_type_for(aggregate: Aggregate) -> str:
    aggregate_type = str(getattr(aggregate, "aggregate_type", "") or "").strip()
    if aggregate_type:
        return aggregate_type
    class_name = aggregate.__class__.__name__
    if class_name.endswith("Aggregate"):
        class_name = class_name[: -len("Aggregate")]
    return class_name


def _event_type_for(aggregate: Aggregate, event: Any) -> str:
    prefix = str(getattr(aggregate, "event_type_prefix", "") or "").strip() or _aggregate_type_for(aggregate)
    return f"{prefix}{event.__class__.__name__}"


def _payload_for(event: Any) -> dict[str, Any]:
    payload = dict(getattr(event, "__dict__", {}) or {})
    for key in _RESERVED_EVENT_KEYS:
        payload.pop(key, None)
    if isinstance(payload.get("changes"), dict):
        changes = dict(payload.pop("changes"))
        payload.update(changes)
    return payload


class AggregateEventRepository:
    def __init__(
        self,
        db: Session,
        *,
        append_event_fn: Callable[..., EventEnvelope] | None = None,
        rebuild_state_fn: Callable[..., tuple[dict[str, Any], int]] | None = None,
    ):
        self.db = db
        if append_event_fn is None or rebuild_state_fn is None:
            from .eventing import append_event as default_append_event, rebuild_state as default_rebuild_state

            self._append_event = append_event_fn or default_append_event
            self._rebuild_state = rebuild_state_fn or default_rebuild_state
        else:
            self._append_event = append_event_fn
            self._rebuild_state = rebuild_state_fn

    def load_with_class(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        aggregate_cls: type[_AggregateT],
    ) -> _AggregateT:
        state, version = self._rebuild_state(self.db, aggregate_type, aggregate_id)
        return initialize_aggregate(
            aggregate_cls,
            aggregate_id=aggregate_id,
            version=version,
            state=state,
        )

    def persist(
        self,
        aggregate: Aggregate,
        *,
        base_metadata: Mapping[str, Any],
        expected_version: int | None = None,
    ) -> list[EventEnvelope]:
        pending = list(getattr(aggregate, "pending_events", []) or [])
        if not pending:
            return []

        aggregate_type = _aggregate_type_for(aggregate)
        first_expected = int(expected_version) if expected_version is not None else int(pending[0].originator_version) - 1

        appended: list[EventEnvelope] = []
        for idx, event in enumerate(pending):
            appended.append(
                self._append_event(
                    self.db,
                    aggregate_type=aggregate_type,
                    aggregate_id=str(aggregate.id),
                    event_type=_event_type_for(aggregate, event),
                    payload=_payload_for(event),
                    metadata=dict(base_metadata),
                    expected_version=first_expected if idx == 0 else None,
                )
            )

        # Clear pending events only after all writes succeed.
        aggregate.collect_events()
        return appended
