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
    assert counts.get("constructos_mcp_tools", 0) > 0

    internal_docs = dict(payload.get("internal_docs") or {})
    reading_order = list(internal_docs.get("reading_order") or [])
    assert "11-claw-code-parity-analysis.md" in reading_order


def test_architecture_inventory_audit_passes():
    from features.architecture_inventory import audit_architecture_inventory, build_architecture_inventory

    inventory = build_architecture_inventory()
    audit_result = audit_architecture_inventory(inventory)

    assert audit_result.ok is True
