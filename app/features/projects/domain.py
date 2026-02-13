from __future__ import annotations

from eventsourcing.domain import Aggregate, event


class ProjectAggregate(Aggregate):
    INITIAL_VERSION = 0

    @event("Created")
    def __init__(
        self,
        *,
        workspace_id: str,
        name: str,
        description: str,
        custom_statuses: list[str],
        status: str = "Active",
    ) -> None:
        self.workspace_id = workspace_id
        self.name = name
        self.description = description
        self.custom_statuses = custom_statuses
        self.status = status
        self.is_deleted = False

    @event("Deleted")
    def deleted(self, moved_tasks: int = 0) -> None:
        _ = moved_tasks
        self.is_deleted = True


EVENT_CREATED = "ProjectCreated"
EVENT_DELETED = "ProjectDeleted"
