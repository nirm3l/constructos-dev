from __future__ import annotations

import plugins.registry as plugin_registry
from plugins import executor_policy as plugin_executor_policy
from plugins import skill_policy as plugin_skill_policy
from plugins import task_policy as plugin_task_policy
from plugins.registry import list_workflow_plugins
from features.agents import gates as gates_module
from plugins.team_mode.plugin import TeamModePlugin


def _clear_plugin_registry_cache() -> None:
    plugin_registry.list_workflow_plugins.cache_clear()


def test_workflow_plugin_registry_includes_team_mode() -> None:
    _clear_plugin_registry_cache()
    plugins = list_workflow_plugins()
    keys = {str(getattr(plugin, "key", "")).strip() for plugin in plugins}
    assert "team_mode" in keys
    _clear_plugin_registry_cache()


def test_default_plugin_policy_and_catalog_include_team_mode_plugin_scope() -> None:
    _clear_plugin_registry_cache()
    assert "team_mode" in gates_module.DEFAULT_PLUGIN_POLICY.get("required_checks", {})
    assert "team_mode" in gates_module.DEFAULT_PLUGIN_POLICY.get("available_checks", {})

    catalog = gates_module.plugin_check_catalog_by_scope()
    assert "team_mode" in catalog
    assert any(item["id"] == "single_lead_present" for item in catalog["team_mode"])
    _clear_plugin_registry_cache()


def test_workflow_plugin_registry_respects_enabled_plugins_env_list(monkeypatch) -> None:
    monkeypatch.setattr(plugin_registry, "AGENT_ENABLED_PLUGINS", ["team_mode"])
    _clear_plugin_registry_cache()
    plugins = plugin_registry.list_workflow_plugins()
    keys = {str(getattr(plugin, "key", "")).strip() for plugin in plugins}
    assert keys == {"team_mode"}
    _clear_plugin_registry_cache()


def test_workflow_plugin_registry_can_disable_all_plugins(monkeypatch) -> None:
    monkeypatch.setattr(plugin_registry, "AGENT_ENABLED_PLUGINS", ["none"])
    _clear_plugin_registry_cache()
    plugins = plugin_registry.list_workflow_plugins()
    assert plugins == []
    _clear_plugin_registry_cache()


def test_executor_policy_dispatches_team_mode_worktree_rules() -> None:
    _clear_plugin_registry_cache()
    assert (
        plugin_executor_policy.is_task_scoped_context_enabled(
            project_plugin_enabled=True,
            assignee_project_role="DeveloperAgent",
        )
        is True
    )
    assert (
        plugin_executor_policy.should_prepare_task_worktree(
            plugin_enabled=True,
            git_delivery_enabled=True,
            task_status="In Progress",
            actor_project_role="DeveloperAgent",
            assignee_project_role="DeveloperAgent",
        )
        is True
    )
    assert (
        plugin_executor_policy.should_prepare_task_worktree(
            plugin_enabled=True,
            git_delivery_enabled=True,
            task_status="In Review",
            actor_project_role="DeveloperAgent",
            assignee_project_role="DeveloperAgent",
        )
        is False
    )
    _clear_plugin_registry_cache()


def test_task_policy_dispatches_team_mode_cleanup_rules() -> None:
    _clear_plugin_registry_cache()
    assert (
        plugin_task_policy.should_cleanup_task_worktree(
            plugin_enabled=True,
            task_status="Completed",
            assignee_role="DeveloperAgent",
        )
        is True
    )
    assert (
        plugin_task_policy.should_cleanup_task_worktree(
            plugin_enabled=True,
            task_status="In Progress",
            assignee_role="DeveloperAgent",
        )
        is False
    )
    assert (
        plugin_task_policy.should_cleanup_task_worktree(
            plugin_enabled=True,
            task_status="QA",
            assignee_role="QAAgent",
        )
        is False
    )
    _clear_plugin_registry_cache()


def test_skill_policy_dispatches_no_team_mode_or_git_delivery_dependency() -> None:
    _clear_plugin_registry_cache()
    deps = plugin_skill_policy.skill_dependencies()
    assert deps.get("team_mode") is None
    patch = plugin_skill_policy.build_plugin_policy_patch_for_skill_keys({"team_mode"})
    assert patch == {}
    _clear_plugin_registry_cache()


def test_team_mode_plugin_does_not_use_instruction_text_for_kickoff_detection() -> None:
    plugin = TeamModePlugin()

    assert (
        plugin.runner_normalize_success_outcome(
            action="complete",
            summary="Completed",
            comment=None,
            instruction="Kickoff execution for project in lead-first mode",
            assignee_role="Lead",
            task_state={
                "last_requested_execution_kickoff_intent": True,
                "last_requested_workflow_scope": "team_mode",
                "last_requested_execution_mode": "kickoff_only",
            },
        )["action"]
        == "comment"
    )
    assert (
        plugin.runner_normalize_success_outcome(
            action="complete",
            summary="Completed",
            comment=None,
            instruction="Kickoff execution for project in lead-first mode",
            assignee_role="Lead",
            task_state={
                "last_requested_execution_kickoff_intent": False,
                "last_requested_workflow_scope": "unknown",
                "last_requested_execution_mode": "unknown",
            },
        )["action"]
        == "complete"
    )
    assert plugin.runner_is_kickoff_instruction(instruction="Kickoff execution for project in lead-first mode") is False
