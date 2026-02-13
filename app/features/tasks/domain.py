from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event


class TaskAggregate(Aggregate):
    INITIAL_VERSION = 0

    @event("Created")
    def __init__(
        self,
        *,
        workspace_id: str,
        project_id: str | None,
        title: str,
        description: str,
        status: str,
        priority: str,
        due_date: str | None,
        assignee_id: str | None,
        labels: list[str],
        subtasks: list[dict[str, Any]],
        attachments: list[dict[str, Any]],
        recurring_rule: str | None,
        order_index: int,
    ) -> None:
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.title = title
        self.description = description
        self.status = status
        self.priority = priority
        self.due_date = due_date
        self.assignee_id = assignee_id
        self.labels = labels
        self.subtasks = subtasks
        self.attachments = attachments
        self.recurring_rule = recurring_rule
        self.order_index = order_index
        self.archived = False
        self.is_deleted = False
        self.completed_at = None

    @event("Updated")
    def updated(self, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            setattr(self, key, value)

    @event("Reordered")
    def reordered(self, *, order_index: int, status: str | None) -> None:
        self.order_index = order_index
        if status:
            self.status = status

    @event("Completed")
    def completed(self, completed_at: str) -> None:
        self.status = "Done"
        self.completed_at = completed_at

    @event("Reopened")
    def reopened(self, status: str = "To do") -> None:
        self.status = status
        self.completed_at = None

    @event("Archived")
    def archived_event(self) -> None:
        self.archived = True

    @event("Restored")
    def restored(self) -> None:
        self.archived = False

    @event("Deleted")
    def deleted(self) -> None:
        self.is_deleted = True

    @event("MovedToInbox")
    def moved_to_inbox(self, from_project_id: str | None = None) -> None:
        _ = from_project_id
        self.project_id = None

    @event("CommentAdded")
    def comment_added(self, *, task_id: str, user_id: str, body: str) -> None:
        _ = (task_id, user_id, body)

    @event("WatchToggled")
    def watch_toggled(self, *, task_id: str, user_id: str) -> None:
        _ = (task_id, user_id)


EVENT_CREATED = "TaskCreated"
EVENT_UPDATED = "TaskUpdated"
EVENT_REORDERED = "TaskReordered"
EVENT_COMPLETED = "TaskCompleted"
EVENT_REOPENED = "TaskReopened"
EVENT_ARCHIVED = "TaskArchived"
EVENT_RESTORED = "TaskRestored"
EVENT_DELETED = "TaskDeleted"
EVENT_MOVED_TO_INBOX = "TaskMovedToInbox"
EVENT_COMMENT_ADDED = "TaskCommentAdded"
EVENT_WATCH_TOGGLED = "TaskWatchToggled"

MUTATION_EVENTS = {
    EVENT_UPDATED,
    EVENT_REORDERED,
    EVENT_COMPLETED,
    EVENT_REOPENED,
    EVENT_ARCHIVED,
    EVENT_RESTORED,
    EVENT_DELETED,
    EVENT_MOVED_TO_INBOX,
}
