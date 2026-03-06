from __future__ import annotations

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
