from __future__ import annotations

from functools import lru_cache

from .base import WorkflowPlugin
from .doctor.plugin import DoctorPlugin
from .git_delivery.plugin import GitDeliveryPlugin
from .github_delivery.plugin import GithubDeliveryPlugin
from .team_mode.plugin import TeamModePlugin
from shared.settings import AGENT_ENABLED_PLUGINS


@lru_cache(maxsize=1)
def list_workflow_plugins() -> list[WorkflowPlugin]:
    all_plugins: list[WorkflowPlugin] = [TeamModePlugin(), GitDeliveryPlugin(), GithubDeliveryPlugin(), DoctorPlugin()]
    plugin_by_key_map = {
        str(getattr(plugin, "key", "")).strip().lower(): plugin
        for plugin in all_plugins
        if str(getattr(plugin, "key", "")).strip()
    }
    enabled = {str(item or "").strip().lower() for item in AGENT_ENABLED_PLUGINS if str(item or "").strip()}
    if not enabled:
        return all_plugins
    if enabled.intersection({"none", "off", "disabled"}):
        return []
    resolved = set(enabled)
    # Expand plugin set using declared skill/plugin dependencies so selecting
    # `team_mode` auto-enables `git_delivery` plugin behavior.
    changed = True
    while changed:
        changed = False
        for key in list(resolved):
            plugin = plugin_by_key_map.get(key)
            if plugin is None:
                continue
            deps_fn = getattr(plugin, "skill_dependencies", None)
            if not callable(deps_fn):
                continue
            deps_map = deps_fn()
            if not isinstance(deps_map, dict):
                continue
            raw_deps = deps_map.get(key, ())
            if not isinstance(raw_deps, (list, tuple, set)):
                continue
            for dep in raw_deps:
                normalized_dep = str(dep or "").strip().lower()
                if not normalized_dep or normalized_dep in resolved:
                    continue
                if normalized_dep not in plugin_by_key_map:
                    continue
                resolved.add(normalized_dep)
                changed = True
    return [plugin for plugin in all_plugins if str(getattr(plugin, "key", "")).strip().lower() in resolved]


@lru_cache(maxsize=8)
def plugin_by_key(key: str) -> WorkflowPlugin | None:
    normalized = str(key or "").strip().lower()
    if not normalized:
        return None
    for plugin in list_workflow_plugins():
        if str(getattr(plugin, "key", "")).strip().lower() == normalized:
            return plugin
    return None
