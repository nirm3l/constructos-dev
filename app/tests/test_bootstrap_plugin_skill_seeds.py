from __future__ import annotations

import plugins.registry as plugin_registry
from shared import bootstrap as bootstrap_module


def _clear_bootstrap_skill_cache() -> None:
    bootstrap_module._DEFAULT_WORKSPACE_SKILLS_CACHE = None
    plugin_registry.list_workflow_plugins.cache_clear()


def test_workspace_skill_seeds_include_team_mode_when_plugin_enabled(monkeypatch) -> None:
    monkeypatch.setattr(plugin_registry, "AGENT_ENABLED_PLUGINS", ["team_mode"])
    _clear_bootstrap_skill_cache()
    loaded = bootstrap_module._load_default_workspace_skills()
    keys = {str(item.get("skill_key") or "").strip() for item in loaded}
    assert "team_mode" in keys
    assert "git_delivery" in keys
    _clear_bootstrap_skill_cache()


def test_workspace_skill_seeds_exclude_team_mode_when_plugins_disabled(monkeypatch) -> None:
    monkeypatch.setattr(plugin_registry, "AGENT_ENABLED_PLUGINS", ["none"])
    _clear_bootstrap_skill_cache()
    loaded = bootstrap_module._load_default_workspace_skills()
    keys = {str(item.get("skill_key") or "").strip() for item in loaded}
    assert "team_mode" not in keys
    assert "git_delivery" not in keys
    assert "github_delivery" not in keys
    _clear_bootstrap_skill_cache()
