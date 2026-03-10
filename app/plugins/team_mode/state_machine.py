from __future__ import annotations

from typing import Any

from .task_roles import canonicalize_role


def _normalize_statuses(workflow: dict[str, Any]) -> list[str]:
    statuses_raw = workflow.get("statuses")
    if not isinstance(statuses_raw, list):
        return []
    return [str(item or "").strip() for item in statuses_raw if str(item or "").strip()]


def _normalize_transitions(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    transitions_raw = workflow.get("transitions")
    if not isinstance(transitions_raw, list):
        return []
    return [item for item in transitions_raw if isinstance(item, dict)]


def evaluate_team_mode_transition(
    *,
    workflow: dict[str, Any],
    from_status: str,
    to_status: str,
    actor_role: str | None,
) -> tuple[bool, str]:
    normalized_from = str(from_status or "").strip()
    normalized_to = str(to_status or "").strip()
    if normalized_from == normalized_to:
        return True, "noop"

    statuses = _normalize_statuses(workflow)
    if statuses and normalized_to not in set(statuses):
        return False, "target_status_not_allowed"

    transitions = _normalize_transitions(workflow)
    if not transitions:
        return False, "no_transitions_declared"

    normalized_actor_role = canonicalize_role(actor_role)
    if not normalized_actor_role:
        return False, "actor_role_missing"

    for transition in transitions:
        transition_from = str(transition.get("from") or "").strip()
        transition_to = str(transition.get("to") or "").strip()
        if transition_from != normalized_from or transition_to != normalized_to:
            continue
        allowed_roles_raw = transition.get("allowed_roles")
        allowed_roles = (
            {str(role or "").strip() for role in allowed_roles_raw if str(role or "").strip()}
            if isinstance(allowed_roles_raw, list)
            else set()
        )
        if "*" in allowed_roles or normalized_actor_role in allowed_roles:
            return True, "allowed"
        return False, "actor_role_not_permitted"

    return False, "transition_not_declared"

