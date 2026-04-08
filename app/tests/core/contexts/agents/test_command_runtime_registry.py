from __future__ import annotations


def test_command_provider_resolution_returns_last_remembered_provider():
    import features.agents.command_runtime_registry as registry

    registry._PROVIDER_BY_COMMAND_ID.clear()
    registry.remember_provider_for_command_id(command_id="cmd-1", provider="claude")
    assert registry.resolve_provider_for_command_id("cmd-1") == "claude"


def test_command_provider_resolution_supports_child_command_ids():
    import features.agents.command_runtime_registry as registry

    registry._PROVIDER_BY_COMMAND_ID.clear()
    registry.remember_provider_for_command_id(command_id="cmd-1", provider="codex")

    assert registry.resolve_provider_for_command_id("cmd-1") == "codex"
    assert registry.resolve_provider_for_command_id("cmd-1:create-task") == "codex"
