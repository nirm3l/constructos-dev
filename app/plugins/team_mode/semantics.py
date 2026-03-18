from __future__ import annotations

from typing import Any

from shared.team_mode_lifecycle import (
    LIFECYCLE_LABELS,
    REQUIRED_SEMANTIC_STATUSES,
    SEMANTIC_STATUS_ALIASES,
    TEAM_MODE_PHASES,
    canonicalize_semantic_status_label,
    derive_phase_from_status_and_role,
    is_active_status,
    is_terminal_status,
    semantic_status_key,
)
from shared.settings import DEFAULT_USER_ID

from .task_roles import TEAM_MODE_ROLES, normalize_team_agents

RESERVED_LIFECYCLE_LABELS: tuple[str, ...] = LIFECYCLE_LABELS
DEFAULT_ASSIGNMENT_POLICY = "least_active_then_stable_order"


def default_team_mode_config() -> dict[str, Any]:
    return {
        "team": {
            "agents": [
                {"id": "dev-a", "name": "Developer A", "authority_role": "Developer"},
                {"id": "dev-b", "name": "Developer B", "authority_role": "Developer"},
                {"id": "qa-a", "name": "QA A", "authority_role": "QA"},
                {"id": "lead-a", "name": "Lead", "authority_role": "Lead"},
            ]
        },
        "status_semantics": dict(REQUIRED_SEMANTIC_STATUSES),
        "routing": {
            "developer_assignment": DEFAULT_ASSIGNMENT_POLICY,
            "qa_assignment": DEFAULT_ASSIGNMENT_POLICY,
        },
        "oversight": {
            "reconciliation_interval_seconds": 5,
            "human_owner_user_id": DEFAULT_USER_ID,
        },
        "review_policy": {
            "require_code_review": False,
            "reviewer_user_id": None,
        },
        "labels": {label.replace("-", "_"): label for label in RESERVED_LIFECYCLE_LABELS},
    }


def compile_team_mode_policy(config: dict[str, Any], *, required_checks: list[str], available_checks: dict[str, str]) -> dict[str, Any]:
    team_cfg = config.get("team") if isinstance(config.get("team"), dict) else {}
    agents = normalize_team_agents(team_cfg)
    status_semantics = normalize_status_semantics(config.get("status_semantics"))
    routing = normalize_routing(config.get("routing"))
    oversight = normalize_oversight(config.get("oversight"))
    review_policy = normalize_review_policy(config.get("review_policy"))
    labels = normalize_reserved_labels(config.get("labels"))
    return {
        "version": 2,
        "required_checks": {"team_mode": list(required_checks)},
        "available_checks": {"team_mode": dict(available_checks)},
        "team": {
            "agents": agents,
            "authority_role_counts": {
                role: sum(1 for agent in agents if str(agent.get("authority_role") or "").strip() == role)
                for role in sorted(TEAM_MODE_ROLES)
            },
        },
        "status_semantics": status_semantics,
        "routing": routing,
        "oversight": oversight,
        "review_policy": review_policy,
        "labels": labels,
    }


def normalize_status_semantics(raw: Any) -> dict[str, str]:
    source = raw if isinstance(raw, dict) else {}
    normalized: dict[str, str] = {}
    for key, default_value in REQUIRED_SEMANTIC_STATUSES.items():
        value = canonicalize_semantic_status_label(str(source.get(key) or "").strip(), semantic_key=key)
        normalized[key] = value or default_value
    return normalized


def normalize_routing(raw: Any) -> dict[str, str]:
    source = raw if isinstance(raw, dict) else {}
    return {
        "developer_assignment": _normalize_assignment_policy(source.get("developer_assignment")),
        "qa_assignment": _normalize_assignment_policy(source.get("qa_assignment")),
    }


def normalize_oversight(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    try:
        reconciliation_interval_seconds = int(source.get("reconciliation_interval_seconds"))
    except Exception:
        reconciliation_interval_seconds = 5
    return {
        "reconciliation_interval_seconds": max(1, reconciliation_interval_seconds),
        "human_owner_user_id": str(source.get("human_owner_user_id") or "").strip() or None,
    }


def normalize_review_policy(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    return {
        "require_code_review": bool(source.get("require_code_review", False)),
        "reviewer_user_id": str(source.get("reviewer_user_id") or "").strip() or None,
    }


def normalize_reserved_labels(raw: Any) -> dict[str, str]:
    source = raw if isinstance(raw, dict) else {}
    normalized: dict[str, str] = {}
    for label in RESERVED_LIFECYCLE_LABELS:
        key = label.replace("-", "_")
        value = str(source.get(key) or "").strip().lower()
        normalized[key] = value or label
    return normalized

def _normalize_assignment_policy(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized != DEFAULT_ASSIGNMENT_POLICY:
        return DEFAULT_ASSIGNMENT_POLICY
    return normalized
