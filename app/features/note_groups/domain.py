from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event

EVENT_CREATED = "NoteGroupCreated"
EVENT_UPDATED = "NoteGroupUpdated"
EVENT_REORDERED = "NoteGroupReordered"
EVENT_DELETED = "NoteGroupDeleted"

MUTATION_EVENTS = {EVENT_UPDATED, EVENT_REORDERED, EVENT_DELETED}


class NoteGroupAggregate(Aggregate):
    aggregate_type = "NoteGroup"

    @event("Created")
    def __init__(
        self,
        id: Any,
        workspace_id: str,
        project_id: str,
        name: str,
        description: str,
        color: str | None,
        order_index: int,
    ) -> None:
        _ = id
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.name = name
        self.description = description
        self.color = color
        self.order_index = order_index
        self.is_deleted = False

    @event("Updated")
    def update(self, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            setattr(self, key, value)

    @event("Reordered")
    def reorder(self, order_index: int) -> None:
        self.order_index = order_index

    @event("Deleted")
    def delete(self) -> None:
        self.is_deleted = True
