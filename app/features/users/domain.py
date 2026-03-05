from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event

EVENT_PREFERENCES_UPDATED = "UserPreferencesUpdated"
EVENT_CREATED = "UserCreated"
EVENT_PASSWORD_CHANGED = "UserPasswordChanged"
EVENT_PASSWORD_RESET = "UserPasswordReset"
EVENT_WORKSPACE_ROLE_SET = "UserWorkspaceRoleSet"
EVENT_DEACTIVATED = "UserDeactivated"


class UserAggregate(Aggregate):
    aggregate_type = "User"

    @event("Created")
    def __init__(
        self,
        id: Any,
        username: str,
        full_name: str,
        user_type: str,
        password_hash: str | None,
        must_change_password: bool,
        password_changed_at: str | None,
        is_active: bool,
        theme: str,
        timezone: str,
        notifications_enabled: bool,
        agent_chat_model: str = "",
        agent_chat_reasoning_effort: str = "medium",
        onboarding_quick_tour_completed: bool = False,
        onboarding_advanced_tour_completed: bool = False,
        workspace_id: str | None = None,
        workspace_role: str = "Member",
    ) -> None:
        _ = id
        self.username = username
        self.full_name = full_name
        self.user_type = user_type
        self.password_hash = password_hash
        self.must_change_password = must_change_password
        self.password_changed_at = password_changed_at
        self.is_active = is_active
        self.theme = theme
        self.timezone = timezone
        self.notifications_enabled = notifications_enabled
        self.agent_chat_model = agent_chat_model
        self.agent_chat_reasoning_effort = agent_chat_reasoning_effort
        self.onboarding_quick_tour_completed = bool(onboarding_quick_tour_completed)
        self.onboarding_advanced_tour_completed = bool(onboarding_advanced_tour_completed)
        self.workspace_roles = {workspace_id: workspace_role} if workspace_id else {}

    @event("PreferencesUpdated")
    def update_preferences(
        self,
        theme: str | None = None,
        timezone: str | None = None,
        notifications_enabled: bool | None = None,
        agent_chat_model: str | None = None,
        agent_chat_reasoning_effort: str | None = None,
        onboarding_quick_tour_completed: bool | None = None,
        onboarding_advanced_tour_completed: bool | None = None,
    ) -> None:
        if theme is not None:
            self.theme = str(theme)
        if timezone is not None:
            self.timezone = str(timezone)
        if notifications_enabled is not None:
            self.notifications_enabled = bool(notifications_enabled)
        if agent_chat_model is not None:
            self.agent_chat_model = str(agent_chat_model)
        if agent_chat_reasoning_effort is not None:
            self.agent_chat_reasoning_effort = str(agent_chat_reasoning_effort)
        if onboarding_quick_tour_completed is not None:
            self.onboarding_quick_tour_completed = bool(onboarding_quick_tour_completed)
        if onboarding_advanced_tour_completed is not None:
            self.onboarding_advanced_tour_completed = bool(onboarding_advanced_tour_completed)

    @event("PasswordChanged")
    def change_password(
        self,
        password_hash: str,
        must_change_password: bool,
        password_changed_at: str | None,
        keep_session_hash: str | None = None,
    ) -> None:
        _ = keep_session_hash
        self.password_hash = password_hash
        self.must_change_password = must_change_password
        self.password_changed_at = password_changed_at

    @event("PasswordReset")
    def reset_password(
        self,
        password_hash: str,
        must_change_password: bool,
        password_changed_at: str | None,
        revoke_all_sessions: bool = True,
    ) -> None:
        _ = revoke_all_sessions
        self.password_hash = password_hash
        self.must_change_password = must_change_password
        self.password_changed_at = password_changed_at

    @event("WorkspaceRoleSet")
    def set_workspace_role(self, workspace_id: str, role: str) -> None:
        roles = dict(getattr(self, "workspace_roles", {}) or {})
        roles[workspace_id] = role
        self.workspace_roles = roles

    @event("Deactivated")
    def deactivate(self, workspace_id: str, revoke_all_sessions: bool = True) -> None:
        _ = (workspace_id, revoke_all_sessions)
        self.is_active = False
