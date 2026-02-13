from __future__ import annotations

from eventsourcing.domain import Aggregate, event


class NotificationAggregate(Aggregate):
    INITIAL_VERSION = 0

    @event("Created")
    def __init__(self, *, user_id: str, message: str) -> None:
        self.user_id = user_id
        self.message = message
        self.is_read = False

    @event("MarkedRead")
    def marked_read(self, *, notification_id: str, user_id: str) -> None:
        _ = (notification_id, user_id)
        self.is_read = True


EVENT_CREATED = "NotificationCreated"
EVENT_MARKED_READ = "NotificationMarkedRead"
