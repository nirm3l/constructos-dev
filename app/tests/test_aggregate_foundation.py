from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event

from shared.aggregates import AggregateEventRepository, initialize_aggregate
from shared.contracts import EventEnvelope


class DemoAggregate(Aggregate):
    aggregate_type = "Demo"

    @event("Created")
    def __init__(self, *, id: Any, title: str) -> None:
        _ = id
        self.title = title
        self.archived = False

    @event("Renamed")
    def rename(self, *, title: str) -> None:
        self.title = title

    @event("Archived")
    def archive(self) -> None:
        self.archived = True


def test_initialize_aggregate_restores_state_and_supports_new_events() -> None:
    aggregate_id = "11111111-1111-1111-1111-111111111111"
    aggregate = initialize_aggregate(
        DemoAggregate,
        aggregate_id=aggregate_id,
        version=3,
        state={"title": "Existing", "archived": False},
    )

    assert str(aggregate.id) == aggregate_id
    assert aggregate.version == 3
    assert aggregate.title == "Existing"
    assert aggregate.archived is False
    assert list(aggregate.pending_events) == []

    aggregate.rename(title="Renamed")

    assert aggregate.version == 4
    assert len(list(aggregate.pending_events)) == 1
    assert aggregate.pending_events[0].originator_version == 4


def test_aggregate_repository_load_with_class_uses_rebuild_state() -> None:
    db = object()
    aggregate_id = "22222222-2222-2222-2222-222222222222"

    def fake_rebuild_state(_db, aggregate_type: str, aggregate_id_arg: str) -> tuple[dict[str, Any], int]:
        assert _db is db
        assert aggregate_type == "Demo"
        assert aggregate_id_arg == aggregate_id
        return {"title": "Existing", "archived": False}, 4

    repo = AggregateEventRepository(
        db,
        rebuild_state_fn=fake_rebuild_state,
    )
    aggregate = repo.load_with_class(
        aggregate_type="Demo",
        aggregate_id=aggregate_id,
        aggregate_cls=DemoAggregate,
    )

    assert str(aggregate.id) == aggregate_id
    assert aggregate.title == "Existing"
    assert aggregate.archived is False
    assert aggregate.version == 4
    assert list(aggregate.pending_events) == []


def test_aggregate_repository_persist_appends_events_in_order() -> None:
    db = object()
    calls: list[dict[str, Any]] = []

    def fake_append_event(
        _db,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any],
        expected_version: int | None = None,
    ) -> EventEnvelope:
        assert _db is db
        calls.append(
            {
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "event_type": event_type,
                "payload": dict(payload),
                "metadata": dict(metadata),
                "expected_version": expected_version,
            }
        )
        return EventEnvelope(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            version=len(calls),
            event_type=event_type,
            payload=dict(payload),
            metadata=dict(metadata),
        )

    aggregate = initialize_aggregate(
        DemoAggregate,
        aggregate_id="33333333-3333-3333-3333-333333333333",
        version=7,
        state={"title": "Before", "archived": False},
    )
    aggregate.rename(title="After rename")
    aggregate.archive()

    repo = AggregateEventRepository(db, append_event_fn=fake_append_event)
    emitted = repo.persist(
        aggregate,
        base_metadata={"actor_id": "user-1", "workspace_id": "ws-1"},
    )

    assert len(emitted) == 2
    assert [item["event_type"] for item in calls] == ["DemoRenamed", "DemoArchived"]
    assert calls[0]["expected_version"] == 7
    assert calls[1]["expected_version"] is None
    assert calls[0]["metadata"]["actor_id"] == "user-1"
    assert calls[1]["metadata"]["workspace_id"] == "ws-1"
    assert list(aggregate.pending_events) == []
