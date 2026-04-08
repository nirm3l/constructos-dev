from __future__ import annotations

import threading
import time
from typing import Final

from .execution_provider import normalize_execution_provider

_DEFAULT_TTL_SECONDS: Final[float] = 6 * 60 * 60
_LOCK = threading.Lock()
_PROVIDER_BY_COMMAND_ID: dict[str, tuple[str, float]] = {}
_PROVIDER_BY_WORKSPACE_ID: dict[str, tuple[str, float]] = {}


def _normalize_command_id(value: object) -> str:
    return str(value or "").strip()


def _normalize_workspace_id(value: object) -> str:
    return str(value or "").strip()


def remember_provider_for_command_id(*, command_id: object, provider: object, ttl_seconds: float = _DEFAULT_TTL_SECONDS) -> None:
    normalized_command_id = _normalize_command_id(command_id)
    normalized_provider = normalize_execution_provider(provider)
    if not normalized_command_id or not normalized_provider:
        return
    now = time.time()
    expires_at = now + max(30.0, float(ttl_seconds or _DEFAULT_TTL_SECONDS))
    with _LOCK:
        _cleanup_locked(now)
        _PROVIDER_BY_COMMAND_ID[normalized_command_id] = (normalized_provider, expires_at)


def remember_provider_for_workspace_id(*, workspace_id: object, provider: object, ttl_seconds: float = _DEFAULT_TTL_SECONDS) -> None:
    normalized_workspace_id = _normalize_workspace_id(workspace_id)
    normalized_provider = normalize_execution_provider(provider)
    if not normalized_workspace_id or not normalized_provider:
        return
    now = time.time()
    expires_at = now + max(30.0, float(ttl_seconds or _DEFAULT_TTL_SECONDS))
    with _LOCK:
        _cleanup_locked(now)
        _PROVIDER_BY_WORKSPACE_ID[normalized_workspace_id] = (normalized_provider, expires_at)


def resolve_provider_for_command_id(command_id: object) -> str | None:
    normalized_command_id = _normalize_command_id(command_id)
    if not normalized_command_id:
        return None
    now = time.time()
    with _LOCK:
        _cleanup_locked(now)
        direct = _PROVIDER_BY_COMMAND_ID.get(normalized_command_id)
        if direct is not None:
            return direct[0]
        # Child command ids are derived as `<base>:<suffix>`.
        if ":" in normalized_command_id:
            base, _, _suffix = normalized_command_id.partition(":")
            base_entry = _PROVIDER_BY_COMMAND_ID.get(base)
            if base_entry is not None:
                return base_entry[0]
    return None


def resolve_provider_for_workspace_id(workspace_id: object) -> str | None:
    normalized_workspace_id = _normalize_workspace_id(workspace_id)
    if not normalized_workspace_id:
        return None
    now = time.time()
    with _LOCK:
        _cleanup_locked(now)
        direct = _PROVIDER_BY_WORKSPACE_ID.get(normalized_workspace_id)
        if direct is not None:
            return direct[0]
    return None


def _cleanup_locked(now: float) -> None:
    expired_keys = [key for key, (_provider, expires_at) in _PROVIDER_BY_COMMAND_ID.items() if expires_at <= now]
    for key in expired_keys:
        _PROVIDER_BY_COMMAND_ID.pop(key, None)
    expired_workspace_keys = [key for key, (_provider, expires_at) in _PROVIDER_BY_WORKSPACE_ID.items() if expires_at <= now]
    for key in expired_workspace_keys:
        _PROVIDER_BY_WORKSPACE_ID.pop(key, None)
