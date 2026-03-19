from __future__ import annotations

from typing import Any

from shared.delivery_evidence import derive_deploy_execution_snapshot, has_merge_to_main_ref, is_strict_deploy_success_snapshot


REQUIRED_SEMANTIC_STATUSES: dict[str, str] = {
    "todo": "To Do",
    "active": "In Progress",
    "in_review": "In Review",
    "blocked": "Blocked",
    "awaiting_decision": "Awaiting Decision",
    "completed": "Completed",
}

SEMANTIC_STATUS_ALIASES: dict[str, tuple[str, ...]] = {
    "todo": ("to do", "todo"),
    "active": ("in progress", "inprogress"),
    "in_review": ("in review", "inreview"),
    "blocked": ("blocked",),
    "awaiting_decision": ("awaiting decision", "awaitingdecision"),
    "completed": ("completed", "done", "complete"),
}

TEAM_MODE_PHASES: set[str] = {
    "implementation",
    "in_review",
    "deploy_ready",
    "deployment",
    "qa_validation",
    "lead_triage",
    "blocked",
    "awaiting_decision",
    "completed",
}

LIFECYCLE_LABELS: tuple[str, ...] = ("merged", "deploy-ready", "deployed", "tested")


def semantic_status_key(*, status: Any, status_semantics: dict[str, str] | None = None) -> str:
    status_text = str(status or "").strip()
    semantics = status_semantics or dict(REQUIRED_SEMANTIC_STATUSES)
    for key, label in semantics.items():
        if status_text == str(label or "").strip():
            return key
    normalized_status = status_text.casefold()
    for key, aliases in SEMANTIC_STATUS_ALIASES.items():
        if normalized_status in {alias.casefold() for alias in aliases}:
            return key
    return ""


def canonicalize_semantic_status_label(status: Any, *, semantic_key: str | None = None) -> str:
    status_text = str(status or "").strip()
    if not status_text:
        return ""
    normalized_status = status_text.casefold()
    if semantic_key:
        aliases = SEMANTIC_STATUS_ALIASES.get(semantic_key, ())
        if normalized_status in {alias.casefold() for alias in aliases}:
            return REQUIRED_SEMANTIC_STATUSES.get(semantic_key, status_text)
    resolved_key = semantic_status_key(status=status_text)
    if resolved_key:
        return REQUIRED_SEMANTIC_STATUSES.get(resolved_key, status_text)
    return status_text


def is_terminal_status(*, status: Any, status_semantics: dict[str, str] | None = None) -> bool:
    return semantic_status_key(status=status, status_semantics=status_semantics) == "completed"


def is_active_status(*, status: Any, status_semantics: dict[str, str] | None = None) -> bool:
    return semantic_status_key(status=status, status_semantics=status_semantics) in {"todo", "active", "blocked"}


def canonicalize_team_mode_role(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized.startswith("developer"):
        return "Developer"
    if normalized.startswith("lead"):
        return "Lead"
    if normalized == "qa":
        return "QA"
    if normalized == "human":
        return "Human"
    return str(value or "").strip()


def task_has_merge_evidence(task_like: dict[str, Any] | None) -> bool:
    task = task_like if isinstance(task_like, dict) else {}
    if str(task.get("last_merged_commit_sha") or "").strip():
        return True
    return has_merge_to_main_ref(task.get("external_refs"))


def task_has_deploy_evidence(task_like: dict[str, Any] | None) -> bool:
    task = task_like if isinstance(task_like, dict) else {}
    snapshot = derive_deploy_execution_snapshot(
        refs=task.get("external_refs"),
        current_snapshot=task.get("last_deploy_execution") if isinstance(task.get("last_deploy_execution"), dict) else {},
    )
    return is_strict_deploy_success_snapshot(snapshot)


def task_lifecycle_milestones(task_like: dict[str, Any] | None) -> set[str]:
    task = task_like if isinstance(task_like, dict) else {}
    milestones: set[str] = set()
    if task_has_merge_evidence(task):
        milestones.add("merged")
        milestones.add("deploy_ready")
    if task_has_deploy_evidence(task):
        milestones.add("deployed")
    if semantic_status_key(status=task.get("status")) == "completed":
        milestones.add("tested")
        milestones.add("completed")
    return milestones


def task_matches_dependency_requirement(task_like: dict[str, Any] | None, requirement: Any) -> bool:
    task = task_like if isinstance(task_like, dict) else {}
    normalized = str(requirement or "").strip()
    if not normalized:
        return False
    lowered = normalized.casefold()
    milestones = task_lifecycle_milestones(task)
    if lowered in {item.casefold() for item in milestones}:
        return True
    return str(task.get("status") or "").strip() == normalized


def derive_phase_from_status_and_role(
    *,
    status: Any,
    assignee_role: Any,
    status_semantics: dict[str, str] | None = None,
) -> str:
    semantic_key = semantic_status_key(status=status, status_semantics=status_semantics)
    role = canonicalize_team_mode_role(assignee_role)
    if semantic_key == "completed":
        return "completed"
    if semantic_key == "awaiting_decision":
        return "awaiting_decision"
    if semantic_key == "blocked":
        return "blocked"
    if semantic_key == "in_review":
        return "in_review"
    if role == "Lead":
        return "deployment" if semantic_key == "active" else "deploy_ready"
    if role == "QA":
        return "qa_validation"
    return "implementation"


def developer_success_transition(*, review_required: bool, requires_deploy: bool, completed_status: str) -> dict[str, Any]:
    if review_required:
        return {
            "status": REQUIRED_SEMANTIC_STATUSES["in_review"],
            "phase": "in_review",
            "terminal": False,
            "next_role": "Human",
        }
    if not requires_deploy:
        return {
            "status": completed_status,
            "phase": "completed",
            "terminal": True,
            "next_role": None,
        }
    return {
        "status": REQUIRED_SEMANTIC_STATUSES["active"],
        "phase": "deploy_ready",
        "terminal": False,
        "next_role": "Lead",
    }


def review_resolution_transition(*, action: str) -> dict[str, Any]:
    normalized = str(action or "").strip().lower()
    if normalized == "approve":
        return {
            "status": REQUIRED_SEMANTIC_STATUSES["active"],
            "phase": "implementation",
            "next_role": "Developer",
            "review_status": "approved",
        }
    return {
        "status": REQUIRED_SEMANTIC_STATUSES["active"],
        "phase": "implementation",
        "next_role": "Developer",
        "review_status": "changes_requested",
    }


def lead_deploy_success_transition() -> dict[str, Any]:
    return {
        "status": REQUIRED_SEMANTIC_STATUSES["active"],
        "phase": "qa_validation",
        "next_role": "QA",
    }


def qa_success_transition(*, completed_status: str) -> dict[str, Any]:
    return {
        "status": completed_status,
        "phase": "completed",
        "terminal": True,
    }
