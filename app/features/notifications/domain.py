from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event

EVENT_CREATED = "NotificationCreated"
EVENT_MARKED_READ = "NotificationMarkedRead"
EVENT_MARKED_UNREAD = "NotificationMarkedUnread"


class NotificationAggregate(Aggregate):
    aggregate_type = "Notification"

    @event("Created")
    def __init__(
        self,
        id: Any,
        user_id: str,
        message: str,
        workspace_id: str | None = None,
        project_id: str | None = None,
        task_id: str | None = None,
        note_id: str | None = None,
        specification_id: str | None = None,
        notification_type: str | None = None,
        severity: str | None = None,
        dedupe_key: str | None = None,
        payload_json: str | None = None,
        source_event: str | None = None,
    ) -> None:
        _ = id
        self.user_id = user_id
        self.message = message
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.task_id = task_id
        self.note_id = note_id
        self.specification_id = specification_id
        self.notification_type = notification_type
        self.severity = severity
        self.dedupe_key = dedupe_key
        self.payload_json = payload_json
        self.source_event = source_event
        self.is_read = False

    @event("MarkedRead")
    def mark_read(self, notification_id: str, user_id: str) -> None:
        _ = (notification_id, user_id)
        self.is_read = True

    @event("MarkedUnread")
    def mark_unread(self, notification_id: str, user_id: str) -> None:
        _ = (notification_id, user_id)
        self.is_read = False
