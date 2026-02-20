from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event

EVENT_CREATED = "SpecificationCreated"
EVENT_UPDATED = "SpecificationUpdated"
EVENT_ARCHIVED = "SpecificationArchived"
EVENT_RESTORED = "SpecificationRestored"
EVENT_DELETED = "SpecificationDeleted"

MUTATION_EVENTS = {EVENT_UPDATED, EVENT_ARCHIVED, EVENT_RESTORED, EVENT_DELETED}


class SpecificationAggregate(Aggregate):
    aggregate_type = "Specification"

    @event("Created")
    def __init__(
        self,
        id: Any,
        workspace_id: str,
        project_id: str,
        title: str,
        body: str,
        status: str,
        tags: list[str],
        external_refs: list[dict[str, Any]],
        attachment_refs: list[dict[str, Any]],
        created_by: str,
    ) -> None:
        _ = id
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.title = title
        self.body = body
        self.status = status
        self.tags = tags
        self.external_refs = external_refs
        self.attachment_refs = attachment_refs
        self.archived = status == "Archived"
        self.is_deleted = False
        self.created_by = created_by
        self.updated_by = created_by

    @event("Updated")
    def update(self, changes: dict[str, Any], updated_by: str) -> None:
        for key, value in changes.items():
            setattr(self, key, value)
        self.updated_by = updated_by

    @event("Archived")
    def archive(self, updated_by: str) -> None:
        if bool(getattr(self, "archived", False)):
            raise ValueError("Specification already archived")
        self.archived = True
        self.status = "Archived"
        self.updated_by = updated_by

    @event("Restored")
    def restore_archived(self, updated_by: str) -> None:
        if not bool(getattr(self, "archived", False)):
            raise ValueError("Specification is not archived")
        self.archived = False
        if str(getattr(self, "status", "") or "") == "Archived":
            self.status = "Ready"
        self.updated_by = updated_by

    @event("Deleted")
    def delete(self, updated_by: str) -> None:
        if bool(getattr(self, "is_deleted", False)):
            raise ValueError("Specification already deleted")
        self.is_deleted = True
        self.updated_by = updated_by
