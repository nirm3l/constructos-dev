from __future__ import annotations

import json
import os
import re
import subprocess
from copy import deepcopy
from typing import Any, Callable
from plugins.base import GateEvaluationContext
from plugins.registry import list_workflow_plugins, plugin_by_key
from plugins.runner_policy import is_developer_role, is_lead_role, is_qa_role
from plugins.team_mode.skill_contract import TEAM_MODE_SKILL_KEY

COMMIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
GATE_POLICY_RULE_TITLES = ("gate policy", "delivery gates", "workflow gates")
DEFAULT_REQUIRED_DELIVERY_CHECKS: list[str] = [
    "repo_context_present",
    "git_contract_ok",
    "dev_tasks_have_commit_evidence",
    "dev_tasks_have_task_branch_evidence",
    "dev_tasks_have_unique_commit_evidence",
    "dev_tasks_have_automation_run_evidence",
    "qa_tasks_have_automation_run_evidence",
    "lead_tasks_have_automation_run_evidence",
    "qa_has_verifiable_artifacts",
    "deploy_execution_evidence_present",
]
DELIVERY_CHECK_DESCRIPTIONS: dict[str, str] = {
    "repo_context_present": "Repository context is discoverable from project metadata/rules/refs.",
    "git_contract_ok": "Git delivery contract is satisfied end-to-end.",
    "dev_tasks_have_commit_evidence": "Each Dev task includes commit evidence.",
    "dev_tasks_have_task_branch_evidence": "Each Dev task includes evidence for its task branch (task/<task-id-prefix>-...).",
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
    plugin_scopes: dict[str, list[dict[str, Any]]] = {}
    for plugin in list_workflow_plugins():
        scope = str(plugin.gate_scope() or "").strip()
        if not scope:
            continue
        required = set(plugin.default_required_checks())
        descriptions = plugin.gate_check_descriptions()
        plugin_scopes[scope] = [
            {
                "id": check_id,
                "label": check_id.replace("_", " "),
                "description": descriptions.get(check_id, ""),
                "default_required": check_id in required,
            }
            for check_id in descriptions.keys()
        ]

    delivery_required = set(DEFAULT_REQUIRED_DELIVERY_CHECKS)
    catalog = {
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
    catalog.update(plugin_scopes)
    return catalog


def gate_check_catalog_by_scope() -> dict[str, list[dict[str, Any]]]:
    return deepcopy(_build_gate_check_catalog())


def _build_default_gate_policy() -> dict[str, Any]:
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = dict(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = _deep_merge(dict(merged.get(key) or {}), value)
            else:
                merged[key] = value
        return merged

    base: dict[str, Any] = {
    "version": 1,
    "mode": "execution",
    "required_checks": {
        "delivery": list(DEFAULT_REQUIRED_DELIVERY_CHECKS),
    },
    "available_checks": {
        "delivery": DELIVERY_CHECK_DESCRIPTIONS,
    },
    "runtime_deploy_health": {
        "required": False,
        "stack": "constructos-ws-default",
        "port": None,
        "health_path": "/health",
        "require_http_200": True,
    },
}
    for plugin in list_workflow_plugins():
        base = _deep_merge(base, plugin.default_gate_policy_patch())
    return base
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
    def _sort_key(rule: Any) -> tuple[Any, str]:
        updated = getattr(rule, "updated_at", None)
        created = getattr(rule, "created_at", None)
        timestamp = updated or created
        return (timestamp, str(getattr(rule, "id", "") or ""))

    ordered_rules = sorted(list(project_rules), key=_sort_key, reverse=True)
    for rule in ordered_rules:
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


DELIVERY_CHECK_EVALUATORS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "repo_context_present": lambda f: bool(f["repo_context_present"]),
    "git_contract_ok": lambda f: bool(
        f["repo_context_present"]
        and f["dev_commit_evidence_ok"]
        and f["dev_task_branch_evidence_ok"]
        and f["unique_commit_per_dev_ok"]
    ),
    "dev_tasks_have_commit_evidence": lambda f: bool(f["dev_commit_evidence_ok"]),
    "dev_tasks_have_task_branch_evidence": lambda f: bool(f["dev_task_branch_evidence_ok"]),
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
    plugin = plugin_by_key(TEAM_MODE_SKILL_KEY)
    if plugin is None:
        return {
            "checks": {},
            "available_checks": [],
            "check_descriptions": {},
            "required_checks": [],
            "required_failed_checks": [],
            "ok": True,
            "source": gate_policy_source,
        }
    return plugin.evaluate_gates(
        GateEvaluationContext(
            project_id=project_id,
            workspace_id=workspace_id,
            event_storming_enabled=event_storming_enabled,
            expected_event_storming_enabled=expected_event_storming_enabled,
            gate_policy=gate_policy,
            gate_policy_source=gate_policy_source,
            tasks=tasks,
            member_role_by_user_id=member_role_by_user_id,
            notes_by_task=notes_by_task,
            comments_by_task=comments_by_task,
        ),
        extract_deploy_ports=extract_deploy_ports,
        has_deploy_stack_marker=has_deploy_stack_marker,
    )


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
    branch_regex = re.compile(r"\btask/([a-z0-9][a-z0-9._/-]*)\b", re.IGNORECASE)

    def _task_has_automation_run(task: dict[str, Any]) -> bool:
        return bool(str(task.get("last_agent_run_at") or "").strip())

    role_dev_tasks = [
        t for t in tasks if is_developer_role(member_role_by_user_id.get(str(t.get("assignee_id") or "")))
    ]
    role_qa_tasks = [
        t for t in tasks if is_qa_role(member_role_by_user_id.get(str(t.get("assignee_id") or "")))
    ]
    role_lead_tasks = [
        t for t in tasks if is_lead_role(member_role_by_user_id.get(str(t.get("assignee_id") or "")))
    ]
    dev_tasks = role_dev_tasks or [t for t in tasks if str(t.get("status") or "").strip() == "Dev"]
    qa_tasks = role_qa_tasks or [t for t in tasks if str(t.get("status") or "").strip() == "QA"]
    lead_deploy_tasks = [
        task for task in role_lead_tasks if "deploy" in str(task.get("title") or "").lower() or "docker compose" in str(task.get("title") or "").lower()
    ]
    team_mode_enabled = any(
        str(getattr(skill, "skill_key", "") or "").strip() == TEAM_MODE_SKILL_KEY for skill in project_skills
    )

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

    def _task_has_expected_branch_evidence(task: dict[str, Any]) -> bool:
        task_id = str(task.get("id") or "").strip().lower()
        if not task_id:
            return False
        task_prefix = task_id[:8]
        expected = f"task/{task_prefix}"
        corpus_parts: list[str] = [
            str(task.get("title") or ""),
            str(task.get("description") or ""),
            str(task.get("instruction") or ""),
        ]
        for ref in parse_json_list(task.get("external_refs")):
            if not isinstance(ref, dict):
                continue
            corpus_parts.append(str(ref.get("url") or ""))
            corpus_parts.append(str(ref.get("title") or ""))
        for note in notes_by_task.get(task_id, []):
            corpus_parts.append(str(note.title or ""))
            corpus_parts.append(str(note.body or ""))
            for ref in parse_json_list(note.external_refs):
                if not isinstance(ref, dict):
                    continue
                corpus_parts.append(str(ref.get("url") or ""))
                corpus_parts.append(str(ref.get("title") or ""))
        for comment in comments_by_task.get(task_id, []):
            corpus_parts.append(str(comment.body or ""))
        corpus = "\n".join(corpus_parts).lower()
        for match in branch_regex.finditer(corpus):
            candidate = f"task/{str(match.group(1) or '').strip().lower()}"
            if candidate.startswith(expected):
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
    dev_branch_missing = [
        {"task_id": str(task.get("id") or "").strip(), "title": str(task.get("title") or "").strip() or str(task.get("id") or "").strip()}
        for task in dev_tasks
        if not _task_has_expected_branch_evidence(task)
    ]
    dev_task_branch_evidence_ok = bool(dev_tasks) and not dev_branch_missing
    dev_automation_run_evidence_ok = bool(dev_tasks) and all(_task_has_automation_run(task) for task in dev_tasks)
    qa_automation_run_evidence_ok = bool(qa_tasks) and all(_task_has_automation_run(task) for task in qa_tasks)
    lead_automation_run_evidence_ok = bool(role_lead_tasks) and all(_task_has_automation_run(task) for task in role_lead_tasks)
    qa_artifacts_ok = bool(qa_tasks) and not qa_missing
    deploy_evidence_required = bool(team_mode_enabled and lead_deploy_tasks)
    deploy_execution_evidence_ok = (not deploy_evidence_required) or (not deploy_missing)
    facts = {
        "repo_context_present": repo_context_present,
        "dev_commit_evidence_ok": dev_commit_evidence_ok,
        "dev_task_branch_evidence_ok": dev_task_branch_evidence_ok,
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
            "dev_tasks_have_task_branch_evidence",
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
            "dev_missing_task_branch_evidence": len(dev_branch_missing),
            "dev_duplicated_commit_evidence": len(duplicated_commits),
            "qa_missing_artifacts": len(qa_missing),
            "deploy_missing_artifacts": len(deploy_missing),
        },
        "missing": {
            "dev_tasks_missing_commit_evidence": dev_missing,
            "dev_tasks_missing_task_branch_evidence": dev_branch_missing,
            "dev_duplicated_commit_shas": duplicated_commits,
            "qa_tasks_missing_artifacts": qa_missing,
            "lead_deploy_tasks_missing_artifacts": deploy_missing,
        },
        "ok": bool(checks_ok),
    }
