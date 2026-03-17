from __future__ import annotations

from typing import Any

from .task_roles import canonicalize_role
from .semantics import REQUIRED_SEMANTIC_STATUSES, canonicalize_semantic_status_label, normalize_status_semantics, semantic_status_key


def _normalize_statuses(status_semantics: dict[str, Any]) -> list[str]:
    normalized = normalize_status_semantics(status_semantics)
    return [value for value in normalized.values() if str(value or "").strip()]


def evaluate_team_mode_transition(
    *,
    status_semantics: dict[str, Any] | None,
    from_status: str,
    to_status: str,
    actor_role: str | None,
) -> tuple[bool, str]:
    normalized_semantics = normalize_status_semantics(status_semantics or REQUIRED_SEMANTIC_STATUSES)
    normalized_from = canonicalize_semantic_status_label(str(from_status or "").strip()) or str(from_status or "").strip()
    normalized_to = canonicalize_semantic_status_label(str(to_status or "").strip()) or str(to_status or "").strip()
    if normalized_from == normalized_to:
        return True, "noop"

    statuses = set(_normalize_statuses(normalized_semantics))
    if statuses and normalized_to not in statuses:
        return False, "target_status_not_allowed"

    normalized_actor_role = canonicalize_role(actor_role)
    if not normalized_actor_role:
        return False, "actor_role_missing"
    from_semantic = semantic_status_key(status=normalized_from, status_semantics=normalized_semantics)
    to_semantic = semantic_status_key(status=normalized_to, status_semantics=normalized_semantics)
    if not from_semantic or not to_semantic:
        return False, "unknown_status_semantics"

    if to_semantic == "completed":
        return (
            (normalized_actor_role == "QA" and from_semantic in {"active", "blocked"})
            or (normalized_actor_role == "QA" and from_semantic == "completed"),
            "allowed" if normalized_actor_role == "QA" and from_semantic in {"active", "blocked", "completed"} else "actor_role_not_permitted",
        )
    if to_semantic == "awaiting_decision":
        return (normalized_actor_role == "Lead", "allowed" if normalized_actor_role == "Lead" else "actor_role_not_permitted")
    if to_semantic == "in_review":
        return (normalized_actor_role == "Developer", "allowed" if normalized_actor_role == "Developer" else "actor_role_not_permitted")
    if to_semantic == "blocked":
        return (normalized_actor_role in {"Developer", "QA", "Lead"}, "allowed" if normalized_actor_role in {"Developer", "QA", "Lead"} else "actor_role_not_permitted")
    if to_semantic == "todo":
        return (normalized_actor_role == "Lead", "allowed" if normalized_actor_role == "Lead" else "actor_role_not_permitted")
    if to_semantic == "active":
        return (normalized_actor_role in {"Developer", "Lead", "QA"}, "allowed" if normalized_actor_role in {"Developer", "Lead", "QA"} else "actor_role_not_permitted")
    return False, "transition_not_declared"
