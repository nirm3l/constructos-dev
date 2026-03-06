from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .task_roles import derive_task_role
from shared.schedule import parse_recurring_rule

DEFAULT_REQUIRED_TEAM_MODE_CHECKS: list[str] = [
    "role_coverage_present",
    "required_triggers_present",
    "lead_oversight_not_done_before_delivery_complete",
]

TEAM_MODE_CHECK_DESCRIPTIONS: dict[str, str] = {
    "dev_tasks_have_automation_instruction": "Each Dev task has non-empty automation instruction content.",
    "qa_tasks_have_automation_instruction": "Each QA task has non-empty automation instruction content.",
    "lead_tasks_have_automation_instruction": "Each Lead task has non-empty automation instruction content.",
    "role_coverage_present": "Project has Developer, QA, and Team Lead role coverage.",
    "dev_self_triggers_to_lead": "Each Dev task has self status trigger into Lead.",
    "lead_external_trigger_from_dev": "Lead task has external trigger sourced from Dev task IDs.",
    "lead_external_trigger_requests_automation": "Lead external trigger from Dev handoff is configured to request automation execution.",
    "qa_external_trigger_from_lead": "QA task has external trigger sourced from Lead Done handoff.",
    "qa_external_trigger_requests_automation": "QA external trigger from Lead Done handoff is configured to request automation execution.",
    "lead_external_trigger_from_blocked_work": "Lead task has external trigger sourced from blocked Dev/QA tasks.",
    "lead_external_trigger_from_blocked_work_requests_automation": "Lead blocked-work trigger is configured to request automation execution.",
    "deploy_external_trigger_from_lead": "Deploy task has external trigger sourced from another Lead task.",
    "deploy_external_trigger_from_lead_required": "Deploy-from-Lead trigger is required only when multiple Lead tasks exist.",
    "lead_recurring_schedule_on_lead": "Lead has recurring schedule configured to run on Lead status.",
    "lead_recurring_cadence_ok": "Lead recurring oversight cadence is within the configured maximum interval.",
    "lead_recurring_next_due_soon": "Lead recurring oversight next run is near now (not deferred to a distant future timestamp).",
    "lead_oversight_not_done_before_delivery_complete": "Lead oversight recurring task is not marked Done before delivery handoff completes.",
    "deploy_target_declared": "Deploy task artifacts declare a deploy target port.",
    "deploy_stack_declared": "Deploy task artifacts declare a deploy stack/project name.",
    "handoff_direction_clean": "No contradictory handoff triggers were detected.",
    "required_triggers_present": "Core Team Mode trigger chain is fully present.",
    "event_storming_matches_expectation": "Project event-storming flag matches expected state.",
}


TEAM_MODE_CHECK_EVALUATORS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "dev_tasks_have_automation_instruction": lambda f: bool(f["dev_instruction_ok"]),
    "qa_tasks_have_automation_instruction": lambda f: bool(f["qa_instruction_ok"]),
    "lead_tasks_have_automation_instruction": lambda f: bool(f["lead_instruction_ok"]),
    "role_coverage_present": lambda f: bool(f["role_coverage_ok"]),
    "dev_self_triggers_to_lead": lambda f: bool(f["dev_self_ok"]),
    "lead_external_trigger_from_dev": lambda f: bool(f["lead_external_from_dev_ok"]),
    "lead_external_trigger_requests_automation": lambda f: bool(f["lead_external_from_dev_automation_ok"]),
    "qa_external_trigger_from_lead": lambda f: bool(f["qa_external_from_lead_ok"]),
    "qa_external_trigger_requests_automation": lambda f: bool(f["qa_external_from_lead_automation_ok"]),
    "lead_external_trigger_from_blocked_work": lambda f: bool(f["lead_external_from_blocked_work_ok"]),
    "lead_external_trigger_from_blocked_work_requests_automation": lambda f: bool(f["lead_external_from_blocked_work_automation_ok"]),
    "deploy_external_trigger_from_lead": lambda f: bool(f["deploy_external_from_lead_ok"]),
    "deploy_external_trigger_from_lead_required": lambda f: bool(f["deploy_external_required"]),
    "lead_recurring_schedule_on_lead": lambda f: bool(f["lead_recurring_on_lead_ok"]),
    "lead_recurring_cadence_ok": lambda f: bool(f["lead_recurring_cadence_ok"]),
    "lead_recurring_next_due_soon": lambda f: bool(f["lead_recurring_next_due_soon_ok"]),
    "lead_oversight_not_done_before_delivery_complete": lambda f: bool(f["lead_oversight_not_done_ok"]),
    "deploy_target_declared": lambda f: bool(f["deploy_target_declared_ok"]),
    "deploy_stack_declared": lambda f: bool(f["deploy_stack_declared_ok"]),
    "handoff_direction_clean": lambda f: bool(f["handoff_direction_clean"]),
    "required_triggers_present": lambda f: bool(
        f["dev_self_ok"]
        and f["lead_external_from_dev_ok"]
        and f["qa_external_from_lead_ok"]
        and f["lead_external_from_blocked_work_ok"]
        and (f["deploy_external_from_lead_ok"] if f["deploy_external_required"] else True)
        and f["handoff_direction_clean"]
    ),
    "event_storming_matches_expectation": lambda f: bool(f["event_storming_ok"]),
}


def evaluate_check_registry(
    *,
    registry: dict[str, Callable[[dict[str, Any]], bool]],
    facts: dict[str, Any],
) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for check_id, evaluator in registry.items():
        try:
            checks[check_id] = bool(evaluator(facts))
        except Exception:
            checks[check_id] = False
    return checks


def policy_required_checks(policy: dict[str, Any], scope: str, default_checks: list[str]) -> list[str]:
    required = ((policy.get("required_checks") or {}).get(scope) if isinstance(policy.get("required_checks"), dict) else None)
    if isinstance(required, list):
        return [str(item or "").strip() for item in required if str(item or "").strip()]
    return list(default_checks)


def evaluate_required_checks(checks: dict[str, Any], required_checks: list[str]) -> tuple[bool, list[str]]:
    failed: list[str] = []
    for key in required_checks:
        if not bool(checks.get(key)):
            failed.append(key)
    return len(failed) == 0, failed


def evaluate_team_mode_gates(
    *,
    project_id: str,
    workspace_id: str,
    event_storming_enabled: bool,
    expected_event_storming_enabled: bool | None,
    plugin_policy: dict[str, Any],
    plugin_policy_source: str,
    tasks: list[dict[str, Any]],
    member_role_by_user_id: dict[str, str],
    notes_by_task: dict[str, list[Any]],
    comments_by_task: dict[str, list[Any]],
    extract_deploy_ports: Callable[[str], set[str]],
    has_deploy_stack_marker: Callable[[str], bool],
) -> dict[str, Any]:
    automation_actions = {
        "automation",
        "execute_instruction",
        "queue",
        "queue_automation",
        "queue_instruction",
        "request_automation",
        "request_instruction",
        "run",
        "run_automation",
        "run_instruction",
        "run_task_instruction",
        "start_automation",
        "start_instruction",
        "trigger_automation",
        "trigger_instruction",
    }

    def _has_status_trigger(trigger: dict[str, Any], *, scope: str, to_status: str) -> bool:
        if str(trigger.get("kind") or "").strip() != "status_change":
            return False
        if str(trigger.get("scope") or "").strip() != scope:
            return False
        to_statuses = [str(item or "").strip() for item in (trigger.get("to_statuses") or [])]
        return to_status in to_statuses

    def _is_automation_action(action: Any) -> bool:
        if action is None:
            return True
        normalized = ""
        if isinstance(action, dict):
            normalized = str(action.get("type") or action.get("action") or "").strip().casefold()
        else:
            normalized = str(action or "").strip().casefold()
        if not normalized:
            return True
        return normalized in automation_actions

    def _has_instruction(task: dict[str, Any]) -> bool:
        instruction = str(task.get("instruction") or task.get("scheduled_instruction") or "").strip()
        return bool(instruction)

    def _get_lead_recurring_max_minutes() -> int:
        team_mode_cfg = plugin_policy.get("team_mode") if isinstance(plugin_policy.get("team_mode"), dict) else {}
        raw = team_mode_cfg.get("lead_recurring_max_minutes") if isinstance(team_mode_cfg, dict) else None
        try:
            parsed = int(raw)
        except Exception:
            parsed = 5
        return max(1, parsed)

    def _parse_utc(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    dev_tasks = [
        t
        for t in tasks
        if derive_task_role(task_like=t, member_role_by_user_id=member_role_by_user_id) == "Developer"
    ]
    qa_tasks = [
        t
        for t in tasks
        if derive_task_role(task_like=t, member_role_by_user_id=member_role_by_user_id) == "QA"
    ]
    lead_tasks = [
        t
        for t in tasks
        if derive_task_role(task_like=t, member_role_by_user_id=member_role_by_user_id) == "Lead"
    ]
    deploy_tasks = [
        t for t in lead_tasks if "deploy" in str(t.get("title") or "").lower() or "docker compose" in str(t.get("title") or "").lower()
    ]

    dev_ids = {str(t.get("id")) for t in dev_tasks}
    qa_ids = {str(t.get("id")) for t in qa_tasks}
    lead_ids = {str(t.get("id")) for t in lead_tasks}
    dev_instruction_ok = bool(dev_tasks) and all(_has_instruction(task) for task in dev_tasks)
    qa_instruction_ok = bool(qa_tasks) and all(_has_instruction(task) for task in qa_tasks)
    lead_instruction_ok = bool(lead_tasks) and all(_has_instruction(task) for task in lead_tasks)

    dev_self_ok = bool(dev_tasks) and all(
        any(
            _has_status_trigger(trigger, scope="self", to_status="Lead")
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in dev_tasks
    )
    lead_external_from_dev_ok = any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="Lead")
            and dev_ids.issubset({str(task_id) for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])})
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in lead_tasks
    )
    lead_external_from_dev_automation_ok = any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="Lead")
            and dev_ids.issubset({str(task_id) for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])})
            and _is_automation_action(trigger.get("action"))
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in lead_tasks
    )
    qa_external_from_lead_ok = any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="QA")
            and bool(lead_ids.intersection({str(task_id) for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])}))
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in qa_tasks
    )
    qa_external_from_lead_automation_ok = any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="QA")
            and bool(lead_ids.intersection({str(task_id) for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])}))
            and _is_automation_action(trigger.get("action"))
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in qa_tasks
    )
    blocked_source_task_ids: set[str] = set()
    blocked_source_task_ids_with_automation: set[str] = set()
    for task in lead_tasks:
        for trigger in (task.get("execution_triggers") or []):
            if not isinstance(trigger, dict):
                continue
            if not _has_status_trigger(trigger, scope="external", to_status="Blocked"):
                continue
            selector_task_ids = {
                str(task_id or "").strip()
                for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])
                if str(task_id or "").strip()
            }
            blocked_source_task_ids.update(selector_task_ids)
            if _is_automation_action(trigger.get("action")):
                blocked_source_task_ids_with_automation.update(selector_task_ids)
    blocked_work_ids = dev_ids.union(qa_ids)
    lead_external_from_blocked_work_ok = bool(blocked_work_ids) and blocked_work_ids.issubset(blocked_source_task_ids)
    lead_external_from_blocked_work_automation_ok = bool(blocked_work_ids) and blocked_work_ids.issubset(
        blocked_source_task_ids_with_automation
    )
    deploy_external_from_lead_ok = any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="Done")
            and bool(
                (lead_ids - {str(task.get("id") or "")}).intersection(
                    {str(task_id) for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])}
                )
            )
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in deploy_tasks
    )
    deploy_external_required = bool(deploy_tasks) and len(lead_tasks) > 1
    lead_recurring_on_lead_ok = any(
        any(
            str(trigger.get("kind") or "").strip() == "schedule"
            and bool(str(trigger.get("recurring_rule") or "").strip())
            and "Lead" in [str(item or "").strip() for item in (trigger.get("run_on_statuses") or [])]
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in lead_tasks
    )
    lead_recurring_max_minutes = _get_lead_recurring_max_minutes()
    lead_recurring_cadence_ok = any(
        any(
            str(trigger.get("kind") or "").strip() == "schedule"
            and "Lead" in [str(item or "").strip() for item in (trigger.get("run_on_statuses") or [])]
            and (
                (lambda delta: bool(delta) and (delta.total_seconds() <= (lead_recurring_max_minutes * 60)))(
                    parse_recurring_rule(str(trigger.get("recurring_rule") or "").strip())
                )
            )
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in lead_tasks
    )
    now_utc = datetime.now(timezone.utc)
    lead_recurring_next_due_soon_ok = any(
        any(
            str(trigger.get("kind") or "").strip() == "schedule"
            and "Lead" in [str(item or "").strip() for item in (trigger.get("run_on_statuses") or [])]
            and (
                (lambda due: bool(due) and due <= (now_utc + timedelta(minutes=max(2, lead_recurring_max_minutes * 2))))(
                    _parse_utc(trigger.get("scheduled_at_utc"))
                )
            )
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in lead_tasks
    )
    recurring_lead_tasks = [
        task
        for task in lead_tasks
        if any(
            str(trigger.get("kind") or "").strip() == "schedule"
            and "Lead" in [str(item or "").strip() for item in (trigger.get("run_on_statuses") or [])]
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
    ]
    non_recurring_or_non_lead_tasks = [task for task in tasks if str(task.get("id") or "") not in {str(t.get("id") or "") for t in recurring_lead_tasks}]
    non_recurring_work_done = bool(non_recurring_or_non_lead_tasks) and all(
        str(task.get("status") or "").strip() == "Done" for task in non_recurring_or_non_lead_tasks
    )
    lead_oversight_not_done_ok = all(
        str(task.get("status") or "").strip() != "Done" or non_recurring_work_done
        for task in recurring_lead_tasks
    )
    dev_external_to_qa_conflict = any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="QA")
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in dev_tasks
    )
    qa_external_to_done_conflict = any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="Done")
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in qa_tasks
    )
    handoff_direction_clean = not dev_external_to_qa_conflict and not qa_external_to_done_conflict
    role_coverage_ok = bool(dev_tasks) and bool(qa_tasks) and bool(lead_tasks)

    deploy_target_declared_ok = bool(deploy_tasks) and all(
        (
            len(
                extract_deploy_ports(
                    "\n".join([str(task.get("title") or ""), str(task.get("description") or ""), str(task.get("instruction") or "")])
                )
            )
            > 0
        )
        or any(
            len(extract_deploy_ports(f"{note.title or ''}\n{note.body or ''}")) > 0
            for note in notes_by_task.get(str(task.get("id") or "").strip(), [])
        )
        or any(
            len(extract_deploy_ports(comment.body)) > 0
            for comment in comments_by_task.get(str(task.get("id") or "").strip(), [])
        )
        for task in deploy_tasks
    )
    deploy_stack_declared_ok = bool(deploy_tasks) and all(
        has_deploy_stack_marker(
            "\n".join([str(task.get("title") or ""), str(task.get("description") or ""), str(task.get("instruction") or "")])
        )
        or any(
            has_deploy_stack_marker(f"{note.title or ''}\n{note.body or ''}")
            for note in notes_by_task.get(str(task.get("id") or "").strip(), [])
        )
        or any(
            has_deploy_stack_marker(comment.body)
            for comment in comments_by_task.get(str(task.get("id") or "").strip(), [])
        )
        for task in deploy_tasks
    )

    event_storming_ok = True if expected_event_storming_enabled is None else bool(event_storming_enabled) is bool(expected_event_storming_enabled)
    facts = {
        "dev_instruction_ok": dev_instruction_ok,
        "qa_instruction_ok": qa_instruction_ok,
        "lead_instruction_ok": lead_instruction_ok,
        "role_coverage_ok": role_coverage_ok,
        "dev_self_ok": dev_self_ok,
        "lead_external_from_dev_ok": lead_external_from_dev_ok,
        "lead_external_from_dev_automation_ok": lead_external_from_dev_automation_ok,
        "qa_external_from_lead_ok": qa_external_from_lead_ok,
        "qa_external_from_lead_automation_ok": qa_external_from_lead_automation_ok,
        "lead_external_from_blocked_work_ok": lead_external_from_blocked_work_ok,
        "lead_external_from_blocked_work_automation_ok": lead_external_from_blocked_work_automation_ok,
        "deploy_external_from_lead_ok": deploy_external_from_lead_ok,
        "deploy_external_required": deploy_external_required,
        "lead_recurring_on_lead_ok": lead_recurring_on_lead_ok,
        "lead_recurring_cadence_ok": lead_recurring_cadence_ok,
        "lead_recurring_next_due_soon_ok": lead_recurring_next_due_soon_ok,
        "lead_oversight_not_done_ok": lead_oversight_not_done_ok,
        "deploy_target_declared_ok": deploy_target_declared_ok,
        "deploy_stack_declared_ok": deploy_stack_declared_ok,
        "handoff_direction_clean": handoff_direction_clean,
        "dev_external_to_qa_conflict": dev_external_to_qa_conflict,
        "qa_external_to_done_conflict": qa_external_to_done_conflict,
        "event_storming_ok": event_storming_ok,
    }
    checks = evaluate_check_registry(registry=TEAM_MODE_CHECK_EVALUATORS, facts=facts)
    required_checks = policy_required_checks(plugin_policy, "team_mode", DEFAULT_REQUIRED_TEAM_MODE_CHECKS)
    checks_ok, required_failed = evaluate_required_checks(checks, required_checks)
    return {
        "project_id": str(project_id),
        "workspace_id": str(workspace_id),
        "checks": checks,
        "available_checks": list(TEAM_MODE_CHECK_EVALUATORS.keys()),
        "check_descriptions": dict(TEAM_MODE_CHECK_DESCRIPTIONS),
        "required_checks": required_checks,
        "required_failed_checks": required_failed,
        "plugin_policy": plugin_policy,
        "plugin_policy_source": plugin_policy_source,
        "counts": {
            "tasks_total": len(tasks),
            "developer_tasks": len(dev_tasks),
            "qa_tasks": len(qa_tasks),
            "lead_tasks": len(lead_tasks),
            "deploy_tasks": len(deploy_tasks),
        },
        "event_storming_enabled": bool(event_storming_enabled),
        "expected_event_storming_enabled": expected_event_storming_enabled,
        "ok": bool(checks_ok),
    }
