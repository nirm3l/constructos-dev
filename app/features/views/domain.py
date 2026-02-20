from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.aggregates import AggregateRoot


EVENT_CREATED = "SavedViewCreated"


class SavedViewAggregate(AggregateRoot):
    aggregate_type = "SavedView"

    def apply(self, *, event_type: str, payload: Mapping[str, Any]) -> None:
        if event_type != EVENT_CREATED:
            raise ValueError(f"Unknown event type: {event_type}")
        self.workspace_id = str(payload.get("workspace_id") or "")
        project_id = payload.get("project_id")
        self.project_id = str(project_id) if project_id is not None else None
        user_id = payload.get("user_id")
        self.user_id = str(user_id) if user_id is not None else None
        self.name = str(payload.get("name") or "")
        self.shared = bool(payload.get("shared", False))
        self.filters = dict(payload.get("filters") or {})

    def create(
        self,
        *,
        workspace_id: str,
        project_id: str | None,
        user_id: str | None,
        name: str,
        shared: bool,
        filters: dict[str, Any],
    ) -> None:
        self.record_event(
            event_type=EVENT_CREATED,
            payload={
                "workspace_id": workspace_id,
                "project_id": project_id,
                "user_id": user_id,
                "name": name,
                "shared": shared,
                "filters": dict(filters),
            },
        )
