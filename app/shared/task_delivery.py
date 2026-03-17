from __future__ import annotations

from typing import Any

from shared.team_mode_lifecycle import task_has_deploy_evidence, task_has_merge_evidence, task_matches_dependency_requirement


DELIVERY_MODE_DEPLOYABLE_SLICE = "deployable_slice"
DELIVERY_MODE_MERGED_INCREMENT = "merged_increment"
DELIVERY_MODES = {
    DELIVERY_MODE_DEPLOYABLE_SLICE,
    DELIVERY_MODE_MERGED_INCREMENT,
}


def normalize_delivery_mode(value: Any, *, default: str = DELIVERY_MODE_DEPLOYABLE_SLICE) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in DELIVERY_MODES:
        return normalized
    return default


def task_requires_deploy(value: Any) -> bool:
    return normalize_delivery_mode(value) == DELIVERY_MODE_DEPLOYABLE_SLICE


__all__ = [
    "DELIVERY_MODE_DEPLOYABLE_SLICE",
    "DELIVERY_MODE_MERGED_INCREMENT",
    "DELIVERY_MODES",
    "normalize_delivery_mode",
    "task_requires_deploy",
    "task_has_merge_evidence",
    "task_has_deploy_evidence",
    "task_matches_dependency_requirement",
]
