from __future__ import annotations

from typing import Any, Callable

from .task_roles import derive_task_role
from .task_roles import normalize_team_agents
from .semantics import REQUIRED_SEMANTIC_STATUSES, is_terminal_status, normalize_oversight, normalize_status_semantics

DEFAULT_REQUIRED_TEAM_MODE_CHECKS: list[str] = [
    "role_coverage_present",
    "single_lead_present",
    "human_owner_present",
    "status_semantics_present",
]
TEAM_MODE_CORE_CHECK_IDS: list[str] = [
    "role_coverage_present",
    "single_lead_present",
    "human_owner_present",
    "status_semantics_present",
]
TEAM_MODE_CORE_CHECK_SET: set[str] = set(TEAM_MODE_CORE_CHECK_IDS)

TEAM_MODE_CHECK_DESCRIPTIONS: dict[str, str] = {
    "role_coverage_present": "Project has Developer, QA, and Team Lead role coverage.",
    "single_lead_present": "Project has exactly one Team Lead agent in Team Mode config.",
    "human_owner_present": "Team Mode oversight has a human owner for escalation and completion notifications.",
    "status_semantics_present": "Team Mode config defines the required semantic statuses.",
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
    "single_lead_present": lambda f: bool(f["single_lead_ok"]),
    "human_owner_present": lambda f: bool(f["human_owner_ok"]),
    "status_semantics_present": lambda f: bool(f["status_semantics_ok"]),
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
    oversight = normalize_oversight(plugin_policy.get("oversight"))
    status_semantics = normalize_status_semantics(plugin_policy.get("status_semantics"))
    configured_roles = {
        str(agent.get("authority_role") or "").strip()
        for agent in team_agents
        if str(agent.get("authority_role") or "").strip()
    }
    role_coverage_ok = {"Developer", "QA", "Lead"}.issubset(configured_roles)
    single_lead_ok = sum(
        1 for agent in team_agents if str(agent.get("authority_role") or "").strip() == "Lead"
    ) == 1
    human_owner_ok = bool(oversight.get("human_owner_user_id"))
    status_semantics_ok = status_semantics == REQUIRED_SEMANTIC_STATUSES

    _unused = (extract_deploy_ports, has_deploy_stack_marker, event_storming_enabled, expected_event_storming_enabled)
    _ = _unused
    facts = {
        "role_coverage_ok": role_coverage_ok,
        "single_lead_ok": single_lead_ok,
        "human_owner_ok": human_owner_ok,
        "status_semantics_ok": status_semantics_ok,
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
            "terminal_tasks": sum(1 for task in tasks if is_terminal_status(status=task.get("status"), status_semantics=status_semantics)),
        },
        "event_storming_enabled": bool(event_storming_enabled),
        "expected_event_storming_enabled": expected_event_storming_enabled,
        "ok": bool(checks_ok),
    }
