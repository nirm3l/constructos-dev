from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.aggregates import AggregateRoot


EVENT_CREATED = "NoteCreated"
EVENT_UPDATED = "NoteUpdated"
EVENT_ARCHIVED = "NoteArchived"
EVENT_RESTORED = "NoteRestored"
EVENT_PINNED = "NotePinned"
EVENT_UNPINNED = "NoteUnpinned"
EVENT_DELETED = "NoteDeleted"

MUTATION_EVENTS = {
    EVENT_UPDATED,
    EVENT_ARCHIVED,
    EVENT_RESTORED,
    EVENT_PINNED,
    EVENT_UNPINNED,
    EVENT_DELETED,
}


class NoteAggregate(AggregateRoot):
    aggregate_type = "Note"

    def apply(self, *, event_type: str, payload: Mapping[str, Any]) -> None:
        if event_type == EVENT_CREATED:
            self.workspace_id = str(payload.get("workspace_id") or "")
            self.project_id = payload.get("project_id")
            self.task_id = payload.get("task_id")
            self.specification_id = payload.get("specification_id")
            self.title = str(payload.get("title") or "")
            self.body = str(payload.get("body") or "")
            self.tags = list(payload.get("tags") or [])
            self.external_refs = list(payload.get("external_refs") or [])
            self.attachment_refs = list(payload.get("attachment_refs") or [])
            self.pinned = bool(payload.get("pinned", False))
            self.archived = bool(payload.get("archived", False))
            self.is_deleted = bool(payload.get("is_deleted", False))
            self.created_by = str(payload.get("created_by") or "")
            self.updated_by = str(payload.get("updated_by") or "")
            self.created_at = payload.get("created_at")
            return

        if event_type == EVENT_UPDATED:
            for key, value in dict(payload).items():
                setattr(self, key, value)
            return

        if event_type == EVENT_ARCHIVED:
            self.archived = True
            updated_by = payload.get("updated_by")
            if updated_by is not None:
                self.updated_by = str(updated_by)
            return

        if event_type == EVENT_RESTORED:
            self.archived = False
            updated_by = payload.get("updated_by")
            if updated_by is not None:
                self.updated_by = str(updated_by)
            return

        if event_type == EVENT_PINNED:
            self.pinned = True
            updated_by = payload.get("updated_by")
            if updated_by is not None:
                self.updated_by = str(updated_by)
            return

        if event_type == EVENT_UNPINNED:
            self.pinned = False
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

