from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event

EVENT_CREATED = "NotificationCreated"
EVENT_MARKED_READ = "NotificationMarkedRead"


class NotificationAggregate(Aggregate):
    aggregate_type = "Notification"

    @event("Created")
    def __init__(self, id: Any, user_id: str, message: str) -> None:
        _ = id
        self.user_id = user_id
        self.message = message
        self.is_read = False

    @event("MarkedRead")
    def mark_read(self, notification_id: str, user_id: str) -> None:
        _ = (notification_id, user_id)
        self.is_read = True
