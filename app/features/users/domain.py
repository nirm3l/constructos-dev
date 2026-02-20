from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.aggregates import AggregateRoot


EVENT_PREFERENCES_UPDATED = "UserPreferencesUpdated"
EVENT_CREATED = "UserCreated"
EVENT_PASSWORD_CHANGED = "UserPasswordChanged"
EVENT_PASSWORD_RESET = "UserPasswordReset"
EVENT_WORKSPACE_ROLE_SET = "UserWorkspaceRoleSet"
EVENT_DEACTIVATED = "UserDeactivated"


class UserAggregate(AggregateRoot):
    aggregate_type = "User"

    def apply(self, *, event_type: str, payload: Mapping[str, Any]) -> None:
        if event_type == EVENT_CREATED:
            self.username = str(payload.get("username") or "")
            self.full_name = str(payload.get("full_name") or "")
            self.user_type = str(payload.get("user_type") or "")
            self.password_hash = str(payload.get("password_hash") or "")
            self.must_change_password = bool(payload.get("must_change_password", False))
            self.password_changed_at = payload.get("password_changed_at")
            self.is_active = bool(payload.get("is_active", True))
            self.theme = str(payload.get("theme") or "light")
            self.timezone = str(payload.get("timezone") or "UTC")
            self.notifications_enabled = bool(payload.get("notifications_enabled", True))
            workspace_id = str(payload.get("workspace_id") or "")
            workspace_role = str(payload.get("workspace_role") or "")
            workspace_roles: dict[str, str] = {}
            if workspace_id and workspace_role:
                workspace_roles[workspace_id] = workspace_role
            self.workspace_roles = workspace_roles
            return

        if event_type == EVENT_PREFERENCES_UPDATED:
            if "theme" in payload:
                self.theme = str(payload.get("theme") or "")
            if "timezone" in payload:
                self.timezone = str(payload.get("timezone") or "")
            if "notifications_enabled" in payload:
                self.notifications_enabled = bool(payload.get("notifications_enabled"))
            return

        if event_type in {EVENT_PASSWORD_CHANGED, EVENT_PASSWORD_RESET}:
            self.password_hash = str(payload.get("password_hash") or "")
            self.must_change_password = bool(payload.get("must_change_password", False))
            self.password_changed_at = payload.get("password_changed_at")
            return

        if event_type == EVENT_WORKSPACE_ROLE_SET:
            workspace_id = str(payload.get("workspace_id") or "")
            role = str(payload.get("role") or "")
            if workspace_id and role:
                workspace_roles = dict(getattr(self, "workspace_roles", {}) or {})
                workspace_roles[workspace_id] = role
                self.workspace_roles = workspace_roles
            return

        if event_type == EVENT_DEACTIVATED:
            self.is_active = False
            return

        raise ValueError(f"Unknown event type: {event_type}")

