from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event


class NoteAggregate(Aggregate):
    INITIAL_VERSION = 0

    @event("Created")
    def __init__(
        self,
        *,
        workspace_id: str,
        project_id: str | None,
        task_id: str | None,
        title: str,
        body: str,
        tags: list[str],
        pinned: bool,
        archived: bool,
        created_by: str,
        updated_by: str,
    ) -> None:
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.task_id = task_id
        self.title = title
        self.body = body
        self.tags = tags
        self.pinned = pinned
        self.archived = archived
        self.is_deleted = False
        self.created_by = created_by
        self.updated_by = updated_by

    @event("Updated")
    def updated(self, changes: dict[str, Any]) -> None:
        for k, v in changes.items():
            setattr(self, k, v)

    @event("Archived")
    def archived_event(self) -> None:
        self.archived = True

    @event("Restored")
    def restored(self) -> None:
        self.archived = False

    @event("Pinned")
    def pinned_event(self) -> None:
        self.pinned = True

    @event("Unpinned")
    def unpinned_event(self) -> None:
        self.pinned = False

    @event("Deleted")
    def deleted(self) -> None:
        self.is_deleted = True


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

