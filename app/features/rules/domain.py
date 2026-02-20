from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event

EVENT_CREATED = "ProjectRuleCreated"
EVENT_UPDATED = "ProjectRuleUpdated"
EVENT_DELETED = "ProjectRuleDeleted"

MUTATION_EVENTS = {EVENT_UPDATED, EVENT_DELETED}


class ProjectRuleAggregate(Aggregate):
    aggregate_type = "ProjectRule"

    @event("Created")
    def __init__(
        self,
        id: Any,
        workspace_id: str,
        project_id: str,
        title: str,
        body: str,
        created_by: str,
    ) -> None:
        _ = id
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.title = title
        self.body = body
        self.created_by = created_by
        self.updated_by = created_by
        self.is_deleted = False

    @event("Updated")
    def update(self, changes: dict[str, Any], updated_by: str) -> None:
        for key, value in changes.items():
            setattr(self, key, value)
        self.updated_by = updated_by

    @event("Deleted")
    def delete(self, updated_by: str) -> None:
        if bool(getattr(self, "is_deleted", False)):
            raise ValueError("Project rule already deleted")
        self.is_deleted = True
        self.updated_by = updated_by
