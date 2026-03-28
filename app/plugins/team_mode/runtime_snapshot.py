from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from features.tasks.read_models import get_task_automation_status_read_model
from shared.models import Project, ProjectMember, ProjectPluginConfig, Task
from shared.settings import AGENT_RUNNER_MAX_CONCURRENCY
from shared.task_delivery import task_matches_dependency_requirement
from shared.task_relationships import normalize_task_relationships
from shared.team_mode_lifecycle import derive_phase_from_status_and_role

from .runtime_context import TeamModeProjectRuntimeContext
from .semantics import semantic_status_key
from .task_roles import build_active_agent_load_by_code, derive_task_role, normalize_team_agents, pick_agent_for_role
from .workflow_orchestrator import TEAM_MODE_WORKFLOW_ROLES, plan_kickoff_targets, plan_team_mode_dispatch


def _load_team_mode_config(*, db: Session, project_id: str) -> tuple[Project | None, bool, dict[str, Any]]:
    project = db.get(Project, project_id)
    if project is None or bool(getattr(project, "is_deleted", False)):
        return None, False, {}
    row = db.execute(
        select(ProjectPluginConfig.enabled, ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == str(project.workspace_id),
            ProjectPluginConfig.project_id == project_id,
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        return project, False, {}
    enabled = bool(row[0])
    config: dict[str, Any] = {}
    try:
        parsed = json.loads(str(row[1] or "").strip() or "{}")
        if isinstance(parsed, dict):
            config = dict(parsed)
    except Exception:
        config = {}
    return project, enabled, config


def _normalize_parallel_limit(value: Any) -> int:
    try:
        normalized = int(value)
    except Exception:
        normalized = 1
    return max(1, min(normalized, int(AGENT_RUNNER_MAX_CONCURRENCY)))


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


def _task_runtime_state(
    *,
    task: dict[str, Any],
    dependency_ready: bool,
    dependency_reason: str | None,
) -> tuple[str, str | None, bool]:
    role = str(task.get("role") or "").strip()
    semantic = str(task.get("semantic_status") or "").strip()
    automation_state = str(task.get("automation_state") or "idle").strip().lower()
    has_instruction = bool(task.get("has_instruction"))
    dispatch_ready = bool(task.get("dispatch_ready", True))
    if role not in TEAM_MODE_WORKFLOW_ROLES:
        return "out_of_scope", "task is not assigned to a Team Mode workflow role", False
    if automation_state in {"queued", "running"}:
        return "active", None, False
    if not has_instruction:
        return "missing_instruction", "task has no instruction", False
    if not dispatch_ready:
        return "waiting", "task is not dispatch-ready", False
    if not dependency_ready:
        return "blocked", dependency_reason or "task is blocked by dependencies", False
    if role in {"Developer", "Lead"} and semantic not in {"todo", "active", "blocked"}:
        return "waiting", f"{role} tasks run only from To Do/In Progress/Blocked semantic states", False
    if role == "QA" and semantic not in {"active", "blocked"}:
        return "waiting", "QA tasks run only from In Progress/Blocked semantic states", False
    return "runnable", None, True


def build_team_mode_runtime_snapshot(*, db: Session, user: Any, project_id: str) -> dict[str, Any]:
    project, enabled, config = _load_team_mode_config(db=db, project_id=project_id)
    if project is None:
        return {
            "active": False,
            "reason": "project_not_found",
            "agents": [],
            "tasks": [],
            "summary": {},
            "dispatch": {"ok": False, "queue_task_ids": [], "selected_by_role": {}, "blocked_reasons": []},
            "kickoff": {"ok": False, "kickoff_task_ids": [], "kickoff_task_ids_by_role": {}, "blocked_reasons": []},
        }

    runtime_context = TeamModeProjectRuntimeContext(
        db=db,
        workspace_id=str(project.workspace_id),
        project_id=project_id,
    )
    team_agents = runtime_context.team_agents if enabled else normalize_team_agents(config.get("team"))
    agent_role_by_code = runtime_context.agent_role_by_code if enabled else {
        str(agent.get("id") or "").strip(): str(agent.get("authority_role") or "").strip()
        for agent in team_agents
        if str(agent.get("id") or "").strip()
    }
    member_role_by_user_id = runtime_context.member_role_by_user_id if enabled else {
        str(user_id): str(role or "").strip()
        for user_id, role in db.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(
                ProjectMember.workspace_id == str(project.workspace_id),
                ProjectMember.project_id == project_id,
            )
        ).all()
    }
    task_rows = runtime_context.tasks[:300] if enabled else db.execute(
        select(Task).where(
            Task.project_id == project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        )
        .order_by(Task.created_at.asc())
        .limit(300)
    ).scalars().all()
    parallel_limit = _normalize_parallel_limit(getattr(project, "automation_max_parallel_tasks", 1))

    base_tasks: list[dict[str, Any]] = []
    active_task_ids: list[str] = []
    for task in task_rows:
        task_id = str(task.id or "").strip()
        if not task_id:
            continue
        try:
            automation_status = get_task_automation_status_read_model(db, user, task_id)
        except Exception:
            automation_status = {}
        task_like = runtime_context.task_like(task) if enabled else {
            "id": task_id,
            "assignee_id": str(task.assignee_id or "").strip(),
            "assigned_agent_code": str(task.assigned_agent_code or "").strip(),
            "labels": task.labels,
            "status": str(task.status or "").strip(),
        }
        role = derive_task_role(
            task_like=task_like,
            member_role_by_user_id=member_role_by_user_id,
            agent_role_by_code=agent_role_by_code,
        )
        automation_state = str(automation_status.get("automation_state") or "idle").strip().lower() or "idle"
        if automation_state in {"queued", "running"}:
            active_task_ids.append(task_id)
        assigned_agent_code = str(task.assigned_agent_code or "").strip()
        base_tasks.append(
            {
                "id": task_id,
                "title": str(task.title or "").strip() or task_id,
                "status": str(task.status or "").strip(),
                "semantic_status": semantic_status_key(status=task.status),
                "role": str(role or "").strip(),
                "phase": derive_phase_from_status_and_role(
                    status=task.status,
                    assignee_role=role,
                ),
                "priority": str(task.priority or "").strip(),
                "automation_state": automation_state,
                "assigned_agent_code": assigned_agent_code,
                "dispatch_slot": str(automation_status.get("dispatch_slot") or assigned_agent_code).strip(),
                "has_instruction": bool(str(task.instruction or "").strip() or str(task.scheduled_instruction or "").strip()),
                "dispatch_ready": bool(automation_status.get("dispatch_ready", True)),
                "instruction": str(task.instruction or "").strip(),
                "scheduled_instruction": str(task.scheduled_instruction or "").strip(),
                "task_relationships": normalize_task_relationships(task.task_relationships),
                "last_requested_source": str(automation_status.get("last_requested_source") or "").strip() or None,
                "last_agent_run_at": str(automation_status.get("last_agent_run_at") or "").strip() or None,
            }
        )

    task_by_id = {str(task.get("id") or "").strip(): task for task in base_tasks if str(task.get("id") or "").strip()}
    orchestration_rows: list[dict[str, Any]] = []
    summary = {
        "tasks_total": len(base_tasks),
        "team_tasks_total": 0,
        "active_tasks_total": 0,
        "runnable_tasks_total": 0,
        "blocked_tasks_total": 0,
        "waiting_tasks_total": 0,
        "missing_instruction_total": 0,
        "by_role": {
            "Developer": {"total": 0, "active": 0, "runnable": 0, "blocked": 0},
            "Lead": {"total": 0, "active": 0, "runnable": 0, "blocked": 0},
            "QA": {"total": 0, "active": 0, "runnable": 0, "blocked": 0},
        },
    }
    planned_load_by_agent_code = (
        runtime_context.active_agent_load_by_code(agents=team_agents)
        if enabled
        else build_active_agent_load_by_code(
            agents=team_agents,
            task_likes=base_tasks,
            member_role_by_user_id=member_role_by_user_id,
            agent_role_by_code=agent_role_by_code,
        )
    )

    for task in base_tasks:
        dependency_ready, dependency_reason = _task_dependency_ready(task=task, task_by_id=task_by_id)
        runtime_state, blocker_reason, runnable = _task_runtime_state(
            task=task,
            dependency_ready=dependency_ready,
            dependency_reason=dependency_reason,
        )
        task["dependency_ready"] = dependency_ready
        task["dependency_reason"] = dependency_reason
        task["runtime_state"] = runtime_state
        task["blocker_reason"] = blocker_reason
        task["runnable"] = runnable
        if not str(task.get("dispatch_slot") or "").strip() and str(task.get("role") or "").strip() in TEAM_MODE_WORKFLOW_ROLES:
            selected_agent = pick_agent_for_role(
                agents=team_agents,
                authority_role=str(task.get("role") or "").strip(),
                current_load_by_agent_code=planned_load_by_agent_code,
            )
            predicted_slot = str((selected_agent or {}).get("id") or "").strip()
            task["dispatch_slot"] = predicted_slot
            if predicted_slot and runtime_state == "runnable":
                planned_load_by_agent_code[predicted_slot] = int(planned_load_by_agent_code.get(predicted_slot) or 0) + 1
        if str(task.get("role") or "").strip() in TEAM_MODE_WORKFLOW_ROLES:
            summary["team_tasks_total"] = int(summary["team_tasks_total"]) + 1
            role_summary = summary["by_role"][str(task.get("role"))]
            role_summary["total"] = int(role_summary["total"]) + 1
            if runtime_state == "active":
                summary["active_tasks_total"] = int(summary["active_tasks_total"]) + 1
                role_summary["active"] = int(role_summary["active"]) + 1
            elif runtime_state == "runnable":
                summary["runnable_tasks_total"] = int(summary["runnable_tasks_total"]) + 1
                role_summary["runnable"] = int(role_summary["runnable"]) + 1
            elif runtime_state == "blocked":
                summary["blocked_tasks_total"] = int(summary["blocked_tasks_total"]) + 1
                role_summary["blocked"] = int(role_summary["blocked"]) + 1
            elif runtime_state == "missing_instruction":
                summary["missing_instruction_total"] = int(summary["missing_instruction_total"]) + 1
            else:
                summary["waiting_tasks_total"] = int(summary["waiting_tasks_total"]) + 1
        orchestration_rows.append(
            {
                "id": task["id"],
                "role": task["role"],
                "status": task["status"],
                "instruction": task["instruction"],
                "scheduled_instruction": task["scheduled_instruction"],
                "priority": task["priority"],
                "task_relationships": task["task_relationships"],
                "assigned_agent_code": task["assigned_agent_code"],
                "dispatch_slot": task["dispatch_slot"],
                "dispatch_ready": task["dispatch_ready"],
                "automation_state": task["automation_state"],
            }
        )

    dispatch = plan_team_mode_dispatch(orchestration_rows, max_parallel_dispatch=parallel_limit) if enabled else {
        "ok": False,
        "mode": "disabled",
        "queue_task_ids": [],
        "selected_by_role": {"Developer": [], "Lead": [], "QA": []},
        "counts": {"busy_total": 0, "available_slots": 0, "candidates": {"Developer": 0, "Lead": 0, "QA": 0}},
        "blocked_reasons": ["Team Mode is disabled"],
    }
    available_kickoff_slots = max(0, parallel_limit - len(active_task_ids))
    kickoff = plan_kickoff_targets(orchestration_rows, max_parallel_dispatch=available_kickoff_slots or 1) if enabled else {
        "ok": False,
        "kickoff_task_ids": [],
        "kickoff_task_ids_by_role": {"Developer": [], "Lead": [], "QA": []},
        "parallel_limit": 0,
        "blocked_reasons": ["Team Mode is disabled"],
    }
    dispatch_ids = {str(item or "").strip() for item in list(dispatch.get("queue_task_ids") or []) if str(item or "").strip()}
    kickoff_ids = {str(item or "").strip() for item in list(kickoff.get("kickoff_task_ids") or []) if str(item or "").strip()}
    for task in base_tasks:
        task["selected_for_dispatch"] = str(task.get("id") or "").strip() in dispatch_ids
        task["selected_for_kickoff"] = str(task.get("id") or "").strip() in kickoff_ids

    agents: list[dict[str, Any]] = []
    role_agent_counts: dict[str, dict[str, int]] = {
        "Developer": {"configured": 0, "busy": 0, "idle": 0},
        "Lead": {"configured": 0, "busy": 0, "idle": 0},
        "QA": {"configured": 0, "busy": 0, "idle": 0},
    }
    for agent in team_agents:
        agent_id = str(agent.get("id") or "").strip()
        role = str(agent.get("authority_role") or "").strip()
        busy_task_ids = [
            str(task.get("id") or "").strip()
            for task in base_tasks
            if str(task.get("dispatch_slot") or task.get("assigned_agent_code") or "").strip() == agent_id
            and str(task.get("automation_state") or "").strip().lower() in {"queued", "running"}
        ]
        status = "busy" if busy_task_ids else "idle"
        if role in role_agent_counts:
            role_agent_counts[role]["configured"] = int(role_agent_counts[role]["configured"]) + 1
            role_agent_counts[role][status] = int(role_agent_counts[role][status]) + 1
        agents.append(
            {
                "id": agent_id,
                "name": str(agent.get("name") or "").strip() or agent_id,
                "authority_role": role,
                "executor_user_id": str(agent.get("executor_user_id") or "").strip() or None,
                "status": status,
                "busy_task_ids": busy_task_ids,
                "busy_task_count": len(busy_task_ids),
            }
        )

    summary["active_agents_total"] = sum(1 for agent in agents if str(agent.get("status") or "") == "busy")
    summary["idle_agents_total"] = sum(1 for agent in agents if str(agent.get("status") or "") == "idle")
    summary["role_agents"] = role_agent_counts
    return {
        "active": bool(enabled),
        "parallel_limit": parallel_limit,
        "agents": agents,
        "tasks": base_tasks,
        "summary": summary,
        "dispatch": dispatch,
        "kickoff": kickoff,
    }
