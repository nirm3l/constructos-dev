from __future__ import annotations

import json

from features.agents.service import _compile_plugin_policy, _validate_team_mode_config


def test_validate_team_mode_config_accepts_valid_payload() -> None:
    config = {
        "team": {
            "agents": [
                {"id": "dev-a", "name": "Developer A", "authority_role": "Developer"},
                {"id": "dev-b", "name": "Developer B", "authority_role": "Developer"},
                {"id": "qa-a", "name": "QA A", "authority_role": "QA"},
                {"id": "lead-a", "name": "Lead A", "authority_role": "Lead"},
            ]
        },
        "workflow": {
            "statuses": ["To do", "Dev", "QA", "Lead", "Done", "Blocked"],
            "transitions": [
                {"from": "Dev", "to": "QA", "allowed_roles": ["Developer"]},
                {"from": "QA", "to": "Lead", "allowed_roles": ["QA"]},
                {"from": "Lead", "to": "Done", "allowed_roles": ["Lead"]},
            ],
        },
        "governance": {
            "merge_authority_roles": ["Lead"],
            "task_move_authority_roles": ["Lead", "Developer"],
        },
        "automation": {"lead_recurring_max_minutes": 5},
    }

    errors, warnings = _validate_team_mode_config(config)

    assert errors == []
    assert isinstance(warnings, list)


def test_validate_team_mode_config_rejects_unknown_transition_status() -> None:
    config = {
        "team": {"agents": [{"id": "lead-a", "name": "Lead A", "authority_role": "Lead"}]},
        "workflow": {
            "statuses": ["Dev", "QA", "Lead"],
            "transitions": [{"from": "Dev", "to": "Done", "allowed_roles": ["Developer"]}],
        },
        "governance": {"merge_authority_roles": ["Lead"]},
        "automation": {"lead_recurring_max_minutes": 5},
    }

    errors, _warnings = _validate_team_mode_config(config)

    assert any(err.get("path") == "workflow.transitions[0].to" and err.get("code") == "unknown_status" for err in errors)


def test_compile_plugin_policy_uses_team_mode_recurring_minutes() -> None:
    policy = _compile_plugin_policy(
        "team_mode",
        {
            "team": {"agents": []},
            "workflow": {"statuses": ["To do"], "transitions": []},
            "governance": {"merge_authority_roles": []},
            "automation": {"lead_recurring_max_minutes": 11},
        },
    )

    assert policy["team_mode"]["lead_recurring_max_minutes"] == 11
    assert "required_checks" in policy


def test_compile_plugin_policy_git_delivery_has_runtime_defaults() -> None:
    policy = _compile_plugin_policy("git_delivery", {})

    assert policy["required_checks"]["delivery"]
    assert "runtime_deploy_health" not in policy


def test_compile_plugin_policy_docker_compose_has_runtime_defaults() -> None:
    policy = _compile_plugin_policy("docker_compose", {})

    runtime = policy["runtime_deploy_health"]
    assert runtime["stack"] == "constructos-ws-default"
    assert runtime["health_path"] == "/health"


def test_compile_plugin_policy_docker_compose_snapshot_custom_runtime() -> None:
    policy = _compile_plugin_policy(
        "docker_compose",
        {
            "compose_project_name": "constructos-app",
            "workspace_root": "/workspace",
            "allowed_services": ["task-app", "mcp-tools"],
            "protected_services": ["license-control-plane", "license-control-plane-backup"],
            "runtime_deploy_health": {
                "required": True,
                "stack": "constructos-ws-default",
                "port": 6768,
                "health_path": "/healthz",
                "require_http_200": True,
            },
        },
    )
    snapshot = {
        "version": policy.get("version"),
        "docker_compose": policy.get("docker_compose"),
        "runtime_deploy_health": policy.get("runtime_deploy_health"),
    }
    expected = {
        "version": 1,
        "docker_compose": {
            "compose_project_name": "constructos-app",
            "workspace_root": "/workspace",
            "allowed_services": ["task-app", "mcp-tools"],
            "protected_services": ["license-control-plane", "license-control-plane-backup"],
        },
        "runtime_deploy_health": {
            "required": True,
            "stack": "constructos-ws-default",
            "port": 6768,
            "health_path": "/healthz",
            "require_http_200": True,
        },
    }
    assert json.dumps(snapshot, sort_keys=True) == json.dumps(expected, sort_keys=True)


def test_compile_plugin_policy_team_mode_snapshot_contract() -> None:
    policy = _compile_plugin_policy(
        "team_mode",
        {
            "team": {
                "agents": [
                    {"id": "dev-a", "name": "Developer A", "authority_role": "Developer"},
                    {"id": "qa-a", "name": "QA A", "authority_role": "QA"},
                    {"id": "lead-a", "name": "Lead A", "authority_role": "Lead"},
                ]
            },
            "workflow": {"statuses": ["To do", "Dev", "Lead", "QA", "Done", "Blocked"], "transitions": []},
            "governance": {"merge_authority_roles": ["Lead"], "task_move_authority_roles": ["Lead"]},
            "automation": {"lead_recurring_max_minutes": 7},
            "required_checks": {
                "team_mode": [
                    "role_coverage_present",
                    "required_topology_present",
                    "lead_oversight_not_done_before_delivery_complete",
                ]
            },
        },
    )
    snapshot = {
        "version": policy.get("version"),
        "required_checks": policy.get("required_checks"),
        "available_checks_keys": sorted(list(((policy.get("available_checks") or {}).get("team_mode") or {}).keys())),
        "team_mode": policy.get("team_mode"),
        "authority_role_counts": ((policy.get("team") or {}).get("authority_role_counts") or {}),
    }
    expected = {
        "version": 1,
        "required_checks": {
            "team_mode": [
                "role_coverage_present",
                "required_topology_present",
                "lead_oversight_not_done_before_delivery_complete",
            ]
        },
        "available_checks_keys": [
            "lead_oversight_not_done_before_delivery_complete",
            "required_topology_present",
            "role_coverage_present",
        ],
        "team_mode": {"lead_recurring_max_minutes": 7},
        "authority_role_counts": {"Developer": 1, "Lead": 1, "QA": 1},
    }
    assert json.dumps(snapshot, sort_keys=True) == json.dumps(expected, sort_keys=True)


def test_compile_plugin_policy_git_delivery_snapshot_contract() -> None:
    policy = _compile_plugin_policy(
        "git_delivery",
        {
            "required_checks": {
                "delivery": [
                    "git_contract_ok",
                    "qa_has_verifiable_artifacts",
                ]
            }
        },
    )
    snapshot = {
        "version": policy.get("version"),
        "required_checks": policy.get("required_checks"),
        "available_checks_keys": sorted(list(((policy.get("available_checks") or {}).get("delivery") or {}).keys())),
    }
    expected = {
        "version": 1,
        "required_checks": {
            "delivery": [
                "git_contract_ok",
                "qa_has_verifiable_artifacts",
            ]
        },
        "available_checks_keys": [
            "deploy_execution_evidence_present",
            "git_contract_ok",
            "qa_has_verifiable_artifacts",
            "repo_context_present",
            "runtime_deploy_health_ok",
        ],
    }
    assert json.dumps(snapshot, sort_keys=True) == json.dumps(expected, sort_keys=True)
