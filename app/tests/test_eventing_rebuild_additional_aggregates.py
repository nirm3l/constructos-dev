from __future__ import annotations

from shared.contracts import EventEnvelope
from shared.eventing_rebuild import (
    apply_notification_event,
    apply_saved_view_event,
    apply_user_event,
    rebuild_state,
)
from features.notifications.domain import (
    EVENT_CREATED as NOTIFICATION_EVENT_CREATED,
    EVENT_MARKED_READ as NOTIFICATION_EVENT_MARKED_READ,
    EVENT_MARKED_UNREAD as NOTIFICATION_EVENT_MARKED_UNREAD,
)
from features.users.domain import (
    EVENT_CREATED as USER_EVENT_CREATED,
    EVENT_DEACTIVATED as USER_EVENT_DEACTIVATED,
    EVENT_PREFERENCES_UPDATED as USER_EVENT_PREFERENCES_UPDATED,
    EVENT_WORKSPACE_ROLE_SET as USER_EVENT_WORKSPACE_ROLE_SET,
)
from features.views.domain import EVENT_CREATED as SAVED_VIEW_EVENT_CREATED


def _env(*, aggregate_type: str, aggregate_id: str, version: int, event_type: str, payload: dict, metadata: dict | None = None) -> EventEnvelope:
    return EventEnvelope(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        version=version,
        event_type=event_type,
        payload=payload,
        metadata=dict(metadata or {}),
    )


def test_apply_user_event_tracks_workspace_roles_and_preferences() -> None:
    state: dict = {}
    state = apply_user_event(
        state,
        _env(
            aggregate_type="User",
            aggregate_id="user-1",
            version=1,
            event_type=USER_EVENT_CREATED,
            payload={
                "username": "owner",
                "full_name": "Owner User",
                "user_type": "human",
                "workspace_id": "ws-1",
                "workspace_role": "Owner",
            },
        ),
    )
    state = apply_user_event(
        state,
        _env(
            aggregate_type="User",
            aggregate_id="user-1",
            version=2,
            event_type=USER_EVENT_WORKSPACE_ROLE_SET,
            payload={"workspace_id": "ws-2", "role": "Admin"},
        ),
    )
    state = apply_user_event(
        state,
        _env(
            aggregate_type="User",
            aggregate_id="user-1",
            version=3,
            event_type=USER_EVENT_PREFERENCES_UPDATED,
            payload={"theme": "dark", "timezone": "Europe/Sarajevo"},
        ),
    )
    state = apply_user_event(
        state,
        _env(
            aggregate_type="User",
            aggregate_id="user-1",
            version=4,
            event_type=USER_EVENT_DEACTIVATED,
            payload={"workspace_id": "ws-1"},
        ),
    )

    assert state["workspace_roles"] == {"ws-1": "Owner", "ws-2": "Admin"}
    assert state["theme"] == "dark"
    assert state["timezone"] == "Europe/Sarajevo"
    assert state["is_active"] is False


def test_apply_notification_event_toggles_read_state() -> None:
    state: dict = {}
    state = apply_notification_event(
        state,
        _env(
            aggregate_type="Notification",
            aggregate_id="notif-1",
            version=1,
            event_type=NOTIFICATION_EVENT_CREATED,
            payload={"user_id": "user-1", "message": "Hello"},
            metadata={"workspace_id": "ws-1"},
        ),
    )
    assert state["is_read"] is False
    state = apply_notification_event(
        state,
        _env(
            aggregate_type="Notification",
            aggregate_id="notif-1",
            version=2,
            event_type=NOTIFICATION_EVENT_MARKED_READ,
            payload={"notification_id": "notif-1", "user_id": "user-1"},
        ),
    )
    assert state["is_read"] is True
    state = apply_notification_event(
        state,
        _env(
            aggregate_type="Notification",
            aggregate_id="notif-1",
            version=3,
            event_type=NOTIFICATION_EVENT_MARKED_UNREAD,
            payload={"notification_id": "notif-1", "user_id": "user-1"},
        ),
    )
    assert state["is_read"] is False


def test_apply_saved_view_event_sets_filters() -> None:
    state: dict = {}
    state = apply_saved_view_event(
        state,
        _env(
            aggregate_type="SavedView",
            aggregate_id="view-1",
            version=1,
            event_type=SAVED_VIEW_EVENT_CREATED,
            payload={
                "workspace_id": "ws-1",
                "project_id": "proj-1",
                "user_id": "user-1",
                "name": "Inbox",
                "shared": False,
                "filters": {"status": ["To Do"]},
            },
        ),
    )
    assert state["workspace_id"] == "ws-1"
    assert state["project_id"] == "proj-1"
    assert state["filters"] == {"status": ["To Do"]}


def test_rebuild_state_dispatches_new_aggregate_branches(monkeypatch) -> None:
    events = [
        _env(
            aggregate_type="User",
            aggregate_id="user-branch",
            version=1,
            event_type=USER_EVENT_CREATED,
            payload={"username": "branch-user", "workspace_id": "ws-1", "workspace_role": "Member"},
        )
    ]

    monkeypatch.setattr("shared.eventing_rebuild.load_snapshot", lambda _db, _type, _id: ({}, 0))
    monkeypatch.setattr("shared.eventing_rebuild.load_events_after", lambda _db, _type, _id, _version: events)

    state, version = rebuild_state(db=None, aggregate_type="User", aggregate_id="user-branch")  # type: ignore[arg-type]
    assert version == 1
    assert state["username"] == "branch-user"
    assert state["workspace_roles"] == {"ws-1": "Member"}
