from __future__ import annotations


def test_capability_registry_builds_expected_sections():
    from features.agents.capability_registry import build_capability_registry

    registry = build_capability_registry()

    counts = dict(registry.get("counts") or {})
    assert counts.get("execution_providers", 0) >= 3
    assert counts.get("workflow_plugins", 0) >= 4
    assert counts.get("plugin_descriptors", 0) >= 5
    assert counts.get("constructos_mcp_tools", 0) > 0
    assert counts.get("prompt_templates", 0) > 0
    assert counts.get("bootstrap_startup_phases", 0) > 0
    assert counts.get("bootstrap_shutdown_phases", 0) > 0

    provider_names = {
        str(item.get("provider") or "").strip()
        for item in (registry.get("execution_providers") or [])
    }
    assert {"codex", "claude", "opencode"}.issubset(provider_names)

    plugin_keys = {
        str(item.get("key") or "").strip()
        for item in (registry.get("workflow_plugins") or [])
    }
    assert {"team_mode", "git_delivery", "github_delivery", "doctor"}.issubset(plugin_keys)
    descriptor_keys = {
        str(item.get("key") or "").strip()
        for item in (registry.get("plugin_descriptors") or [])
    }
    assert {"team_mode", "git_delivery", "docker_compose", "github_delivery", "doctor"}.issubset(descriptor_keys)

    tool_by_name = {
        str(item.get("name") or "").strip(): item
        for item in (registry.get("constructos_mcp_tools") or [])
    }
    assert "list_tasks" in tool_by_name
    assert "setup_project_orchestration" in tool_by_name
    assert sorted(tool_by_name["setup_project_orchestration"]["plugin_gates"]) == [
        "docker_compose",
        "git_delivery",
        "team_mode",
    ]

    prompt_paths = {
        str(item.get("path") or "").strip()
        for item in (registry.get("prompt_templates") or [])
    }
    assert "app/shared/prompt_templates/codex/full_prompt.md" in prompt_paths
    assert "app/plugins/team_mode/prompt_templates/team_mode_kickoff_instruction.md" in prompt_paths

    startup_phase_names = [
        str(item.get("name") or "").strip()
        for item in ((registry.get("bootstrap") or {}).get("startup") or [])
    ]
    shutdown_phase_names = [
        str(item.get("name") or "").strip()
        for item in ((registry.get("bootstrap") or {}).get("shutdown") or [])
    ]
    assert "startup_bootstrap" in startup_phase_names
    assert "start_projection_worker" in startup_phase_names
    assert "stop_projection_worker" in shutdown_phase_names
    assert "close_knowledge_graph_driver" in shutdown_phase_names
