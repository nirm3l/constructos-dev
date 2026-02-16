from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event


class SavedViewAggregate(Aggregate):
    INITIAL_VERSION = 0

    @event("Created")
    def __init__(
        self,
        *,
        workspace_id: str,
        project_id: str | None,
        user_id: str | None,
        name: str,
        shared: bool,
        filters: dict[str, Any],
    ) -> None:
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.user_id = user_id
        self.name = name
        self.shared = shared
        self.filters = filters


EVENT_CREATED = "SavedViewCreated"
