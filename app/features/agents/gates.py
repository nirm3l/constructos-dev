from __future__ import annotations

import json
import os
import re
import subprocess
from copy import deepcopy
from typing import Any, Callable
from shared.schedule import parse_recurring_rule

COMMIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
GATE_POLICY_RULE_TITLES = ("gate policy", "delivery gates", "workflow gates")
DEFAULT_REQUIRED_TEAM_MODE_CHECKS: list[str] = [
    "dev_tasks_have_automation_instruction",
    "qa_tasks_have_automation_instruction",
    "lead_tasks_have_automation_instruction",
    "role_coverage_present",
    "dev_self_triggers_to_qa",
    "qa_external_trigger_from_dev",
    "qa_external_trigger_requests_automation",
    "lead_external_trigger_from_qa",
    "lead_external_trigger_requests_automation",
    "lead_external_trigger_from_blocked_work",
    "lead_external_trigger_from_blocked_work_requests_automation",
    "lead_recurring_schedule_on_lead",
    "lead_recurring_cadence_ok",
    "lead_oversight_not_done_before_delivery_complete",
    "required_triggers_present",
    "event_storming_matches_expectation",
    "deploy_target_declared",
]
DEFAULT_REQUIRED_DELIVERY_CHECKS: list[str] = [
    "repo_context_present",
    "git_contract_ok",
    "dev_tasks_have_commit_evidence",
    "dev_tasks_have_unique_commit_evidence",
    "dev_tasks_have_automation_run_evidence",
    "qa_tasks_have_automation_run_evidence",
    "lead_tasks_have_automation_run_evidence",
    "qa_has_verifiable_artifacts",
    "deploy_execution_evidence_present",
]
TEAM_MODE_CHECK_DESCRIPTIONS: dict[str, str] = {
    "dev_tasks_have_automation_instruction": "Each Dev task has non-empty automation instruction content.",
    "qa_tasks_have_automation_instruction": "Each QA task has non-empty automation instruction content.",
    "lead_tasks_have_automation_instruction": "Each Lead task has non-empty automation instruction content.",
    "role_coverage_present": "Project has Developer, QA, and Team Lead role coverage.",
    "dev_self_triggers_to_qa": "Each Dev task has self status trigger into QA.",
    "qa_external_trigger_from_dev": "QA task has external trigger sourced from Dev task IDs.",
    "qa_external_trigger_requests_automation": "QA external trigger from Dev is configured to request automation execution.",
    "lead_external_trigger_from_qa": "Lead task has external trigger sourced from QA Done/Blocked handoff.",
    "lead_external_trigger_requests_automation": "Lead external trigger from QA Done/Blocked handoff is configured to request automation execution.",
    "lead_external_trigger_from_blocked_work": "Lead task has external trigger sourced from blocked Dev/QA tasks.",
    "lead_external_trigger_from_blocked_work_requests_automation": "Lead blocked-work trigger is configured to request automation execution.",
    "deploy_external_trigger_from_lead": "Deploy task has external trigger sourced from another Lead task.",
    "deploy_external_trigger_from_lead_required": "Deploy-from-Lead trigger is required only when multiple Lead tasks exist.",
    "lead_recurring_schedule_on_lead": "Lead has recurring schedule configured to run on Lead status.",
    "lead_recurring_cadence_ok": "Lead recurring oversight cadence is within the configured maximum interval.",
    "lead_oversight_not_done_before_delivery_complete": "Lead oversight recurring task is not marked Done before delivery handoff completes.",
    "deploy_target_declared": "Deploy task artifacts declare a deploy target port.",
    "deploy_stack_declared": "Deploy task artifacts declare a deploy stack/project name.",
    "deploy_task_has_evidence": "Deploy task contains deploy intent or evidence artifacts.",
    "handoff_direction_clean": "No contradictory handoff triggers were detected.",
    "dev_external_trigger_to_qa_conflict": "Conflict flag when Dev tasks incorrectly use external trigger to QA.",
    "qa_external_trigger_to_done_conflict": "Conflict flag when QA tasks incorrectly use external trigger to Done.",
    "required_triggers_present": "Core Team Mode trigger chain is fully present.",
    "event_storming_matches_expectation": "Project event-storming flag matches expected state.",
}
DELIVERY_CHECK_DESCRIPTIONS: dict[str, str] = {
    "repo_context_present": "Repository context is discoverable from project metadata/rules/refs.",
    "git_contract_ok": "Git delivery contract is satisfied end-to-end.",
    "dev_tasks_have_commit_evidence": "Each Dev task includes commit evidence.",
    "dev_tasks_have_unique_commit_evidence": "Dev tasks use distinct commit evidence (no shared SHA across Dev tasks).",
    "dev_tasks_have_automation_run_evidence": "Each Dev task includes automation run evidence.",
    "qa_tasks_have_automation_run_evidence": "Each QA task includes automation run evidence.",
    "lead_tasks_have_automation_run_evidence": "Each Lead task includes automation run evidence.",
    "qa_has_verifiable_artifacts": "QA tasks include verifiable artifacts (logs, links, evidence notes).",
    "deploy_execution_evidence_required": "Deploy evidence is required when Team Mode has deploy tasks.",
    "deploy_execution_evidence_present": "Deploy execution evidence exists for Lead deploy tasks.",
    "runtime_deploy_health_required": "Runtime health probe is required by gate policy.",
    "runtime_deploy_health_ok": "Runtime deploy stack is up, mapped, and healthy when required.",
}


def _build_gate_check_catalog() -> dict[str, list[dict[str, Any]]]:
    team_mode_required = set(DEFAULT_REQUIRED_TEAM_MODE_CHECKS)
    delivery_required = set(DEFAULT_REQUIRED_DELIVERY_CHECKS)
    return {
        "team_mode": [
            {
                "id": check_id,
                "label": check_id.replace("_", " "),
                "description": TEAM_MODE_CHECK_DESCRIPTIONS.get(check_id, ""),
                "default_required": check_id in team_mode_required,
            }
            for check_id in TEAM_MODE_CHECK_EVALUATORS
        ],
        "delivery": [
            {
                "id": check_id,
                "label": check_id.replace("_", " "),
                "description": DELIVERY_CHECK_DESCRIPTIONS.get(check_id, ""),
                "default_required": check_id in delivery_required,
            }
            for check_id in DELIVERY_CHECK_EVALUATORS
        ],
    }


def gate_check_catalog_by_scope() -> dict[str, list[dict[str, Any]]]:
    return deepcopy(_build_gate_check_catalog())


def _build_default_gate_policy() -> dict[str, Any]:
    return {
    "version": 1,
    "mode": "execution",
    "required_checks": {
        "team_mode": list(DEFAULT_REQUIRED_TEAM_MODE_CHECKS),
        "delivery": list(DEFAULT_REQUIRED_DELIVERY_CHECKS),
    },
    "available_checks": {
        "team_mode": TEAM_MODE_CHECK_DESCRIPTIONS,
        "delivery": DELIVERY_CHECK_DESCRIPTIONS,
    },
    "runtime_deploy_health": {
        "required": False,
        "stack": "constructos-ws-default",
        "port": None,
        "health_path": "/health",
        "require_http_200": True,
    },
    "team_mode": {
        "lead_recurring_max_minutes": 5,
    },
}
DEFAULT_GATE_POLICY: dict[str, Any] = _build_default_gate_policy()


def merge_gate_policy_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_gate_policy_dict(dict(merged.get(key) or {}), value)
        else:
            merged[key] = value
    return merged


def parse_gate_policy_rule(*, project_rules: list[Any]) -> tuple[dict[str, Any], str]:
    policy = dict(DEFAULT_GATE_POLICY)
    source = "default"
    for rule in reversed(list(project_rules)):
        title = str(getattr(rule, "title", "") or "").strip().lower()
        if not any(marker in title for marker in GATE_POLICY_RULE_TITLES):
            continue
        raw_body = str(getattr(rule, "body", "") or "").strip()
        if not raw_body:
            continue
        candidate_text = raw_body
        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_body, flags=re.IGNORECASE | re.DOTALL)
        if fenced_match:
            candidate_text = str(fenced_match.group(1) or "").strip()
        try:
            parsed = json.loads(candidate_text)
        except Exception:
            continue
        if isinstance(parsed, dict):
            policy = merge_gate_policy_dict(policy, parsed)
            source = f"project_rule:{getattr(rule, 'id', '')}"
            break
    return policy, source


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


TEAM_MODE_CHECK_EVALUATORS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "dev_tasks_have_automation_instruction": lambda f: bool(f["dev_instruction_ok"]),
    "qa_tasks_have_automation_instruction": lambda f: bool(f["qa_instruction_ok"]),
    "lead_tasks_have_automation_instruction": lambda f: bool(f["lead_instruction_ok"]),
    "role_coverage_present": lambda f: bool(f["role_coverage_ok"]),
    "dev_self_triggers_to_qa": lambda f: bool(f["dev_self_ok"]),
    "qa_external_trigger_from_dev": lambda f: bool(f["qa_external_from_dev_ok"]),
    "qa_external_trigger_requests_automation": lambda f: bool(f["qa_external_from_dev_automation_ok"]),
    "lead_external_trigger_from_qa": lambda f: bool(f["lead_external_from_qa_ok"]),
    "lead_external_trigger_requests_automation": lambda f: bool(f["lead_external_from_qa_automation_ok"]),
    "lead_external_trigger_from_blocked_work": lambda f: bool(f["lead_external_from_blocked_work_ok"]),
    "lead_external_trigger_from_blocked_work_requests_automation": lambda f: bool(f["lead_external_from_blocked_work_automation_ok"]),
    "deploy_external_trigger_from_lead": lambda f: bool(f["deploy_external_from_lead_ok"]),
    "deploy_external_trigger_from_lead_required": lambda f: bool(f["deploy_external_required"]),
    "lead_recurring_schedule_on_lead": lambda f: bool(f["lead_recurring_on_lead_ok"]),
    "lead_recurring_cadence_ok": lambda f: bool(f["lead_recurring_cadence_ok"]),
    "lead_oversight_not_done_before_delivery_complete": lambda f: bool(f["lead_oversight_not_done_ok"]),
    "deploy_target_declared": lambda f: bool(f["deploy_target_declared_ok"]),
    "deploy_stack_declared": lambda f: bool(f["deploy_stack_declared_ok"]),
    "deploy_task_has_evidence": lambda f: bool(f["deploy_target_declared_ok"]),
    "handoff_direction_clean": lambda f: bool(f["handoff_direction_clean"]),
    "dev_external_trigger_to_qa_conflict": lambda f: bool(f["dev_external_to_qa_conflict"]),
    "qa_external_trigger_to_done_conflict": lambda f: bool(f["qa_external_to_done_conflict"]),
    "required_triggers_present": lambda f: bool(
        f["dev_instruction_ok"]
        and f["qa_instruction_ok"]
        and f["lead_instruction_ok"]
        and f["dev_self_ok"]
        and f["qa_external_from_dev_ok"]
        and f["qa_external_from_dev_automation_ok"]
        and f["lead_external_from_qa_ok"]
        and f["lead_external_from_qa_automation_ok"]
        and f["lead_external_from_blocked_work_ok"]
        and f["lead_external_from_blocked_work_automation_ok"]
        and (f["deploy_external_from_lead_ok"] if f["deploy_external_required"] else True)
        and f["lead_recurring_on_lead_ok"]
        and f["lead_recurring_cadence_ok"]
        and f["lead_oversight_not_done_ok"]
        and f["handoff_direction_clean"]
        and f["deploy_target_declared_ok"]
    ),
    "event_storming_matches_expectation": lambda f: bool(f["event_storming_ok"]),
}


DELIVERY_CHECK_EVALUATORS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "repo_context_present": lambda f: bool(f["repo_context_present"]),
    "git_contract_ok": lambda f: bool(
        f["repo_context_present"]
        and f["dev_commit_evidence_ok"]
        and f["unique_commit_per_dev_ok"]
    ),
    "dev_tasks_have_commit_evidence": lambda f: bool(f["dev_commit_evidence_ok"]),
    "dev_tasks_have_unique_commit_evidence": lambda f: bool(f["unique_commit_per_dev_ok"]),
    "dev_tasks_have_automation_run_evidence": lambda f: bool(f["dev_automation_run_evidence_ok"]),
    "qa_tasks_have_automation_run_evidence": lambda f: bool(f["qa_automation_run_evidence_ok"]),
    "lead_tasks_have_automation_run_evidence": lambda f: bool(f["lead_automation_run_evidence_ok"]),
    "qa_has_verifiable_artifacts": lambda f: bool(f["qa_artifacts_ok"]),
    "deploy_execution_evidence_required": lambda f: bool(f["deploy_evidence_required"]),
    "deploy_execution_evidence_present": lambda f: bool(f["deploy_execution_evidence_ok"]),
    "runtime_deploy_health_required": lambda f: bool(f["runtime_required"]),
    "runtime_deploy_health_ok": lambda f: bool(f["runtime_ok"]),
}


def run_runtime_deploy_health_check(
    *,
    stack: str,
    port: int | None,
    health_path: str,
    require_http_200: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "stack": stack,
        "port": port,
        "health_path": health_path,
        "stack_running": False,
        "port_mapped": False,
        "http_200": False,
        "ok": False,
        "error": None,
    }
    if not stack:
        result["error"] = "missing_stack"
        return result
    if port is None:
        result["error"] = "missing_port"
        return result
    try:
        proc = subprocess.run(
            ["docker", "compose", "-p", stack, "ps", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        result["error"] = "docker_cli_missing"
        return result
    except subprocess.TimeoutExpired:
        result["error"] = "docker_compose_timeout"
        return result

    if proc.returncode != 0:
        result["error"] = f"docker_compose_ps_failed:{proc.returncode}"
        result["stderr"] = str(proc.stderr or "").strip()
        return result

    rows: list[dict[str, Any]] = []
    payload = str(proc.stdout or "").strip()
    if payload:
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, list):
                rows = [item for item in parsed if isinstance(item, dict)]
            elif isinstance(parsed, dict):
                rows = [parsed]
        except Exception:
            rows = []
            for line in payload.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed_line = json.loads(line)
                except Exception:
                    continue
                if isinstance(parsed_line, dict):
                    rows.append(parsed_line)

    if rows:
        result["stack_running"] = any(str(item.get("State") or "").strip().lower() == "running" for item in rows)
        for item in rows:
            publishers = item.get("Publishers")
            if not isinstance(publishers, list):
                continue
            for pub in publishers:
                if not isinstance(pub, dict):
                    continue
                published = pub.get("PublishedPort")
                try:
                    if int(published) == int(port):
                        result["port_mapped"] = True
                        break
                except Exception:
                    continue
            if result["port_mapped"]:
                break

    if require_http_200:
        if result["port_mapped"]:
            probe_hosts: list[str] = []
            if os.path.exists("/.dockerenv"):
                probe_hosts.append("host.docker.internal")
                probe_hosts.extend(["172.17.0.1", "172.18.0.1", "172.19.0.1"])
            probe_hosts.extend(["127.0.0.1", "localhost"])
            deduped_probe_hosts: list[str] = []
            for host in probe_hosts:
                normalized = str(host or "").strip().lower()
                if not normalized or normalized in deduped_probe_hosts:
                    continue
                deduped_probe_hosts.append(normalized)
            try:
                import urllib.request

                for host in deduped_probe_hosts:
                    url = f"http://{host}:{int(port)}{health_path}"
                    try:
                        with urllib.request.urlopen(url, timeout=3) as response:
                            result["http_status"] = int(getattr(response, "status", 0) or 0)
                            result["http_200"] = result["http_status"] == 200
                            if result["http_200"]:
                                result["http_url"] = url
                                break
                    except Exception as exc:  # pragma: no cover - platform/network dependent
                        result["http_error"] = str(exc)
            except Exception as exc:  # pragma: no cover - platform/network dependent
                result["http_error"] = str(exc)
    else:
        result["http_200"] = True

    result["ok"] = bool(result["stack_running"] and result["port_mapped"] and result["http_200"])
    return result


def evaluate_team_mode_gates(
    *,
    project_id: str,
    workspace_id: str,
    event_storming_enabled: bool,
    expected_event_storming_enabled: bool | None,
    gate_policy: dict[str, Any],
    gate_policy_source: str,
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
        team_mode_cfg = gate_policy.get("team_mode") if isinstance(gate_policy.get("team_mode"), dict) else {}
        raw = team_mode_cfg.get("lead_recurring_max_minutes") if isinstance(team_mode_cfg, dict) else None
        try:
            parsed = int(raw)
        except Exception:
            parsed = 5
        return max(1, parsed)

    dev_tasks = [t for t in tasks if member_role_by_user_id.get(str(t.get("assignee_id") or "")) == "DeveloperAgent"]
    qa_tasks = [t for t in tasks if member_role_by_user_id.get(str(t.get("assignee_id") or "")) == "QAAgent"]
    lead_tasks = [t for t in tasks if member_role_by_user_id.get(str(t.get("assignee_id") or "")) == "TeamLeadAgent"]
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
            _has_status_trigger(trigger, scope="self", to_status="QA")
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in dev_tasks
    )
    qa_external_from_dev_ok = any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="QA")
            and dev_ids.issubset({str(task_id) for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])})
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in qa_tasks
    )
    qa_external_from_dev_automation_ok = any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="QA")
            and dev_ids.issubset({str(task_id) for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])})
            and _is_automation_action(trigger.get("action"))
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in qa_tasks
    )
    lead_external_from_qa_done_ok = any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="Done")
            and bool(qa_ids.intersection({str(task_id) for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])}))
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in lead_tasks
    )
    lead_external_from_qa_done_automation_ok = any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="Done")
            and bool(qa_ids.intersection({str(task_id) for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])}))
            and _is_automation_action(trigger.get("action"))
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in lead_tasks
    )
    lead_external_from_qa_blocked_ok = any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="Blocked")
            and bool(qa_ids.intersection({str(task_id) for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])}))
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in lead_tasks
    )
    lead_external_from_qa_blocked_automation_ok = any(
        any(
            _has_status_trigger(trigger, scope="external", to_status="Blocked")
            and bool(qa_ids.intersection({str(task_id) for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])}))
            and _is_automation_action(trigger.get("action"))
            for trigger in (task.get("execution_triggers") or [])
            if isinstance(trigger, dict)
        )
        for task in lead_tasks
    )
    lead_external_from_qa_ok = lead_external_from_qa_done_ok and lead_external_from_qa_blocked_ok
    lead_external_from_qa_automation_ok = (
        lead_external_from_qa_done_automation_ok and lead_external_from_qa_blocked_automation_ok
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
        "qa_external_from_dev_ok": qa_external_from_dev_ok,
        "qa_external_from_dev_automation_ok": qa_external_from_dev_automation_ok,
        "lead_external_from_qa_ok": lead_external_from_qa_ok,
        "lead_external_from_qa_automation_ok": lead_external_from_qa_automation_ok,
        "lead_external_from_blocked_work_ok": lead_external_from_blocked_work_ok,
        "lead_external_from_blocked_work_automation_ok": lead_external_from_blocked_work_automation_ok,
        "deploy_external_from_lead_ok": deploy_external_from_lead_ok,
        "deploy_external_required": deploy_external_required,
        "lead_recurring_on_lead_ok": lead_recurring_on_lead_ok,
        "lead_recurring_cadence_ok": lead_recurring_cadence_ok,
        "lead_oversight_not_done_ok": lead_oversight_not_done_ok,
        "deploy_target_declared_ok": deploy_target_declared_ok,
        "deploy_stack_declared_ok": deploy_stack_declared_ok,
        "handoff_direction_clean": handoff_direction_clean,
        "dev_external_to_qa_conflict": dev_external_to_qa_conflict,
        "qa_external_to_done_conflict": qa_external_to_done_conflict,
        "event_storming_ok": event_storming_ok,
    }
    checks = evaluate_check_registry(registry=TEAM_MODE_CHECK_EVALUATORS, facts=facts)
    required_checks = policy_required_checks(
        gate_policy,
        "team_mode",
        [
            "dev_tasks_have_automation_instruction",
            "qa_tasks_have_automation_instruction",
            "lead_tasks_have_automation_instruction",
            "role_coverage_present",
            "dev_self_triggers_to_qa",
            "qa_external_trigger_from_dev",
            "qa_external_trigger_requests_automation",
            "lead_external_trigger_from_qa",
            "lead_external_trigger_requests_automation",
            "lead_external_trigger_from_blocked_work",
            "lead_external_trigger_from_blocked_work_requests_automation",
            "lead_recurring_schedule_on_lead",
            "lead_recurring_cadence_ok",
            "lead_oversight_not_done_before_delivery_complete",
            "required_triggers_present",
            "event_storming_matches_expectation",
            "deploy_target_declared",
        ],
    )
    checks_ok, required_failed = evaluate_required_checks(checks, required_checks)
    return {
        "project_id": str(project_id),
        "workspace_id": str(workspace_id),
        "checks": checks,
        "available_checks": list(TEAM_MODE_CHECK_EVALUATORS.keys()),
        "check_descriptions": dict(TEAM_MODE_CHECK_DESCRIPTIONS),
        "required_checks": required_checks,
        "required_failed_checks": required_failed,
        "gate_policy": gate_policy,
        "gate_policy_source": gate_policy_source,
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


def evaluate_delivery_gates(
    *,
    project_id: str,
    workspace_id: str,
    gate_policy: dict[str, Any],
    gate_policy_source: str,
    tasks: list[dict[str, Any]],
    member_role_by_user_id: dict[str, str],
    notes_by_task: dict[str, list[Any]],
    comments_by_task: dict[str, list[Any]],
    project_rules: list[Any],
    project_skills: list[Any],
    project_description: str,
    project_external_refs: Any,
    extract_commit_shas_from_refs: Callable[[Any], set[str]],
    extract_commit_shas_from_text: Callable[[str], set[str]],
    parse_json_list: Callable[[Any], list[dict[str, Any]]],
    has_http_external_ref: Callable[[Any], bool],
    has_qa_artifact_text: Callable[[str], bool],
    has_deploy_artifact_text: Callable[[str], bool],
    resolve_deploy_target_from_artifacts: Callable[..., tuple[str, int | None, str]],
    run_runtime_deploy_health_check_fn: Callable[..., dict[str, Any]],
    project_has_repo_context: Callable[..., bool],
) -> dict[str, Any]:
    def _task_has_automation_run(task: dict[str, Any]) -> bool:
        return bool(str(task.get("last_agent_run_at") or "").strip())

    role_dev_tasks = [t for t in tasks if member_role_by_user_id.get(str(t.get("assignee_id") or "")) == "DeveloperAgent"]
    role_qa_tasks = [t for t in tasks if member_role_by_user_id.get(str(t.get("assignee_id") or "")) == "QAAgent"]
    role_lead_tasks = [t for t in tasks if member_role_by_user_id.get(str(t.get("assignee_id") or "")) == "TeamLeadAgent"]
    dev_tasks = role_dev_tasks or [t for t in tasks if str(t.get("status") or "").strip() == "Dev"]
    qa_tasks = role_qa_tasks or [t for t in tasks if str(t.get("status") or "").strip() == "QA"]
    lead_deploy_tasks = [
        task for task in role_lead_tasks if "deploy" in str(task.get("title") or "").lower() or "docker compose" in str(task.get("title") or "").lower()
    ]
    team_mode_enabled = any(str(getattr(skill, "skill_key", "") or "").strip() == "team_mode" for skill in project_skills)

    def _task_commit_shas(task: dict[str, Any]) -> set[str]:
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            return set()
        shas: set[str] = set()
        shas.update(extract_commit_shas_from_refs(task.get("external_refs")))
        for note in notes_by_task.get(task_id, []):
            shas.update(extract_commit_shas_from_text(f"{note.title or ''}\n{note.body or ''}"))
            shas.update(extract_commit_shas_from_refs(note.external_refs))
        for comment in comments_by_task.get(task_id, []):
            shas.update(extract_commit_shas_from_text(comment.body))
        return shas

    def _task_has_qa_artifacts(task: dict[str, Any]) -> bool:
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            return False
        if has_http_external_ref(task.get("external_refs")):
            return True
        for note in notes_by_task.get(task_id, []):
            if has_qa_artifact_text(f"{note.title or ''}\n{note.body or ''}"):
                return True
            if has_http_external_ref(parse_json_list(note.external_refs)):
                return True
        for comment in comments_by_task.get(task_id, []):
            if has_qa_artifact_text(comment.body):
                return True
        return False

    def _task_has_deploy_artifacts(task: dict[str, Any]) -> bool:
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            return False
        if has_http_external_ref(task.get("external_refs")):
            return True
        if has_deploy_artifact_text(
            "\n".join([str(task.get("title") or ""), str(task.get("description") or ""), str(task.get("instruction") or "")])
        ):
            return True
        for note in notes_by_task.get(task_id, []):
            if has_deploy_artifact_text(f"{note.title or ''}\n{note.body or ''}"):
                return True
            if has_http_external_ref(parse_json_list(note.external_refs)):
                return True
        for comment in comments_by_task.get(task_id, []):
            if has_deploy_artifact_text(comment.body):
                return True
        return False

    task_commit_shas: dict[str, set[str]] = {}
    for task in dev_tasks:
        task_id = str(task.get("id") or "").strip()
        if task_id:
            task_commit_shas[task_id] = _task_commit_shas(task)

    commit_to_tasks: dict[str, set[str]] = {}
    for task_id, shas in task_commit_shas.items():
        for sha in shas:
            commit_to_tasks.setdefault(sha, set()).add(task_id)
    duplicated_commits = sorted(sha for sha, task_ids in commit_to_tasks.items() if len(task_ids) > 1)
    unique_commit_per_dev_ok = bool(dev_tasks) and not duplicated_commits

    dev_missing = [
        {"task_id": str(task.get("id") or "").strip(), "title": str(task.get("title") or "").strip() or str(task.get("id") or "").strip()}
        for task in dev_tasks
        if not task_commit_shas.get(str(task.get("id") or "").strip(), set())
    ]
    qa_missing = [
        {"task_id": str(task.get("id") or "").strip(), "title": str(task.get("title") or "").strip() or str(task.get("id") or "").strip()}
        for task in qa_tasks
        if not _task_has_qa_artifacts(task)
    ]
    deploy_missing = [
        {"task_id": str(task.get("id") or "").strip(), "title": str(task.get("title") or "").strip() or str(task.get("id") or "").strip()}
        for task in lead_deploy_tasks
        if not _task_has_deploy_artifacts(task)
    ]
    runtime_policy_raw = gate_policy.get("runtime_deploy_health") if isinstance(gate_policy, dict) else {}
    runtime_policy = runtime_policy_raw if isinstance(runtime_policy_raw, dict) else {}
    runtime_required = bool(runtime_policy.get("required"))
    runtime_stack, runtime_port, runtime_health_path = resolve_deploy_target_from_artifacts(
        deploy_tasks=lead_deploy_tasks,
        notes_by_task=notes_by_task,
        comments_by_task=comments_by_task,
        runtime_policy=runtime_policy,
    )
    runtime_require_http_200 = bool(runtime_policy.get("require_http_200", True))
    runtime_check = (
        run_runtime_deploy_health_check_fn(
            stack=runtime_stack,
            port=runtime_port,
            health_path=runtime_health_path,
            require_http_200=runtime_require_http_200,
        )
        if runtime_required
        else {
            "stack": runtime_stack,
            "port": runtime_port,
            "health_path": runtime_health_path,
            "stack_running": False,
            "port_mapped": False,
            "http_200": False,
            "ok": True,
            "skipped": True,
            "reason": "runtime_deploy_health_not_required",
        }
    )
    runtime_ok = bool(runtime_check.get("ok"))

    repo_context_present = project_has_repo_context(
        project_description=project_description,
        project_external_refs=project_external_refs,
        project_rules=project_rules,
    )
    dev_commit_evidence_ok = bool(dev_tasks) and not dev_missing
    dev_automation_run_evidence_ok = bool(dev_tasks) and all(_task_has_automation_run(task) for task in dev_tasks)
    qa_automation_run_evidence_ok = bool(qa_tasks) and all(_task_has_automation_run(task) for task in qa_tasks)
    lead_automation_run_evidence_ok = bool(role_lead_tasks) and all(_task_has_automation_run(task) for task in role_lead_tasks)
    qa_artifacts_ok = bool(qa_tasks) and not qa_missing
    deploy_evidence_required = bool(team_mode_enabled and lead_deploy_tasks)
    deploy_execution_evidence_ok = (not deploy_evidence_required) or (not deploy_missing)
    facts = {
        "repo_context_present": repo_context_present,
        "dev_commit_evidence_ok": dev_commit_evidence_ok,
        "unique_commit_per_dev_ok": unique_commit_per_dev_ok,
        "dev_automation_run_evidence_ok": dev_automation_run_evidence_ok,
        "qa_automation_run_evidence_ok": qa_automation_run_evidence_ok,
        "lead_automation_run_evidence_ok": lead_automation_run_evidence_ok,
        "qa_artifacts_ok": qa_artifacts_ok,
        "deploy_evidence_required": deploy_evidence_required,
        "deploy_execution_evidence_ok": deploy_execution_evidence_ok,
        "runtime_required": runtime_required,
        "runtime_ok": runtime_ok,
    }
    checks = evaluate_check_registry(registry=DELIVERY_CHECK_EVALUATORS, facts=facts)
    required_checks = policy_required_checks(
        gate_policy,
        "delivery",
        [
            "repo_context_present",
            "git_contract_ok",
            "dev_tasks_have_commit_evidence",
            "dev_tasks_have_unique_commit_evidence",
            "dev_tasks_have_automation_run_evidence",
            "qa_tasks_have_automation_run_evidence",
            "lead_tasks_have_automation_run_evidence",
            "qa_has_verifiable_artifacts",
            "deploy_execution_evidence_present",
        ],
    )
    checks_ok, required_failed = evaluate_required_checks(checks, required_checks)
    return {
        "project_id": str(project_id),
        "workspace_id": str(workspace_id),
        "checks": checks,
        "available_checks": list(DELIVERY_CHECK_EVALUATORS.keys()),
        "check_descriptions": dict(DELIVERY_CHECK_DESCRIPTIONS),
        "required_checks": required_checks,
        "required_failed_checks": required_failed,
        "gate_policy": gate_policy,
        "gate_policy_source": gate_policy_source,
        "runtime_deploy_health": runtime_check,
        "counts": {
            "tasks_total": len(tasks),
            "developer_tasks": len(dev_tasks),
            "qa_tasks": len(qa_tasks),
            "lead_deploy_tasks": len(lead_deploy_tasks),
            "dev_missing_commit_evidence": len(dev_missing),
            "dev_duplicated_commit_evidence": len(duplicated_commits),
            "qa_missing_artifacts": len(qa_missing),
            "deploy_missing_artifacts": len(deploy_missing),
        },
        "missing": {
            "dev_tasks_missing_commit_evidence": dev_missing,
            "dev_duplicated_commit_shas": duplicated_commits,
            "qa_tasks_missing_artifacts": qa_missing,
            "lead_deploy_tasks_missing_artifacts": deploy_missing,
        },
        "ok": bool(checks_ok),
    }
