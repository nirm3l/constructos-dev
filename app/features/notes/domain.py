from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event

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


class NoteAggregate(Aggregate):
    aggregate_type = "Note"

    @event("Created")
    def __init__(
        self,
        id: Any,
        workspace_id: str,
        project_id: str | None,
        note_group_id: str | None,
        task_id: str | None,
        specification_id: str | None,
        title: str,
        body: str,
        tags: list[str],
        external_refs: list[dict[str, Any]],
        attachment_refs: list[dict[str, Any]],
        pinned: bool,
        archived: bool,
        created_by: str,
        updated_by: str,
        created_at: str | None,
    ) -> None:
        _ = id
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.note_group_id = note_group_id
        self.task_id = task_id
        self.specification_id = specification_id
        self.title = title
        self.body = body
        self.tags = tags
        self.external_refs = external_refs
        self.attachment_refs = attachment_refs
        self.pinned = pinned
        self.archived = archived
        self.is_deleted = False
        self.created_by = created_by
        self.updated_by = updated_by
        self.created_at = created_at

    @event("Updated")
    def update(self, changes: dict[str, Any], updated_by: str) -> None:
        for key, value in changes.items():
            setattr(self, key, value)
        self.updated_by = updated_by

    @event("Archived")
    def archive(self, updated_by: str) -> None:
        self.archived = True
        self.updated_by = updated_by

    @event("Restored")
    def restore(self, updated_by: str) -> None:
        self.archived = False
        self.updated_by = updated_by

    @event("Pinned")
    def pin(self, updated_by: str) -> None:
        self.pinned = True
        self.updated_by = updated_by

    @event("Unpinned")
    def unpin(self, updated_by: str) -> None:
        self.pinned = False
        self.updated_by = updated_by

    @event("Deleted")
    def delete(self, updated_by: str) -> None:
        self.is_deleted = True
        self.updated_by = updated_by
