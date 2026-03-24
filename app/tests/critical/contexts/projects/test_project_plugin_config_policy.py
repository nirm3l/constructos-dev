from __future__ import annotations

import json

from features.agents.service import _compile_plugin_policy, _validate_team_mode_config


def test_validate_team_mode_config_accepts_valid_payload() -> None:
    config = {
        "required_checks": {
            "team_mode": [
                "role_coverage_present",
                "single_lead_present",
                "human_owner_present",
                "status_semantics_present",
            ]
        },
        "team": {
            "agents": [
                {"id": "dev-a", "name": "Developer A", "authority_role": "Developer"},
                {"id": "dev-b", "name": "Developer B", "authority_role": "Developer"},
                {"id": "qa-a", "name": "QA A", "authority_role": "QA"},
                {"id": "lead-a", "name": "Lead A", "authority_role": "Lead"},
            ]
        },
        "status_semantics": {
            "todo": "To Do",
            "active": "In Progress",
            "in_review": "In Review",
            "blocked": "Blocked",
            "awaiting_decision": "Awaiting Decision",
            "completed": "Completed",
        },
        "routing": {
            "developer_assignment": "least_active_then_stable_order",
            "qa_assignment": "least_active_then_stable_order",
        },
        "oversight": {
            "reconciliation_interval_seconds": 5,
            "human_owner_user_id": "11111111-1111-1111-1111-111111111111",
        },
        "review_policy": {
            "require_code_review": True,
            "reviewer_user_id": "22222222-2222-2222-2222-222222222222",
        },
        "labels": {
            "merged": "merged",
            "deploy_ready": "deploy-ready",
            "deployed": "deployed",
            "tested": "tested",
        },
    }

    errors, warnings = _validate_team_mode_config(config)

    assert errors == []
    assert isinstance(warnings, list)


def test_validate_team_mode_config_rejects_missing_human_owner() -> None:
    config = {
        "team": {"agents": [{"id": "lead-a", "name": "Lead A", "authority_role": "Lead"}]},
        "status_semantics": {
            "todo": "To Do",
            "active": "In Progress",
            "in_review": "In Review",
            "blocked": "Blocked",
            "awaiting_decision": "Awaiting Decision",
            "completed": "Completed",
        },
        "routing": {
            "developer_assignment": "least_active_then_stable_order",
            "qa_assignment": "least_active_then_stable_order",
        },
        "oversight": {"reconciliation_interval_seconds": 5, "human_owner_user_id": ""},
        "labels": {
            "merged": "merged",
            "deploy_ready": "deploy-ready",
            "deployed": "deployed",
            "tested": "tested",
        },
    }

    errors, _warnings = _validate_team_mode_config(config)

    assert any(err.get("path") == "oversight.human_owner_user_id" and err.get("code") == "required" for err in errors)


def test_compile_plugin_policy_uses_team_mode_contract() -> None:
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
            "status_semantics": {
                "todo": "To Do",
                "active": "In Progress",
                "in_review": "In Review",
                "blocked": "Blocked",
                "awaiting_decision": "Awaiting Decision",
                "completed": "Completed",
            },
            "routing": {
                "developer_assignment": "least_active_then_stable_order",
                "qa_assignment": "least_active_then_stable_order",
            },
            "oversight": {
                "reconciliation_interval_seconds": 11,
                "human_owner_user_id": "11111111-1111-1111-1111-111111111111",
            },
            "review_policy": {
                "require_code_review": True,
                "reviewer_user_id": "22222222-2222-2222-2222-222222222222",
            },
            "labels": {
                "merged": "merged",
                "deploy_ready": "deploy-ready",
                "deployed": "deployed",
                "tested": "tested",
            },
        },
    )

    assert policy["version"] == 2
    assert policy["oversight"]["reconciliation_interval_seconds"] == 11
    assert policy["review_policy"]["require_code_review"] is True
    assert policy["review_policy"]["reviewer_user_id"] == "22222222-2222-2222-2222-222222222222"
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
            "status_semantics": {
                "todo": "To Do",
                "active": "In Progress",
                "in_review": "In Review",
                "blocked": "Blocked",
                "awaiting_decision": "Awaiting Decision",
                "completed": "Completed",
            },
            "routing": {
                "developer_assignment": "least_active_then_stable_order",
                "qa_assignment": "least_active_then_stable_order",
            },
            "oversight": {
                "reconciliation_interval_seconds": 7,
                "human_owner_user_id": "11111111-1111-1111-1111-111111111111",
            },
            "labels": {
                "merged": "merged",
                "deploy_ready": "deploy-ready",
                "deployed": "deployed",
                "tested": "tested",
            },
            "required_checks": {
                "team_mode": [
                    "role_coverage_present",
                    "single_lead_present",
                    "human_owner_present",
                    "status_semantics_present",
                ]
            },
        },
    )
    snapshot = {
        "version": policy.get("version"),
        "required_checks": policy.get("required_checks"),
        "available_checks_keys": sorted(list(((policy.get("available_checks") or {}).get("team_mode") or {}).keys())),
        "oversight": policy.get("oversight"),
        "status_semantics": policy.get("status_semantics"),
        "authority_role_counts": ((policy.get("team") or {}).get("authority_role_counts") or {}),
    }
    expected = {
        "version": 2,
        "required_checks": {
            "team_mode": [
                "role_coverage_present",
                "single_lead_present",
                "human_owner_present",
                "status_semantics_present",
            ]
        },
        "available_checks_keys": [
            "human_owner_present",
            "role_coverage_present",
            "single_lead_present",
            "status_semantics_present",
        ],
        "oversight": {
            "reconciliation_interval_seconds": 7,
            "human_owner_user_id": "11111111-1111-1111-1111-111111111111",
        },
        "status_semantics": {
            "todo": "To Do",
            "active": "In Progress",
            "in_review": "In Review",
            "blocked": "Blocked",
            "awaiting_decision": "Awaiting Decision",
            "completed": "Completed",
        },
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
            "compose_manifest_present",
            "deploy_execution_evidence_present",
            "deploy_serves_application_root",
            "git_contract_ok",
            "lead_deploy_decision_evidence_present",
            "qa_handoff_current_cycle_ok",
            "qa_has_verifiable_artifacts",
            "repo_context_present",
            "runtime_deploy_health_ok",
        ],
    }
    assert json.dumps(snapshot, sort_keys=True) == json.dumps(expected, sort_keys=True)
