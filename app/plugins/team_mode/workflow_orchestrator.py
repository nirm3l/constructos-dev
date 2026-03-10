from __future__ import annotations

from typing import Any


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


def plan_kickoff_targets(tasks: list[dict[str, Any]], *, max_parallel_dispatch: int = 1) -> dict[str, Any]:
    lead_role_total = 0
    lead_status_total = 0
    lead_instruction_total = 0
    kickoff_targets: list[str] = []
    kickoff_targets_by_role: dict[str, list[str]] = {"Lead": [], "Developer": [], "QA": []}
    developer_candidates: list[str] = []
    qa_candidates: list[str] = []

    parallel_limit = _normalize_parallel_limit(max_parallel_dispatch, default=1)
    for task in tasks:
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            continue
        role = str(task.get("role") or "").strip()
        status = str(task.get("status") or "").strip()
        if not task_has_instruction(task):
            continue
        if role != "Lead":
            if role == "Developer" and status == "Dev":
                developer_candidates.append(task_id)
            elif role == "QA" and status == "QA":
                qa_candidates.append(task_id)
            continue
        lead_role_total += 1
        if status == "Lead":
            lead_status_total += 1
            lead_instruction_total += 1
            kickoff_targets_by_role["Lead"].append(task_id)

    # Lead-first kickoff requires at least one runnable Lead task.
    # Kickoff is dispatch-only orchestration and queues Lead tasks only.
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
    if lead_role_total == 0:
        blocked_reasons.append("no Team Mode Lead task exists")
    if lead_status_total == 0:
        blocked_reasons.append("no Lead task is currently in Lead status")
    if lead_instruction_total == 0:
        blocked_reasons.append("no Lead task has automation instruction")
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

    for order_index, task in enumerate(tasks):
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            continue
        role = str(task.get("role") or "").strip()
        status = str(task.get("status") or "").strip()
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
        expected_status = {"Developer": "Dev", "Lead": "Lead", "QA": "QA"}[role]
        if status != expected_status:
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
    lead_tasks_in_lead_status = 0

    for task in tasks:
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            continue
        role = str(task.get("role") or "").strip()
        status = str(task.get("status") or "").strip()
        if role not in TEAM_MODE_WORKFLOW_ROLES:
            continue
        if role == "Lead" and status == "Lead":
            lead_tasks_in_lead_status += 1
        if not task_has_instruction(task):
            continue
        if role == "Lead" and status == "Lead":
            lead_task_ids.append(task_id)
        elif role == "Developer" and status == "Dev":
            dev_task_ids.append(task_id)
        elif role == "QA" and status == "QA":
            qa_task_ids.append(task_id)

    # Deterministic Team Mode dispatch order is Lead-first.
    # Developer/QA execution should be explicitly dispatched by Lead orchestration
    # via automation requests/triggers, not by background auto-queue guessing.
    if lead_tasks_in_lead_status > 0:
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
            "lead_in_status": int(lead_tasks_in_lead_status),
        },
    }
