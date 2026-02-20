from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, TypeVar

from sqlalchemy.orm import Session

from .contracts import EventEnvelope


@dataclass(frozen=True, slots=True)
class PendingDomainEvent:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class AggregateRoot(ABC):
    aggregate_type: str = ""

    def __init__(self, aggregate_id: str, *, version: int = 0):
        self.id = str(aggregate_id)
        self.version = int(version)
        self._loaded_version = int(version)
        self._pending_events: list[PendingDomainEvent] = []

    @classmethod
    def from_state(
        cls,
        aggregate_id: str,
        state: Mapping[str, Any],
        *,
        version: int,
    ) -> AggregateRoot:
        aggregate = cls.__new__(cls)
        AggregateRoot.__init__(aggregate, aggregate_id=aggregate_id, version=version)
        aggregate.restore(state)
        return aggregate

    @property
    def loaded_version(self) -> int:
        return int(self._loaded_version)

    @property
    def has_pending_events(self) -> bool:
        return bool(self._pending_events)

    @property
    def pending_events(self) -> list[PendingDomainEvent]:
        return [
            PendingDomainEvent(
                event_type=event.event_type,
                payload=dict(event.payload),
                metadata=dict(event.metadata),
            )
            for event in self._pending_events
        ]

    def restore(self, state: Mapping[str, Any]) -> None:
        for key, value in dict(state).items():
            setattr(self, key, value)

    @abstractmethod
    def apply(self, *, event_type: str, payload: Mapping[str, Any]) -> None:
        ...

    def record_event(
        self,
        *,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        normalized_payload = dict(payload or {})
        normalized_metadata = dict(metadata or {})
        self.apply(event_type=event_type, payload=normalized_payload)
        self.version += 1
        self._pending_events.append(
            PendingDomainEvent(
                event_type=event_type,
                payload=normalized_payload,
                metadata=normalized_metadata,
            )
        )

    def clear_pending_events(self) -> None:
        self._pending_events.clear()
        self._loaded_version = int(self.version)

    def _require_aggregate_type(self) -> str:
        aggregate_type = str(self.aggregate_type or "").strip()
        if not aggregate_type:
            raise ValueError(f"{self.__class__.__name__} must define aggregate_type")
        return aggregate_type


_AggregateT = TypeVar("_AggregateT", bound=AggregateRoot)


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

    def load(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        factory: Callable[[str, Mapping[str, Any], int], _AggregateT],
    ) -> _AggregateT:
        state, version = self._rebuild_state(self.db, aggregate_type, aggregate_id)
        return factory(aggregate_id, state, version)

    def load_with_class(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        aggregate_cls: type[_AggregateT],
    ) -> _AggregateT:
        return self.load(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            factory=lambda aid, state, version: aggregate_cls.from_state(
                aid,
                state,
                version=version,
            ),
        )

    def persist(
        self,
        aggregate: AggregateRoot,
        *,
        base_metadata: Mapping[str, Any],
        expected_version: int | None = None,
    ) -> list[EventEnvelope]:
        pending = aggregate.pending_events
        if not pending:
            return []

        aggregate_type = aggregate._require_aggregate_type()
        first_expected = aggregate.loaded_version if expected_version is None else int(expected_version)

        appended: list[EventEnvelope] = []
        for idx, event in enumerate(pending):
            metadata = dict(base_metadata)
            metadata.update(event.metadata)
            appended.append(
                self._append_event(
                    self.db,
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate.id,
                    event_type=event.event_type,
                    payload=dict(event.payload),
                    metadata=metadata,
                    expected_version=first_expected if idx == 0 else None,
                )
            )

        aggregate.clear_pending_events()
        return appended
