from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event


class UserAggregate(Aggregate):
    INITIAL_VERSION = 0

    @event("PreferencesUpdated")
    def preferences_updated(self, data: dict[str, Any]) -> None:
        _ = data


EVENT_PREFERENCES_UPDATED = "UserPreferencesUpdated"
