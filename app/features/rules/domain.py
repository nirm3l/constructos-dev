from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.aggregates import AggregateRoot

EVENT_CREATED = "ProjectRuleCreated"
EVENT_UPDATED = "ProjectRuleUpdated"
EVENT_DELETED = "ProjectRuleDeleted"

MUTATION_EVENTS = {EVENT_UPDATED, EVENT_DELETED}


class ProjectRuleAggregate(AggregateRoot):
    aggregate_type = "ProjectRule"

    def apply(self, *, event_type: str, payload: Mapping[str, Any]) -> None:
        if event_type == EVENT_CREATED:
            self.workspace_id = str(payload.get("workspace_id") or "")
            self.project_id = str(payload.get("project_id") or "")
            self.title = str(payload.get("title") or "")
            self.body = str(payload.get("body") or "")
            self.created_by = str(payload.get("created_by") or "")
            self.updated_by = str(payload.get("updated_by") or "")
            self.is_deleted = bool(payload.get("is_deleted", False))
            return

        if event_type == EVENT_UPDATED:
            for key, value in dict(payload).items():
                setattr(self, key, value)
            return

        if event_type == EVENT_DELETED:
            self.is_deleted = True
            updated_by = payload.get("updated_by")
            if updated_by is not None:
                self.updated_by = str(updated_by)
            return

        raise ValueError(f"Unknown event type: {event_type}")

    def create(
        self,
        *,
        workspace_id: str,
        project_id: str,
        title: str,
        body: str,
        created_by: str,
    ) -> None:
        self.record_event(
            event_type=EVENT_CREATED,
            payload={
                "workspace_id": workspace_id,
                "project_id": project_id,
                "title": title,
                "body": body,
                "created_by": created_by,
                "updated_by": created_by,
                "is_deleted": False,
            },
        )

    def update(self, *, changes: dict[str, Any], updated_by: str) -> None:
        payload = dict(changes)
        payload["updated_by"] = updated_by
        self.record_event(event_type=EVENT_UPDATED, payload=payload)

    def delete(self, *, updated_by: str) -> None:
        if bool(getattr(self, "is_deleted", False)):
            raise ValueError("Project rule already deleted")
        self.record_event(event_type=EVENT_DELETED, payload={"updated_by": updated_by})
