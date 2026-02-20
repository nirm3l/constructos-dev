from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.aggregates import AggregateRoot


EVENT_CREATED = "NotificationCreated"
EVENT_MARKED_READ = "NotificationMarkedRead"


class NotificationAggregate(AggregateRoot):
    aggregate_type = "Notification"

    def apply(self, *, event_type: str, payload: Mapping[str, Any]) -> None:
        if event_type == EVENT_CREATED:
            self.user_id = str(payload.get("user_id") or "")
            self.message = str(payload.get("message") or "")
            self.is_read = bool(payload.get("is_read", False))
            return
        if event_type == EVENT_MARKED_READ:
            self.is_read = True
            return
        raise ValueError(f"Unknown event type: {event_type}")

    def create(self, *, user_id: str, message: str) -> None:
        self.record_event(
            event_type=EVENT_CREATED,
            payload={
                "user_id": user_id,
                "message": message,
                "is_read": False,
            },
        )

    def mark_read(self, *, notification_id: str, user_id: str) -> None:
        _ = (notification_id, user_id)
        self.record_event(event_type=EVENT_MARKED_READ, payload={"notification_id": notification_id, "user_id": user_id})
