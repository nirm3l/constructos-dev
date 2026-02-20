from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.aggregates import AggregateRoot

EVENT_CREATED = "SpecificationCreated"
EVENT_UPDATED = "SpecificationUpdated"
EVENT_ARCHIVED = "SpecificationArchived"
EVENT_RESTORED = "SpecificationRestored"
EVENT_DELETED = "SpecificationDeleted"

MUTATION_EVENTS = {EVENT_UPDATED, EVENT_ARCHIVED, EVENT_RESTORED, EVENT_DELETED}


class SpecificationAggregate(AggregateRoot):
    aggregate_type = "Specification"

    def apply(self, *, event_type: str, payload: Mapping[str, Any]) -> None:
        if event_type == EVENT_CREATED:
            self.workspace_id = str(payload.get("workspace_id") or "")
            self.project_id = str(payload.get("project_id") or "")
            self.title = str(payload.get("title") or "")
            self.body = str(payload.get("body") or "")
            self.status = str(payload.get("status") or "Draft")
            self.tags = list(payload.get("tags") or [])
            self.external_refs = list(payload.get("external_refs") or [])
            self.attachment_refs = list(payload.get("attachment_refs") or [])
            self.created_by = str(payload.get("created_by") or "")
            self.updated_by = str(payload.get("updated_by") or "")
            self.archived = bool(payload.get("archived", False))
            self.is_deleted = bool(payload.get("is_deleted", False))
            return

        if event_type == EVENT_UPDATED:
            for key, value in dict(payload).items():
                setattr(self, key, value)
            return

        if event_type == EVENT_ARCHIVED:
            self.archived = True
            self.status = "Archived"
            updated_by = payload.get("updated_by")
            if updated_by is not None:
                self.updated_by = str(updated_by)
            return

        if event_type == EVENT_RESTORED:
            self.archived = False
            if str(getattr(self, "status", "") or "") == "Archived":
                self.status = "Ready"
            updated_by = payload.get("updated_by")
            if updated_by is not None:
                self.updated_by = str(updated_by)
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
        status: str,
        tags: list[str],
        external_refs: list[dict[str, Any]],
        attachment_refs: list[dict[str, Any]],
        created_by: str,
    ) -> None:
        self.record_event(
            event_type=EVENT_CREATED,
            payload={
                "workspace_id": workspace_id,
                "project_id": project_id,
                "title": title,
                "body": body,
                "status": status,
                "tags": tags,
                "external_refs": external_refs,
                "attachment_refs": attachment_refs,
                "archived": status == "Archived",
                "is_deleted": False,
                "created_by": created_by,
                "updated_by": created_by,
            },
        )

    def update(self, *, changes: dict[str, Any], updated_by: str) -> None:
        payload = dict(changes)
        payload["updated_by"] = updated_by
        self.record_event(
            event_type=EVENT_UPDATED,
            payload=payload,
        )

    def archive(self, *, updated_by: str) -> None:
        if bool(getattr(self, "archived", False)):
            raise ValueError("Specification already archived")
        self.record_event(event_type=EVENT_ARCHIVED, payload={"updated_by": updated_by})

    def restore_archived(self, *, updated_by: str) -> None:
        if not bool(getattr(self, "archived", False)):
            raise ValueError("Specification is not archived")
        self.record_event(event_type=EVENT_RESTORED, payload={"updated_by": updated_by})

    def delete(self, *, updated_by: str) -> None:
        if bool(getattr(self, "is_deleted", False)):
            raise ValueError("Specification already deleted")
        self.record_event(event_type=EVENT_DELETED, payload={"updated_by": updated_by})
