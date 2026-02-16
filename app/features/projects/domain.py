from __future__ import annotations

from typing import Any

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
        external_refs: list[dict[str, Any]],
        attachment_refs: list[dict[str, Any]],
        status: str = "Active",
    ) -> None:
        self.workspace_id = workspace_id
        self.name = name
        self.description = description
        self.custom_statuses = custom_statuses
        self.external_refs = external_refs
        self.attachment_refs = attachment_refs
        self.status = status
        self.is_deleted = False

    @event("Deleted")
    def deleted(self, moved_tasks: int = 0) -> None:
        _ = moved_tasks
        self.is_deleted = True

    @event("Updated")
    def updated(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        external_refs: list[dict[str, Any]] | None = None,
        attachment_refs: list[dict[str, Any]] | None = None,
    ) -> None:
        if name is not None:
            self.name = name
        if description is not None:
            self.description = description
        if external_refs is not None:
            self.external_refs = external_refs
        if attachment_refs is not None:
            self.attachment_refs = attachment_refs


EVENT_CREATED = "ProjectCreated"
EVENT_DELETED = "ProjectDeleted"
EVENT_UPDATED = "ProjectUpdated"
