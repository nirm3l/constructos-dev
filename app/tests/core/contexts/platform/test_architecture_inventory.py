from __future__ import annotations

from pathlib import Path

from tests.core.support.runtime import build_client as build_runtime_client


def test_architecture_inventory_endpoint_exposes_generated_inventory(tmp_path: Path):
    client = build_runtime_client(tmp_path)

    response = client.get("/api/debug/architecture-inventory")
    assert response.status_code == 200

    payload = response.json()
    counts = dict(payload.get("counts") or {})
    assert counts.get("execution_providers", 0) >= 3
    assert counts.get("workflow_plugins", 0) >= 4
    assert counts.get("plugin_descriptors", 0) >= 5
    assert counts.get("constructos_mcp_tools", 0) > 0

    internal_docs = dict(payload.get("internal_docs") or {})
    reading_order = list(internal_docs.get("reading_order") or [])
    assert "11-claw-code-parity-analysis.md" in reading_order

    export_response = client.get("/api/debug/architecture-export")
    assert export_response.status_code == 200
    export_payload = export_response.json()
    assert export_payload.get("export_version") == 1
    assert isinstance(export_payload.get("generated_at"), str)
    assert isinstance(export_payload.get("inventory_generated_at"), (str, type(None)))
    export_counts = dict(export_payload.get("counts") or {})
    assert export_counts.get("plugin_descriptors", 0) >= 5
    assert isinstance(export_payload.get("plugin_descriptors"), list)
    assert isinstance(export_payload.get("audit"), dict)

    descriptors = client.get("/api/debug/plugin-descriptors")
    assert descriptors.status_code == 200
    descriptors_payload = descriptors.json()
    assert isinstance(descriptors_payload.get("generated_at"), str)
    assert isinstance(descriptors_payload.get("count"), int)
    assert isinstance(descriptors_payload.get("items"), list)
    descriptor_keys = {
        str(item.get("key") or "").strip()
        for item in descriptors_payload.get("items") or []
    }
    assert {"team_mode", "git_delivery", "docker_compose", "github_delivery", "doctor"}.issubset(descriptor_keys)
    descriptor_items = [item for item in (descriptors_payload.get("items") or []) if isinstance(item, dict)]
    assert all(isinstance(item.get("name"), str) and str(item.get("name") or "").strip() for item in descriptor_items)
    assert all(isinstance(item.get("description"), str) and str(item.get("description") or "").strip() for item in descriptor_items)
    assert all(isinstance(item.get("available_check_ids"), list) for item in descriptor_items)
    assert all(isinstance(item.get("skill_dependencies"), dict) for item in descriptor_items)
    configurable_without_surface = [
      str(item.get("key") or "").strip()
      for item in descriptor_items
      if bool(item.get("configurable")) and not str(item.get("config_surface") or "").strip()
    ]
    assert configurable_without_surface == []

    export_descriptor_items = [
        item
        for item in (export_payload.get("plugin_descriptors") or [])
        if isinstance(item, dict)
    ]
    export_descriptor_keys = {
        str(item.get("key") or "").strip()
        for item in export_descriptor_items
        if str(item.get("key") or "").strip()
    }
    assert export_descriptor_keys == descriptor_keys


def test_architecture_inventory_audit_passes():
    from features.architecture_inventory import (
        audit_architecture_inventory,
        build_architecture_export,
        build_architecture_inventory,
    )

    inventory = build_architecture_inventory()
    audit_result = audit_architecture_inventory(inventory)
    export_payload = build_architecture_export(inventory)

    assert audit_result.ok is True
    assert export_payload.get("export_version") == 1
    assert isinstance(export_payload.get("plugin_descriptors"), list)


def test_architecture_inventory_audit_allows_missing_internal_docs_index():
    from features.architecture_inventory import (
        audit_architecture_inventory,
        build_architecture_inventory,
    )

    inventory = build_architecture_inventory()
    inventory["internal_docs"] = {
        "available": False,
        "reason": "internal_docs_index_missing",
        "root": "/docs/internal",
        "index_path": "/docs/internal/00-index.md",
        "reading_order": [],
        "referenced_docs": [],
        "existing_docs": [],
        "missing_from_reading_order": [],
        "unreferenced_docs": [],
    }

    audit_result = audit_architecture_inventory(inventory)
    assert audit_result.ok is True
    assert audit_result.warnings == []
