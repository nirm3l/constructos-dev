from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .audit import audit_architecture_inventory
from .build import build_architecture_inventory


def build_architecture_export(inventory: dict[str, Any] | None = None) -> dict[str, Any]:
    source = dict(inventory or build_architecture_inventory())
    capabilities = dict(source.get("capabilities") or {})
    counts = dict(source.get("counts") or {})
    workflow_plugins = list(capabilities.get("workflow_plugins") or [])
    plugin_descriptors = list(capabilities.get("plugin_descriptors") or [])
    execution_providers = list(capabilities.get("execution_providers") or [])
    audit = audit_architecture_inventory(source)

    return {
        "export_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "inventory_generated_at": str(source.get("generated_at") or "").strip() or None,
        "counts": {
            "execution_providers": int(counts.get("execution_providers") or 0),
            "workflow_plugins": int(counts.get("workflow_plugins") or 0),
            "plugin_descriptors": int(counts.get("plugin_descriptors") or 0),
            "constructos_mcp_tools": int(counts.get("constructos_mcp_tools") or 0),
            "prompt_templates": int(counts.get("prompt_templates") or 0),
            "bootstrap_startup_phases": int(counts.get("bootstrap_startup_phases") or 0),
            "bootstrap_shutdown_phases": int(counts.get("bootstrap_shutdown_phases") or 0),
            "internal_docs": int(counts.get("internal_docs") or 0),
            "internal_docs_reading_order": int(counts.get("internal_docs_reading_order") or 0),
        },
        "execution_providers": [
            {
                "provider": str(item.get("provider") or "").strip(),
                "is_default": bool(item.get("is_default")),
                "default_model": str(item.get("default_model") or "").strip() or None,
                "default_reasoning_effort": str(item.get("default_reasoning_effort") or "").strip() or None,
            }
            for item in execution_providers
            if str(item.get("provider") or "").strip()
        ],
        "workflow_plugins": [
            {
                "key": str(item.get("key") or "").strip(),
                "check_scope": str(item.get("check_scope") or "").strip() or None,
                "default_required_check_count": int(item.get("default_required_check_count") or 0),
                "available_check_count": len(dict(item.get("available_checks") or {})),
            }
            for item in workflow_plugins
            if str(item.get("key") or "").strip()
        ],
        "plugin_descriptors": [
            {
                "key": str(item.get("key") or "").strip(),
                "name": str(item.get("name") or "").strip(),
                "category": str(item.get("category") or "").strip(),
                "configurable": bool(item.get("configurable")),
                "runtime_enabled": bool(item.get("runtime_enabled")),
                "has_workflow_plugin_class": bool(item.get("has_workflow_plugin_class")),
                "config_surface": str(item.get("config_surface") or "").strip() or None,
            }
            for item in plugin_descriptors
            if str(item.get("key") or "").strip()
        ],
        "audit": audit.as_dict(),
    }

