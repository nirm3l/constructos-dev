from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event

EVENT_CREATED = "SavedViewCreated"


class SavedViewAggregate(Aggregate):
    aggregate_type = "SavedView"

    @event("Created")
    def __init__(
        self,
        id: Any,
        workspace_id: str,
        project_id: str | None,
        user_id: str | None,
        name: str,
        shared: bool,
        filters: dict[str, Any],
    ) -> None:
        _ = id
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.user_id = user_id
        self.name = name
        self.shared = shared
        self.filters = filters
