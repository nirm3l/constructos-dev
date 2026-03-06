from __future__ import annotations

from typing import Any

from plugins.registry import list_workflow_plugins


def _merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_dict(dict(out.get(key) or {}), value)
        else:
            out[key] = value
    return out


def skill_dependencies() -> dict[str, tuple[str, ...]]:
    merged: dict[str, tuple[str, ...]] = {}
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "skill_dependencies", None)
        if not callable(fn):
            continue
        raw = fn()
        if not isinstance(raw, dict):
            continue
        for key, deps in raw.items():
            normalized_key = str(key or "").strip().lower()
            if not normalized_key:
                continue
            if isinstance(deps, (list, tuple, set)):
                dep_items = tuple(
                    str(item or "").strip().lower()
                    for item in deps
                    if str(item or "").strip()
                )
            else:
                dep_items = tuple()
            if dep_items:
                merged[normalized_key] = dep_items
    return merged


def build_plugin_policy_patch_for_skill_keys(skill_keys: set[str]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    normalized_keys = {str(item or "").strip().lower() for item in (skill_keys or set()) if str(item or "").strip()}
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "plugin_policy_patch_for_skill_keys", None)
        if not callable(fn):
            continue
        raw_patch = fn(skill_keys=normalized_keys)
        if not isinstance(raw_patch, dict):
            continue
        patch = _merge_dict(patch, raw_patch)
    return patch
