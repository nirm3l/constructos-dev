from __future__ import annotations


def test_workspace_provider_resolution_returns_last_remembered_provider():
    import features.agents.command_runtime_registry as registry

    registry._PROVIDER_BY_COMMAND_ID.clear()
    registry._PROVIDER_BY_WORKSPACE_ID.clear()

    registry.remember_provider_for_workspace_id(workspace_id="ws-1", provider="claude")

    assert registry.resolve_provider_for_workspace_id("ws-1") == "claude"


def test_command_provider_resolution_takes_precedence_over_workspace_provider():
    import features.agents.command_runtime_registry as registry

    registry._PROVIDER_BY_COMMAND_ID.clear()
    registry._PROVIDER_BY_WORKSPACE_ID.clear()

    registry.remember_provider_for_workspace_id(workspace_id="ws-1", provider="claude")
    registry.remember_provider_for_command_id(command_id="cmd-1", provider="codex")

    assert registry.resolve_provider_for_command_id("cmd-1") == "codex"
    assert registry.resolve_provider_for_workspace_id("ws-1") == "claude"

