from __future__ import annotations

from pathlib import Path

from .provider_auth import (
    delete_provider_system_override_auth,
    ensure_provider_system_override_home,
    get_provider_auth_status,
    is_placeholder_auth_file,
    is_usable_auth_file,
    resolve_provider_effective_auth_path,
    resolve_provider_effective_auth_source,
    resolve_provider_host_auth_path,
    resolve_provider_system_override_auth_path,
    resolve_provider_system_override_home,
    start_provider_device_auth_session,
    cancel_provider_device_auth_session,
    submit_provider_device_auth_code,
)


def resolve_host_auth_path() -> Path | None:
    return resolve_provider_host_auth_path("claude")


def resolve_system_override_home() -> Path:
    return resolve_provider_system_override_home("claude")


def resolve_system_override_auth_path() -> Path:
    return resolve_provider_system_override_auth_path("claude")


def resolve_effective_auth_source(_actor_user_id: str | None = None) -> str:
    return resolve_provider_effective_auth_source("claude", _actor_user_id)


def resolve_effective_auth_path(_actor_user_id: str | None = None) -> Path | None:
    return resolve_provider_effective_auth_path("claude", _actor_user_id)


def ensure_system_override_home() -> Path:
    return ensure_provider_system_override_home("claude")


def get_claude_auth_status(_requested_by_user_id: str | None = None) -> dict[str, object]:
    return get_provider_auth_status("claude", _requested_by_user_id)


def start_device_auth_session(
    requested_by_user_id: str | None = None,
    *,
    login_method: str | None = None,
) -> dict[str, object]:
    return start_provider_device_auth_session("claude", requested_by_user_id, login_method=login_method)


def cancel_device_auth_session(_requested_by_user_id: str | None = None) -> dict[str, object]:
    return cancel_provider_device_auth_session("claude", _requested_by_user_id)


def submit_device_auth_code(code: str, _requested_by_user_id: str | None = None) -> dict[str, object]:
    return submit_provider_device_auth_code("claude", code, _requested_by_user_id)


def delete_system_override_auth(_requested_by_user_id: str | None = None) -> dict[str, object]:
    return delete_provider_system_override_auth("claude", _requested_by_user_id)
