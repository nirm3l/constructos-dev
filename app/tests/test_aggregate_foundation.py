from __future__ import annotations

from typing import Any, Mapping

from shared.aggregates import AggregateEventRepository, AggregateRoot
from shared.contracts import EventEnvelope


class DemoAggregate(AggregateRoot):
    aggregate_type = "Demo"

    def apply(self, *, event_type: str, payload: Mapping[str, Any]) -> None:
        if event_type == "DemoCreated":
            self.title = str(payload.get("title") or "")
            self.archived = False
            return
        if event_type == "DemoRenamed":
            self.title = str(payload.get("title") or self.title)
            return
        if event_type == "DemoArchived":
            self.archived = True
            return
        raise ValueError(f"Unknown event type: {event_type}")


def test_aggregate_root_records_pending_events_and_versions() -> None:
    aggregate = DemoAggregate("demo-1")

    aggregate.record_event(
        event_type="DemoCreated",
        payload={"title": "Initial title"},
        metadata={"trace_id": "trace-1"},
    )
    aggregate.record_event(
        event_type="DemoArchived",
        payload={},
        metadata={"trace_id": "trace-2"},
    )

    assert aggregate.version == 2
    assert aggregate.loaded_version == 0
    assert aggregate.title == "Initial title"
    assert aggregate.archived is True
    assert aggregate.has_pending_events is True
    assert [event.event_type for event in aggregate.pending_events] == [
        "DemoCreated",
        "DemoArchived",
    ]


def test_aggregate_repository_load_with_class_uses_rebuild_state() -> None:
    db = object()

    def fake_rebuild_state(_db, aggregate_type: str, aggregate_id: str) -> tuple[dict[str, Any], int]:
        assert _db is db
        assert aggregate_type == "Demo"
        assert aggregate_id == "demo-existing"
        return {"title": "Existing", "archived": False}, 4

    repo = AggregateEventRepository(
        db,
        rebuild_state_fn=fake_rebuild_state,
    )
    aggregate = repo.load_with_class(
        aggregate_type="Demo",
        aggregate_id="demo-existing",
        aggregate_cls=DemoAggregate,
    )

    assert aggregate.id == "demo-existing"
    assert aggregate.title == "Existing"
    assert aggregate.archived is False
    assert aggregate.version == 4
    assert aggregate.loaded_version == 4
    assert aggregate.has_pending_events is False


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

    aggregate = DemoAggregate.from_state(
        "demo-2",
        {"title": "Before", "archived": False},
        version=7,
    )
    aggregate.record_event(
        event_type="DemoRenamed",
        payload={"title": "After rename"},
        metadata={"trace_id": "trace-rename"},
    )
    aggregate.record_event(
        event_type="DemoArchived",
        payload={},
    )

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
    assert calls[0]["metadata"]["trace_id"] == "trace-rename"
    assert calls[1]["metadata"]["workspace_id"] == "ws-1"
    assert aggregate.has_pending_events is False
    assert aggregate.loaded_version == aggregate.version
