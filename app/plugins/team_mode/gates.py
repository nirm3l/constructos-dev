from __future__ import annotations

from typing import Any, Callable

from .task_roles import derive_task_role
from .task_roles import normalize_team_agents
from shared.task_relationships import normalize_task_relationships

DEFAULT_REQUIRED_TEAM_MODE_CHECKS: list[str] = [
    "role_coverage_present",
    "required_topology_present",
    "lead_oversight_not_done_before_delivery_complete",
]
TEAM_MODE_CORE_CHECK_IDS: list[str] = [
    "role_coverage_present",
    "required_topology_present",
    "lead_oversight_not_done_before_delivery_complete",
]
TEAM_MODE_CORE_CHECK_SET: set[str] = set(TEAM_MODE_CORE_CHECK_IDS)

TEAM_MODE_CHECK_DESCRIPTIONS: dict[str, str] = {
    "role_coverage_present": "Project has Developer, QA, and Team Lead role coverage.",
    "lead_oversight_not_done_before_delivery_complete": "Lead oversight recurring task is not marked Done before delivery handoff completes.",
    "required_topology_present": "Core Team Mode topology is fully present.",
}
TEAM_MODE_CORE_CHECK_DESCRIPTIONS: dict[str, str] = {
    check_id: TEAM_MODE_CHECK_DESCRIPTIONS[check_id]
    for check_id in TEAM_MODE_CORE_CHECK_IDS
    if check_id in TEAM_MODE_CHECK_DESCRIPTIONS
}
TEAM_MODE_DIAGNOSTIC_CHECK_IDS: list[str] = [
    check_id for check_id in TEAM_MODE_CHECK_DESCRIPTIONS.keys() if check_id not in TEAM_MODE_CORE_CHECK_SET
]


TEAM_MODE_CHECK_EVALUATORS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "role_coverage_present": lambda f: bool(f["role_coverage_ok"]),
    "lead_oversight_not_done_before_delivery_complete": lambda f: bool(f["lead_oversight_not_done_ok"]),
    "required_topology_present": lambda f: bool(
        f["dev_self_ok"]
        and f["lead_external_from_dev_ok"]
        and f["qa_external_from_lead_ok"]
        and f["lead_external_from_blocked_work_ok"]
        and (f["deploy_external_from_lead_ok"] if f["deploy_external_required"] else True)
        and f["handoff_direction_clean"]
    ),
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
    team_agents = normalize_team_agents(
        (plugin_policy.get("team") if isinstance(plugin_policy.get("team"), dict) else {})
    )
    agent_role_by_code = {
        str(agent.get("id") or "").strip(): str(agent.get("authority_role") or "").strip()
        for agent in team_agents
        if str(agent.get("id") or "").strip()
    }
    def _has_status_trigger(trigger: dict[str, Any], *, scope: str, to_status: str) -> bool:
        if str(trigger.get("kind") or "").strip() != "status_change":
            return False
        if str(trigger.get("scope") or "").strip() != scope:
            return False
        to_statuses = [str(item or "").strip() for item in (trigger.get("to_statuses") or [])]
        return to_status in to_statuses

    def _task_relationships(task: dict[str, Any]) -> list[dict[str, Any]]:
        return normalize_task_relationships(task.get("task_relationships"))

    def _has_relationship(
        task: dict[str, Any],
        *,
        kind: str,
        source_ids_subset: set[str],
        statuses_subset: set[str] | None = None,
    ) -> bool:
        for relationship in _task_relationships(task):
            if str(relationship.get("kind") or "").strip().lower() != kind:
                continue
            task_ids = {str(item or "").strip() for item in (relationship.get("task_ids") or []) if str(item or "").strip()}
            if source_ids_subset and not source_ids_subset.issubset(task_ids):
                continue
            if statuses_subset:
                statuses = {str(item or "").strip() for item in (relationship.get("statuses") or []) if str(item or "").strip()}
                if not statuses_subset.issubset(statuses):
                    continue
            return True
        return False

    dev_tasks = [
        t
        for t in tasks
        if derive_task_role(
            task_like=t,
            member_role_by_user_id=member_role_by_user_id,
            agent_role_by_code=agent_role_by_code,
        )
        == "Developer"
    ]
    qa_tasks = [
        t
        for t in tasks
        if derive_task_role(
            task_like=t,
            member_role_by_user_id=member_role_by_user_id,
            agent_role_by_code=agent_role_by_code,
        )
        == "QA"
    ]
    lead_tasks = [
        t
        for t in tasks
        if derive_task_role(
            task_like=t,
            member_role_by_user_id=member_role_by_user_id,
            agent_role_by_code=agent_role_by_code,
        )
        == "Lead"
    ]

    def _task_has_explicit_deploy_signal(task: dict[str, Any]) -> bool:
        deploy_snapshot = task.get("last_deploy_execution") if isinstance(task.get("last_deploy_execution"), dict) else {}
        if str(deploy_snapshot.get("executed_at") or "").strip():
            return True
        refs = task.get("external_refs")
        if not isinstance(refs, list):
            return False
        for item in refs:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip().casefold()
            if url.startswith("deploy:stack:") or url.startswith("deploy:command:") or url.startswith("deploy:health:"):
                return True
            if url.startswith("deploy:compose:") or url.startswith("deploy:runtime:"):
                return True
        return False

    deploy_tasks = [task for task in lead_tasks if _task_has_explicit_deploy_signal(task)]

    dev_ids = {str(t.get("id")) for t in dev_tasks}
    qa_ids = {str(t.get("id")) for t in qa_tasks}
    lead_ids = {str(t.get("id")) for t in lead_tasks}
    dev_self_ok = bool(dev_tasks) and all(
        any(
            _has_relationship(task, kind="delivers_to", source_ids_subset={lead_id}, statuses_subset={"Lead"})
            for lead_id in lead_ids
        )
        for task in dev_tasks
    )
    lead_external_from_dev_ok = any(
        _has_relationship(task, kind="depends_on", source_ids_subset=dev_ids, statuses_subset={"Lead"})
        for task in lead_tasks
    )
    qa_external_from_lead_ok = any(
        any(
            _has_relationship(task, kind="hands_off_to", source_ids_subset={lead_id}, statuses_subset={"QA"})
            for lead_id in lead_ids
        )
        for task in qa_tasks
    )
    blocked_source_task_ids: set[str] = set()
    for task in lead_tasks:
        for relationship in _task_relationships(task):
            if str(relationship.get("kind") or "").strip().lower() != "depends_on":
                continue
            statuses = {
                str(item or "").strip()
                for item in (relationship.get("statuses") or [])
                if str(item or "").strip()
            }
            if "Blocked" not in statuses:
                continue
            blocked_source_task_ids.update(
                {
                    str(task_id or "").strip()
                    for task_id in (relationship.get("task_ids") or [])
                    if str(task_id or "").strip()
                }
            )
    blocked_work_ids = dev_ids.union(qa_ids)
    lead_external_from_blocked_work_ok = bool(blocked_work_ids) and blocked_work_ids.issubset(blocked_source_task_ids)
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
    dev_external_to_qa_conflict = any(_has_relationship(task, kind="hands_off_to", source_ids_subset=qa_ids, statuses_subset={"QA"}) for task in dev_tasks) or any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="QA")
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in dev_tasks
    )
    qa_external_to_done_conflict = any(_has_relationship(task, kind="depends_on", source_ids_subset=lead_ids, statuses_subset={"Done"}) for task in qa_tasks) or any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="Done")
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in qa_tasks
    )
    handoff_direction_clean = not dev_external_to_qa_conflict and not qa_external_to_done_conflict
    role_coverage_ok = bool(dev_tasks) and bool(qa_tasks) and bool(lead_tasks)

    _unused = (extract_deploy_ports, has_deploy_stack_marker, event_storming_enabled, expected_event_storming_enabled)
    _ = _unused
    facts = {
        "role_coverage_ok": role_coverage_ok,
        "dev_self_ok": dev_self_ok,
        "lead_external_from_dev_ok": lead_external_from_dev_ok,
        "qa_external_from_lead_ok": qa_external_from_lead_ok,
        "lead_external_from_blocked_work_ok": lead_external_from_blocked_work_ok,
        "deploy_external_from_lead_ok": deploy_external_from_lead_ok,
        "deploy_external_required": deploy_external_required,
        "lead_oversight_not_done_ok": lead_oversight_not_done_ok,
        "handoff_direction_clean": handoff_direction_clean,
    }
    checks = evaluate_check_registry(registry=TEAM_MODE_CHECK_EVALUATORS, facts=facts)
    required_checks = policy_required_checks(plugin_policy, "team_mode", DEFAULT_REQUIRED_TEAM_MODE_CHECKS)
    checks_ok, required_failed = evaluate_required_checks(checks, required_checks)
    return {
        "project_id": str(project_id),
        "workspace_id": str(workspace_id),
        "checks": checks,
        "available_checks": list(TEAM_MODE_CORE_CHECK_IDS),
        "diagnostic_checks": list(TEAM_MODE_DIAGNOSTIC_CHECK_IDS),
        "check_descriptions": dict(TEAM_MODE_CHECK_DESCRIPTIONS),
        "core_check_descriptions": dict(TEAM_MODE_CORE_CHECK_DESCRIPTIONS),
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
