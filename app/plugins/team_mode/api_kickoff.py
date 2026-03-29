from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException

from shared.core import User, append_event
from shared.models import Project, SessionLocal, Task
from shared.settings import AGENT_RUNNER_MAX_CONCURRENCY
from shared.task_automation import normalize_execution_triggers
from shared.task_relationships import normalize_task_relationships
from shared.typed_notifications import append_notification_created_event
from .runtime_context import TeamModeProjectRuntimeContext
from .gates import evaluate_team_mode_gates
from .workflow_orchestrator import TEAM_MODE_WORKFLOW_ROLES, plan_kickoff_targets
from .semantics import REQUIRED_SEMANTIC_STATUSES, semantic_status_key


def _collect_team_mode_developer_dispatch_state(
    *,
    db: Any,
    workspace_id: str,
    project_id: str,
) -> dict[str, Any]:
    runtime_context = TeamModeProjectRuntimeContext(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    developer_task_ids: list[str] = []
    active_task_ids: list[str] = []
    idle_task_ids: list[str] = []
    for task in runtime_context.tasks:
        task_id = str(task.id or "").strip()
        if not task_id:
            continue
        role = runtime_context.derive_workflow_role(task=task)
        if role != "Developer":
            continue
        if semantic_status_key(status=task.status) == "completed":
            continue
        developer_task_ids.append(task_id)
        state = runtime_context.task_state(task_id)
        automation_state = str(state.get("automation_state") or "idle").strip().lower()
        if automation_state == "idle":
            idle_task_ids.append(task_id)
        else:
            active_task_ids.append(task_id)
    return {
        "developer_task_ids": developer_task_ids,
        "developer_active_task_ids": active_task_ids,
        "developer_idle_task_ids": idle_task_ids,
        "developer_dispatch_confirmed": bool(active_task_ids),
    }


def maybe_dispatch_execution_kickoff(
    *,
    db: Any,
    user: User,
    workspace_id: str,
    project_id: str | None,
    intent_flags: dict[str, bool] | None,
    allow_mutations: bool,
    command_id: str | None,
    promote_plugin_policy_to_execution_mode_if_needed: Callable[..., None] | None = None,
    build_team_lead_kickoff_instruction: Callable[..., str] | None = None,
    command_id_with_suffix: Callable[[str | None, str], str | None] | None = None,
) -> dict[str, object] | None:
    normalized_project_id = str(project_id or "").strip()
    if not allow_mutations or not normalized_project_id:
        return None
    if not callable(promote_plugin_policy_to_execution_mode_if_needed):
        return None
    if not callable(build_team_lead_kickoff_instruction):
        return None
    if not callable(command_id_with_suffix):
        return None

    flags = intent_flags or {}
    kickoff_intent = bool(flags.get("execution_kickoff_intent"))
    should_dispatch_kickoff = kickoff_intent
    if not should_dispatch_kickoff:
        return None

    runtime_context = TeamModeProjectRuntimeContext(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    if not runtime_context.enabled:
        return None
    team_mode_config_obj = runtime_context.config
    team_agents = runtime_context.team_agents
    project_row = db.get(Project, normalized_project_id)
    raw_parallel_limit = getattr(project_row, "automation_max_parallel_tasks", None) if project_row is not None else None
    try:
        max_parallel_dispatch = int(raw_parallel_limit or 4)
    except Exception:
        max_parallel_dispatch = 4
    max_parallel_dispatch = max(1, min(max_parallel_dispatch, int(AGENT_RUNNER_MAX_CONCURRENCY)))
    agent_role_by_code = runtime_context.agent_role_by_code

    promote_plugin_policy_to_execution_mode_if_needed(
        db=db,
        user=user,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        command_id=command_id,
    )

    member_role_by_user_id = runtime_context.member_role_by_user_id
    tasks = runtime_context.tasks

    def _task_instruction(task: Task) -> str:
        return str(task.instruction or "").strip() or str(task.scheduled_instruction or "").strip()

    candidates_dev: list[tuple[Task, str]] = []
    candidates_qa: list[tuple[Task, str]] = []
    orchestration_rows: list[dict[str, str]] = []
    task_by_id: dict[str, Task] = {}
    task_state_by_id: dict[str, dict[str, Any]] = {}
    active_task_ids_before_dispatch: list[str] = []
    for task in tasks:
        task_id = str(task.id or "").strip()
        if not task_id:
            continue
        task_state_by_id[task_id] = runtime_context.task_state(task_id)
        automation_state = str((task_state_by_id.get(task_id) or {}).get("automation_state") or "idle").strip().lower()
        if automation_state in {"queued", "running"}:
            active_task_ids_before_dispatch.append(task_id)

        normalized_role = runtime_context.derive_workflow_role(task=task)
        if normalized_role not in TEAM_MODE_WORKFLOW_ROLES:
            continue
        normalized_status = str(task.status or "").strip()
        normalized_semantic = semantic_status_key(status=normalized_status)
        if normalized_semantic == "completed":
            continue
        task_by_id[task_id] = task
        orchestration_rows.append(
            {
                "id": task_id,
                "role": normalized_role,
                "status": normalized_status,
                "instruction": str(task.instruction or "").strip(),
                "scheduled_instruction": str(task.scheduled_instruction or "").strip(),
                "priority": str(task.priority or "").strip(),
                "task_relationships": normalize_task_relationships(task.task_relationships),
            }
        )
        if normalized_role == "Developer" and normalized_semantic in {"todo", "active", "blocked"} and _task_instruction(task):
            candidates_dev.append((task, normalized_role))
        elif normalized_role == "QA" and normalized_semantic in {"active", "blocked"} and _task_instruction(task):
            candidates_qa.append((task, normalized_role))

    active_count = len(active_task_ids_before_dispatch)
    available_slots_before_dispatch = max(0, max_parallel_dispatch - active_count)
    if available_slots_before_dispatch <= 0:
        return {
            "ok": True,
            "action": "comment",
            "summary": "Team Mode kickoff already in progress.",
            "comment": (
                "Maximum parallel kickoff capacity is reached for this project. "
                "Wait for active automation tasks to finish before retrying."
            ),
            "kickoff_dispatched": False,
            "already_in_progress": True,
            "queued_task_ids": list(active_task_ids_before_dispatch),
            "queued_by_role": {"Developer": 0, "Lead": 0, "QA": 0},
            "failed": [],
            "parallel_limit": max_parallel_dispatch,
            "active_count_before_dispatch": active_count,
        }

    kickoff_plan = plan_kickoff_targets(
        orchestration_rows,
        max_parallel_dispatch=available_slots_before_dispatch,
    )
    kickoff_task_ids_by_role = kickoff_plan.get("kickoff_task_ids_by_role")
    kickoff_ids_by_role = kickoff_task_ids_by_role if isinstance(kickoff_task_ids_by_role, dict) else {}
    task_role_by_id: dict[str, str] = {}
    for role_name in ("Lead", "Developer", "QA"):
        role_task_ids = kickoff_ids_by_role.get(role_name)
        if not isinstance(role_task_ids, list):
            continue
        for item in role_task_ids:
            task_id = str(item or "").strip()
            if task_id:
                task_role_by_id[task_id] = role_name

    kickoff_targets: list[tuple[Task, str]] = [
        (task_by_id[task_id], str(task_role_by_id.get(task_id) or "Lead"))
        for task_id in list(kickoff_plan.get("kickoff_task_ids") or [])
        if task_id in task_by_id
    ]

    if not kickoff_targets:
        blocked_reasons = [str(item or "").strip() for item in (kickoff_plan.get("blocked_reasons") or []) if str(item or "").strip()]
        if not blocked_reasons:
            blocked_reasons = ["no runnable kickoff target matched deterministic kickoff criteria"]
        return {
            "ok": False,
            "action": "comment",
            "summary": "Team Mode kickoff blocked.",
            "comment": "Missing kickoff prerequisites: " + "; ".join(blocked_reasons) + ".",
            "kickoff_dispatched": False,
            "queued_task_ids": [],
            "queued_by_role": {"Developer": 0, "Lead": 0, "QA": 0},
            "failed": [],
            "blocked_reasons": blocked_reasons,
            "parallel_limit": max_parallel_dispatch,
            "active_count_before_dispatch": active_count,
        }

    # Before kickoff, validate Team Mode configuration readiness only.
    if candidates_dev or candidates_qa:
        topology_tasks: list[dict[str, object]] = []
        for task in tasks:
            topology_tasks.append(
                {
                    "id": str(task.id or "").strip(),
                    "assignee_id": str(task.assignee_id or "").strip(),
                    "assigned_agent_code": str(task.assigned_agent_code or "").strip(),
                    "labels": task.labels,
                    "status": str(task.status or "").strip(),
                    "title": str(task.title or "").strip(),
                    "instruction": str(task.instruction or "").strip(),
                    "scheduled_instruction": str(task.scheduled_instruction or "").strip(),
                    "execution_triggers": normalize_execution_triggers(task.execution_triggers),
                    "task_relationships": normalize_task_relationships(task.task_relationships),
                    "scheduled_at_utc": task.scheduled_at_utc,
                    "recurring_rule": task.recurring_rule,
                    "task_type": str(task.task_type or "").strip() or "manual",
                }
            )
        team_mode_gate_eval = evaluate_team_mode_gates(
            project_id=normalized_project_id,
            workspace_id=workspace_id,
            event_storming_enabled=False,
            expected_event_storming_enabled=None,
            plugin_policy={
                "team": {"agents": team_agents},
                "status_semantics": dict(REQUIRED_SEMANTIC_STATUSES),
                "oversight": dict(team_mode_config_obj.get("oversight") or {}),
            },
            plugin_policy_source="team_mode_kickoff_readiness",
            tasks=topology_tasks,
            member_role_by_user_id=member_role_by_user_id,
            notes_by_task={},
            comments_by_task={},
            extract_deploy_ports=lambda _text: set(),
            has_deploy_stack_marker=lambda _text: False,
        )
        topology_checks = dict(team_mode_gate_eval.get("checks") or {})
        if not bool(team_mode_gate_eval.get("ok")):
            missing_bits: list[str] = []
            if not bool(topology_checks.get("role_coverage_present")):
                missing_bits.append("role coverage (need at least one Developer task assignment, one QA assignment, and one Lead assignment)")
            if not bool(topology_checks.get("single_lead_present")):
                missing_bits.append("exactly one Lead agent in Team Mode config")
            if not bool(topology_checks.get("human_owner_present")):
                missing_bits.append("oversight.human_owner_user_id")
            if not bool(topology_checks.get("status_semantics_present")):
                missing_bits.append("required Team Mode semantic statuses")
            summary = "Team Mode kickoff blocked: Team Mode configuration is incomplete."
            comment = "Missing: " + "; ".join(missing_bits)
            return {
                "ok": False,
                "action": "comment",
                "summary": summary,
                "comment": comment,
                "kickoff_dispatched": False,
                "queued_task_ids": [],
                "queued_by_role": {"Developer": 0, "Lead": 0, "QA": 0},
                "failed": [],
                "blocked_reasons": missing_bits,
            }

    kickoff_instruction = build_team_lead_kickoff_instruction(
        project_id=normalized_project_id,
        requester_user_id=str(user.id),
    )
    from features.tasks.application import TaskApplicationService
    from shared.core import TaskAutomationRun

    active_kickoff_task_ids: list[str] = []
    for task, _role in kickoff_targets:
        task_id = str(getattr(task, "id", "") or "").strip()
        if not task_id:
            continue
        state = task_state_by_id.get(task_id) or {}
        automation_state = str(state.get("automation_state") or "idle").strip().lower()
        if automation_state in {"queued", "running"}:
            active_kickoff_task_ids.append(task_id)
    if active_kickoff_task_ids:
        summary = "Team Mode kickoff already in progress."
        comment = (
            "A kickoff task is already queued/running. "
            "Wait for current kickoff execution to finish before retrying."
        )
        return {
            "ok": True,
            "action": "comment",
            "summary": summary,
            "comment": comment,
            "kickoff_dispatched": False,
            "already_in_progress": True,
            "queued_task_ids": active_kickoff_task_ids,
            "queued_by_role": {"Developer": 0, "Lead": len(active_kickoff_task_ids), "QA": 0},
            "failed": [],
            "parallel_limit": max_parallel_dispatch,
            "active_count_before_dispatch": active_count,
        }

    queued_task_ids: list[str] = []
    queued_by_role: dict[str, int] = {"Developer": 0, "Lead": 0, "QA": 0}
    failed: list[dict[str, str]] = []
    for task, role in kickoff_targets:
        task_id = str(task.id or "").strip()
        if not task_id:
            continue
        task_command_id = command_id_with_suffix(command_id, f"kickoff-{task_id[:8]}")
        instruction = kickoff_instruction if str(role or "").strip() == "Lead" else _task_instruction(task)
        if not instruction:
            continue
        normalized_role = str(role or "").strip()
        is_lead_kickoff_target = normalized_role == "Lead"
        try:
            request_result = TaskApplicationService(db, user, command_id=task_command_id).request_automation_run(
                task_id,
                TaskAutomationRun(
                    instruction=instruction,
                    source=None if is_lead_kickoff_target else "lead_kickoff_dispatch",
                    execution_intent=bool(flags.get("execution_intent")),
                    execution_kickoff_intent=bool(flags.get("execution_kickoff_intent")) if is_lead_kickoff_target else False,
                    project_creation_intent=bool(flags.get("project_creation_intent")),
                    workflow_scope=str(flags.get("workflow_scope") or "").strip() or "team_mode",
                    execution_mode=(
                        str(flags.get("execution_mode") or "").strip() or "kickoff_only"
                        if is_lead_kickoff_target
                        else "unknown"
                    ),
                    classifier_reason=(
                        str(flags.get("reason") or "").strip() or None
                        if is_lead_kickoff_target
                        else "Queued by Team Mode kickoff dispatch."
                    ),
                ),
                wake_runner=False,
            )
            if bool((request_result or {}).get("skipped")):
                failed.append(
                    {
                        "task_id": task_id,
                        "error": str((request_result or {}).get("reason") or "Task automation request was skipped.").strip(),
                    }
                )
                continue
            queued_task_ids.append(task_id)
            queued_by_role[normalized_role] = int(queued_by_role.get(normalized_role, 0)) + 1
        except HTTPException as exc:
            failed.append({"task_id": task_id, "error": str(exc.detail or "").strip() or f"HTTP {exc.status_code}"})
        except Exception as exc:  # pragma: no cover
            failed.append({"task_id": task_id, "error": str(exc)[:200]})

    kickoff_ok = len(queued_task_ids) > 0 and not failed
    queued_dev = int(queued_by_role.get("Developer", 0))
    queued_lead = int(queued_by_role.get("Lead", 0))
    queued_qa = int(queued_by_role.get("QA", 0))
    if not kickoff_ok:
        message = (
            f"Team Mode kickoff failed for project {normalized_project_id}: "
            f"{len(queued_task_ids)} task(s) queued (Dev={queued_dev}, Lead={queued_lead}, QA={queued_qa}), "
            f"{len(failed)} queue attempt(s) failed."
        )
        dedupe_key = command_id_with_suffix(command_id, "team-mode-kickoff-notify")
        append_notification_created_event(
            db,
            append_event_fn=append_event,
            user_id=str(user.id),
            message=message,
            actor_id=str(user.id),
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            notification_type="ManualMessage",
            severity="warning",
            dedupe_key=dedupe_key,
            payload={
                "kind": "team_mode_kickoff",
                "queued_task_ids": queued_task_ids,
                "queued_by_role": queued_by_role,
                "failed": failed,
            },
            source_event="agents.chat.kickoff_dispatch",
        )
        db.commit()

    developer_dispatch_state = {
        "developer_task_ids": [],
        "developer_active_task_ids": [],
        "developer_idle_task_ids": [],
        "developer_dispatch_confirmed": False,
    }
    kickoff_processing_error: str | None = None
    if kickoff_ok and queued_task_ids:
        try:
            from features.agents.runner import run_queued_automation_once

            run_queued_automation_once(limit=max(1, len(queued_task_ids)), allow_fresh_kickoff=True)
            with SessionLocal() as verify_db:
                developer_dispatch_state = _collect_team_mode_developer_dispatch_state(
                    db=verify_db,
                    workspace_id=workspace_id,
                    project_id=normalized_project_id,
                )
        except Exception as exc:  # pragma: no cover
            kickoff_processing_error = str(exc)[:300]

    if kickoff_ok:
        if kickoff_processing_error:
            summary = "Team Mode kickoff dispatched; immediate verification is pending."
            comment = (
                f"Queued tasks: {len(queued_task_ids)} (Dev={queued_dev}, Lead={queued_lead}, QA={queued_qa}). "
                "Kickoff processing encountered a transient verification error, but queueing succeeded: "
                f"{kickoff_processing_error}"
            )
        elif not bool(developer_dispatch_state.get("developer_dispatch_confirmed")):
            summary = "Team Mode kickoff dispatched; Developer execution is still propagating."
            comment = (
                f"Queued tasks: {len(queued_task_ids)} (Dev={queued_dev}, Lead={queued_lead}, QA={queued_qa}). "
                "No Developer task is active yet on the immediate readback; this remains in progress."
            )
        else:
            active_dev = len(developer_dispatch_state.get("developer_active_task_ids") or [])
            summary = "Team Mode kickoff dispatched to task automation."
            comment = (
                f"Queued tasks: {len(queued_task_ids)} (Dev={queued_dev}, Lead={queued_lead}, QA={queued_qa}). "
                f"Developer tasks started: {active_dev}."
            )
    else:
        summary = "Team Mode kickoff partially failed."
        comment = (
            f"Queued tasks: {len(queued_task_ids)} (Dev={queued_dev}, Lead={queued_lead}, QA={queued_qa}). "
            f"Failed queues: {len(failed)}."
        )
    return {
        "ok": kickoff_ok,
        "action": "comment",
        "summary": summary,
        "comment": comment,
        "kickoff_dispatched": kickoff_ok,
        "queued_task_ids": queued_task_ids,
        "queued_by_role": queued_by_role,
        "failed": failed,
        "parallel_limit": max_parallel_dispatch,
        "active_count_before_dispatch": active_count,
        "available_slots_before_dispatch": available_slots_before_dispatch,
        "developer_dispatch_confirmed": bool(developer_dispatch_state.get("developer_dispatch_confirmed")),
        "developer_task_ids": list(developer_dispatch_state.get("developer_task_ids") or []),
        "developer_active_task_ids": list(developer_dispatch_state.get("developer_active_task_ids") or []),
        "developer_idle_task_ids": list(developer_dispatch_state.get("developer_idle_task_ids") or []),
    }
