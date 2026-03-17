from __future__ import annotations

from typing import Any

from shared.task_relationships import normalize_task_relationships
from shared.task_delivery import task_matches_dependency_requirement

from .semantics import semantic_status_key


TEAM_MODE_WORKFLOW_ROLES = {"Developer", "Lead", "QA"}


def task_has_instruction(task: dict[str, Any]) -> bool:
    return bool(
        str(task.get("instruction") or "").strip()
        or str(task.get("scheduled_instruction") or "").strip()
    )


def _normalize_parallel_limit(value: Any, *, default: int = 1) -> int:
    try:
        normalized = int(value)
    except Exception:
        normalized = int(default)
    return max(1, normalized)


def _priority_rank(value: Any) -> int:
    normalized = str(value or "").strip().casefold()
    if normalized == "high":
        return 0
    if normalized in {"med", "medium"}:
        return 1
    if normalized == "low":
        return 2
    return 3


def _normalized_task_slot(task: dict[str, Any]) -> str:
    preferred = str(task.get("dispatch_slot") or "").strip()
    if preferred:
        return preferred
    return str(task.get("assigned_agent_code") or "").strip()


def _dependency_statuses(relationship: dict[str, Any]) -> set[str]:
    raw_statuses = relationship.get("statuses")
    if not isinstance(raw_statuses, list):
        return set()
    return {
        str(item or "").strip()
        for item in raw_statuses
        if str(item or "").strip()
    }


def _task_dependency_ready(
    *,
    task: dict[str, Any],
    task_by_id: dict[str, dict[str, Any]],
) -> tuple[bool, str | None]:
    task_id = str(task.get("id") or "").strip()
    relationships = normalize_task_relationships(task.get("task_relationships"))
    if not relationships:
        return True, None
    dependency_reasons: list[str] = []
    for relationship in relationships:
        if str(relationship.get("kind") or "").strip().lower() != "depends_on":
            continue
        source_task_ids = [
            str(item or "").strip()
            for item in (relationship.get("task_ids") or [])
            if str(item or "").strip() and str(item or "").strip() != task_id
        ]
        if not source_task_ids:
            continue
        required_statuses = _dependency_statuses(relationship)
        if not required_statuses:
            required_statuses = {"Completed"}
        match_mode = str(relationship.get("match_mode") or "all").strip().lower()
        matched_sources = 0
        total_sources = 0
        for source_task_id in source_task_ids:
            source_task = task_by_id.get(source_task_id)
            if not isinstance(source_task, dict):
                continue
            total_sources += 1
            if any(task_matches_dependency_requirement(source_task, required) for required in required_statuses):
                matched_sources += 1
        if total_sources <= 0:
            continue
        if match_mode == "any":
            if matched_sources > 0:
                continue
        elif matched_sources == total_sources:
            continue
        dependency_reasons.append(
            f"waiting for dependency: {matched_sources}/{total_sources} source tasks reached {sorted(required_statuses)}"
        )
    if dependency_reasons:
        return False, dependency_reasons[0]
    return True, None


def plan_kickoff_targets(tasks: list[dict[str, Any]], *, max_parallel_dispatch: int = 1) -> dict[str, Any]:
    kickoff_targets: list[str] = []
    kickoff_targets_by_role: dict[str, list[str]] = {"Lead": [], "Developer": [], "QA": []}
    role_runnable_totals: dict[str, int] = {"Lead": 0, "Developer": 0, "QA": 0}
    dependency_blocked_reasons: list[str] = []
    task_by_id = {
        str(task.get("id") or "").strip(): task
        for task in tasks
        if str(task.get("id") or "").strip()
    }

    parallel_limit = _normalize_parallel_limit(max_parallel_dispatch, default=1)
    for task in tasks:
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            continue
        role = str(task.get("role") or "").strip()
        semantic = semantic_status_key(status=task.get("status"))
        if role not in TEAM_MODE_WORKFLOW_ROLES:
            continue
        if not task_has_instruction(task):
            continue
        dependency_ready, dependency_reason = _task_dependency_ready(task=task, task_by_id=task_by_id)
        if not dependency_ready:
            if dependency_reason:
                dependency_blocked_reasons.append(dependency_reason)
            continue
        if role == "Developer" and semantic in {"todo", "active", "blocked"}:
            role_runnable_totals["Developer"] += 1
            kickoff_targets_by_role["Developer"].append(task_id)
            continue
        if role == "Lead" and semantic in {"todo", "active", "blocked"}:
            role_runnable_totals["Lead"] += 1
            kickoff_targets_by_role["Lead"].append(task_id)
            continue
        if role == "QA" and semantic in {"active", "blocked"}:
            role_runnable_totals["QA"] += 1
            kickoff_targets_by_role["QA"].append(task_id)

    for task_id in list(kickoff_targets_by_role["Developer"]):
        if len(kickoff_targets) >= parallel_limit:
            break
        kickoff_targets.append(task_id)
    for task_id in list(kickoff_targets_by_role["Lead"]):
        if len(kickoff_targets) >= parallel_limit:
            break
        kickoff_targets.append(task_id)

    if kickoff_targets:
        return {
            "ok": True,
            "kickoff_task_ids": kickoff_targets,
            "kickoff_task_ids_by_role": kickoff_targets_by_role,
            "parallel_limit": parallel_limit,
            "blocked_reasons": [],
        }

    blocked_reasons: list[str] = []
    if role_runnable_totals["Developer"] == 0 and role_runnable_totals["Lead"] == 0:
        blocked_reasons.append("no runnable Team Mode task is in a kickoff-ready semantic state")
    if dependency_blocked_reasons:
        blocked_reasons.extend(dependency_blocked_reasons)
    if not blocked_reasons:
        blocked_reasons.append("no runnable kickoff target matched deterministic kickoff criteria")
    return {
        "ok": False,
        "kickoff_task_ids": [],
        "kickoff_task_ids_by_role": kickoff_targets_by_role,
        "parallel_limit": parallel_limit,
        "blocked_reasons": blocked_reasons,
    }


def plan_team_mode_dispatch(tasks: list[dict[str, Any]], *, max_parallel_dispatch: int = 1) -> dict[str, Any]:
    parallel_limit = _normalize_parallel_limit(max_parallel_dispatch, default=1)
    busy_total = 0
    busy_slots_by_role: dict[str, set[str]] = {"Developer": set(), "Lead": set(), "QA": set()}
    candidates_by_role: dict[str, int] = {"Developer": 0, "Lead": 0, "QA": 0}
    selected_by_role: dict[str, list[str]] = {"Developer": [], "Lead": [], "QA": []}
    candidate_rows: list[tuple[int, int, int, str, str, str]] = []
    role_rank = {"Developer": 0, "QA": 1, "Lead": 2}
    dependency_blocked_reasons: list[str] = []
    task_by_id = {
        str(task.get("id") or "").strip(): task
        for task in tasks
        if str(task.get("id") or "").strip()
    }

    for order_index, task in enumerate(tasks):
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            continue
        role = str(task.get("role") or "").strip()
        semantic = semantic_status_key(status=task.get("status"))
        if role not in TEAM_MODE_WORKFLOW_ROLES:
            continue
        automation_state = str(task.get("automation_state") or "idle").strip().lower()
        task_slot = _normalized_task_slot(task)
        if automation_state in {"queued", "running"}:
            busy_total += 1
            if task_slot:
                busy_slots_by_role.setdefault(role, set()).add(task_slot)
            continue
        if not task_has_instruction(task):
            continue
        if not bool(task.get("dispatch_ready", True)):
            continue
        dependency_ready, dependency_reason = _task_dependency_ready(task=task, task_by_id=task_by_id)
        if not dependency_ready:
            if dependency_reason:
                dependency_blocked_reasons.append(dependency_reason)
            continue
        if role == "Lead" and semantic not in {"todo", "active", "blocked"}:
            continue
        if role == "Developer" and semantic not in {"todo", "active", "blocked"}:
            continue
        if role == "QA" and semantic not in {"active", "blocked"}:
            continue
        candidates_by_role[role] = int(candidates_by_role.get(role) or 0) + 1
        candidate_rows.append(
            (
                int(role_rank.get(role, 99)),
                _priority_rank(task.get("priority")),
                order_index,
                task_id,
                role,
                task_slot,
            )
        )

    available_slots = max(0, parallel_limit - busy_total)
    if available_slots <= 0:
        return {
            "ok": True,
            "mode": "capacity_exhausted",
            "queue_task_ids": [],
            "selected_by_role": selected_by_role,
            "counts": {
                "busy_total": busy_total,
                "available_slots": 0,
                "candidates": candidates_by_role,
            },
            "blocked_reasons": ["parallel dispatch capacity is exhausted"],
        }

    candidate_rows.sort()
    reserved_slots_by_role = {role: set(slots) for role, slots in busy_slots_by_role.items()}
    queue_task_ids: list[str] = []
    for _role_rank, _priority, _order_index, task_id, role, task_slot in candidate_rows:
        if len(queue_task_ids) >= available_slots:
            break
        if task_slot and task_slot in reserved_slots_by_role.setdefault(role, set()):
            continue
        queue_task_ids.append(task_id)
        selected_by_role.setdefault(role, []).append(task_id)
        if task_slot:
            reserved_slots_by_role[role].add(task_slot)

    mode = "idle"
    if selected_by_role["Developer"]:
        mode = "developer_dispatch"
    elif selected_by_role["QA"]:
        mode = "qa_dispatch"
    elif selected_by_role["Lead"]:
        mode = "lead_dispatch"

    blocked_reasons: list[str] = []
    if not queue_task_ids:
        if any(int(candidates_by_role.get(role) or 0) > 0 for role in TEAM_MODE_WORKFLOW_ROLES):
            blocked_reasons.append("all runnable candidates are already covered by busy agent slots")
        else:
            blocked_reasons.append("no runnable Team Mode task matched dispatch criteria")
        if dependency_blocked_reasons:
            blocked_reasons.extend(dependency_blocked_reasons)

    return {
        "ok": True,
        "mode": mode,
        "queue_task_ids": queue_task_ids,
        "selected_by_role": selected_by_role,
        "counts": {
            "busy_total": busy_total,
            "available_slots": available_slots,
            "candidates": candidates_by_role,
        },
        "blocked_reasons": blocked_reasons,
    }


def plan_next_runnable_tasks(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    lead_task_ids: list[str] = []
    dev_task_ids: list[str] = []
    qa_task_ids: list[str] = []
    lead_runnable = 0

    for task in tasks:
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            continue
        role = str(task.get("role") or "").strip()
        semantic = semantic_status_key(status=task.get("status"))
        if role not in TEAM_MODE_WORKFLOW_ROLES:
            continue
        if not task_has_instruction(task):
            continue
        if role == "Lead" and semantic in {"todo", "active", "blocked"}:
            lead_runnable += 1
            lead_task_ids.append(task_id)
        elif role == "Developer" and semantic in {"todo", "active", "blocked"}:
            dev_task_ids.append(task_id)
        elif role == "QA" and semantic in {"active", "blocked"}:
            qa_task_ids.append(task_id)

    # Deterministic Team Mode dispatch order is Lead-first.
    # Developer/QA execution should be explicitly dispatched by Lead orchestration
    # via automation requests/triggers, not by background auto-queue guessing.
    if lead_runnable > 0:
        queue_order = list(lead_task_ids)
        mode = "lead"
    elif dev_task_ids:
        queue_order = []
        mode = "developer_waiting_lead_dispatch"
    else:
        queue_order = []
        mode = "qa_waiting_lead_handoff"
    return {
        "ok": True,
        "mode": mode,
        "queue_task_ids": queue_order,
        "counts": {
            "developer": len(dev_task_ids),
            "lead": len(lead_task_ids),
            "qa": len(qa_task_ids),
            "lead_in_status": int(lead_runnable),
        },
    }
