from __future__ import annotations

from typing import Any

from plugins.registry import list_workflow_plugins

from .doctor.plugin import DoctorPlugin
from .git_delivery.plugin import GitDeliveryPlugin
from .github_delivery.plugin import GithubDeliveryPlugin
from .team_mode.plugin import TeamModePlugin


def _all_workflow_plugins() -> list[Any]:
    return [TeamModePlugin(), GitDeliveryPlugin(), GithubDeliveryPlugin(), DoctorPlugin()]


def _normalize_skill_dependencies(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for dep_key_raw, dep_values in raw.items():
        dep_key = str(dep_key_raw or "").strip().lower()
        if not dep_key or not isinstance(dep_values, (list, tuple, set)):
            continue
        out[dep_key] = [
            str(item or "").strip().lower()
            for item in dep_values
            if str(item or "").strip()
        ]
    return out


_PLUGIN_DESCRIPTOR_SEEDS: dict[str, dict[str, Any]] = {
    "team_mode": {
        "name": "Team Mode",
        "description": "Workflow orchestration policy for Developer/QA/Lead automation lifecycle.",
        "category": "workflow",
        "configurable": True,
        "config_surface": "project_plugin_config",
    },
    "git_delivery": {
        "name": "Git Delivery",
        "description": "Delivery evidence policy for task branches, commit references, and completion gating.",
        "category": "delivery",
        "configurable": True,
        "config_surface": "project_plugin_config",
    },
    "docker_compose": {
        "name": "Docker Compose",
        "description": "Runtime deployment and health-contract configuration for managed compose stacks.",
        "category": "runtime",
        "configurable": True,
        "config_surface": "project_plugin_config",
    },
    "github_delivery": {
        "name": "GitHub Delivery",
        "description": "Repository context classifier and GitHub-specific delivery capability surface.",
        "category": "delivery",
        "configurable": True,
        "config_surface": "project_plugin_config",
    },
    "doctor": {
        "name": "Doctor",
        "description": "Operational diagnostics, runtime contract audits, and workspace recovery actions.",
        "category": "operations",
        "configurable": False,
        "config_surface": "workspace_doctor",
    },
}


def list_plugin_descriptors() -> list[dict[str, Any]]:
    enabled_plugin_keys = {
        str(getattr(plugin, "key", "") or "").strip().lower()
        for plugin in list_workflow_plugins()
        if str(getattr(plugin, "key", "") or "").strip()
    }
    class_backed_plugins = {
        str(getattr(plugin, "key", "") or "").strip().lower(): plugin
        for plugin in _all_workflow_plugins()
        if str(getattr(plugin, "key", "") or "").strip()
    }

    rows: list[dict[str, Any]] = []
    for key in sorted(_PLUGIN_DESCRIPTOR_SEEDS.keys()):
        seed = dict(_PLUGIN_DESCRIPTOR_SEEDS.get(key) or {})
        plugin = class_backed_plugins.get(key)
        default_required_checks = plugin.default_required_checks() if plugin is not None else []
        check_descriptions = plugin.check_descriptions() if plugin is not None else {}
        available_check_ids_fn = getattr(plugin, "available_check_ids", None) if plugin is not None else None
        skill_dependencies_fn = getattr(plugin, "skill_dependencies", None) if plugin is not None else None
        available_check_ids = (
            [str(item or "").strip() for item in available_check_ids_fn()]
            if callable(available_check_ids_fn)
            else []
        )
        skill_dependencies = skill_dependencies_fn() if callable(skill_dependencies_fn) else {}
        rows.append(
            {
                "key": key,
                "name": str(seed.get("name") or key),
                "description": str(seed.get("description") or "").strip(),
                "category": str(seed.get("category") or "workflow"),
                "configurable": bool(seed.get("configurable")),
                "config_surface": str(seed.get("config_surface") or "").strip() or None,
                "has_workflow_plugin_class": plugin is not None,
                "runtime_enabled": key in enabled_plugin_keys,
                "module": type(plugin).__module__ if plugin is not None else None,
                "class_name": type(plugin).__name__ if plugin is not None else None,
                "check_scope": plugin.check_scope() if plugin is not None else None,
                "default_required_checks": list(default_required_checks),
                "default_required_check_count": len(default_required_checks),
                "available_checks": dict(check_descriptions or {}),
                "available_check_ids": list(available_check_ids),
                "skill_dependencies": _normalize_skill_dependencies(skill_dependencies),
            }
        )
    return rows

