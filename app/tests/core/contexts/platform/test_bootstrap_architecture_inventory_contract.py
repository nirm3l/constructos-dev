from __future__ import annotations

from pathlib import Path

from tests.core.support.runtime import build_client as build_runtime_client


def _build_client(tmp_path: Path):
    return build_runtime_client(
        tmp_path,
        extra_env={
            "AGENT_CODEX_WORKDIR": str(tmp_path / "workspace"),
            "AGENT_RUNNER_ENABLED": "false",
        },
    )


def test_bootstrap_architecture_inventory_summary_contract_shape(tmp_path: Path):
    client = _build_client(tmp_path)

    response = client.get("/api/bootstrap")
    assert response.status_code == 200
    payload = response.json()

    summary = payload.get("architecture_inventory_summary")
    assert isinstance(summary, dict)

    assert isinstance(summary.get("generated_at"), str)
    assert isinstance(summary.get("counts"), dict)
    assert isinstance(summary.get("cache_ttl_seconds"), float)
    assert isinstance(summary.get("cache_hit"), bool)
    assert isinstance(summary.get("cache_status"), dict)

    counts = summary.get("counts") or {}
    for key in (
        "execution_providers",
        "workflow_plugins",
        "plugin_descriptors",
        "constructos_mcp_tools",
        "prompt_templates",
        "bootstrap_startup_phases",
        "bootstrap_shutdown_phases",
        "internal_docs",
        "internal_docs_reading_order",
    ):
        assert isinstance(counts.get(key), int)
        assert int(counts.get(key) or 0) >= 0

    internal_docs = summary.get("internal_docs") or {}
    assert isinstance(internal_docs, dict)
    assert isinstance(internal_docs.get("existing_docs_count"), int)
    assert isinstance(internal_docs.get("reading_order_count"), int)
    assert isinstance(internal_docs.get("missing_from_reading_order_count"), int)
    assert isinstance(internal_docs.get("unreferenced_docs_count"), int)
    assert isinstance(internal_docs.get("missing_from_reading_order"), list)
    assert isinstance(internal_docs.get("unreferenced_docs"), list)

    audit = summary.get("audit") or {}
    assert isinstance(audit, dict)
    assert isinstance(audit.get("ok"), bool)
    assert isinstance(audit.get("error_count"), int)
    assert isinstance(audit.get("warning_count"), int)
    assert isinstance(audit.get("errors"), list)
    assert isinstance(audit.get("warnings"), list)

    cache_status = summary.get("cache_status") or {}
    assert isinstance(cache_status.get("key"), str)
    assert isinstance(cache_status.get("has_payload"), bool)
    assert isinstance(cache_status.get("hit_count"), int)
    assert isinstance(cache_status.get("miss_count"), int)
    assert isinstance(cache_status.get("expires_in_seconds"), float)

    # Backward-compatible mirror for legacy bootstrap consumers.
    config_summary = ((payload.get("config") or {}).get("architecture_inventory_summary") or {})
    assert config_summary == summary


def test_bootstrap_plan_contract_shape(tmp_path: Path):
    client = _build_client(tmp_path)

    response = client.get("/api/bootstrap")
    assert response.status_code == 200
    payload = response.json()

    plan = payload.get("bootstrap_plan")
    assert isinstance(plan, dict)
    assert isinstance(plan.get("generated_at"), str)
    assert isinstance(plan.get("startup_phase_count"), int)
    assert isinstance(plan.get("shutdown_phase_count"), int)

    phases = plan.get("phases") or {}
    assert isinstance(phases, dict)
    assert isinstance(phases.get("startup"), list)
    assert isinstance(phases.get("shutdown"), list)
    for phase_type in ("startup", "shutdown"):
        for item in phases.get(phase_type) or []:
            assert isinstance(item.get("id"), str)
            assert isinstance(item.get("name"), str)
            assert isinstance(item.get("phase_type"), str)
            assert isinstance(item.get("order"), int)
            assert isinstance(item.get("status"), str)

    runtime_health = plan.get("runtime_health") or {}
    assert isinstance(runtime_health, dict)
    for key in ("bootstrap_discovery_cache", "architecture_inventory_cache"):
        section = runtime_health.get(key) or {}
        assert isinstance(section, dict)
        assert isinstance(section.get("has_payload"), bool)
        assert isinstance(section.get("expires_in_seconds"), float)
        assert isinstance(section.get("hit_count"), int)
        assert isinstance(section.get("miss_count"), int)

    # Backward-compatible mirror for legacy bootstrap consumers.
    config_plan = ((payload.get("config") or {}).get("bootstrap_plan") or {})
    assert config_plan == plan


def test_bootstrap_architecture_export_summary_contract_shape(tmp_path: Path):
    client = _build_client(tmp_path)

    response = client.get("/api/bootstrap")
    assert response.status_code == 200
    payload = response.json()

    summary = payload.get("architecture_export_summary")
    assert isinstance(summary, dict)
    assert isinstance(summary.get("generated_at"), str)
    assert isinstance(summary.get("inventory_generated_at"), str)
    assert isinstance(summary.get("counts"), dict)
    assert isinstance(summary.get("plugin_descriptor_keys"), list)
    assert isinstance(summary.get("cache_ttl_seconds"), float)
    assert isinstance(summary.get("cache_hit"), bool)
    assert isinstance(summary.get("cache_status"), dict)

    counts = summary.get("counts") or {}
    for key in (
        "execution_providers",
        "workflow_plugins",
        "plugin_descriptors",
        "constructos_mcp_tools",
        "prompt_templates",
        "bootstrap_startup_phases",
        "bootstrap_shutdown_phases",
        "internal_docs",
        "internal_docs_reading_order",
    ):
        assert isinstance(counts.get(key), int)
        assert int(counts.get(key) or 0) >= 0

    descriptor_keys = [str(item or "").strip() for item in (summary.get("plugin_descriptor_keys") or [])]
    assert descriptor_keys
    assert all(descriptor_keys)

    audit = summary.get("audit") or {}
    assert isinstance(audit, dict)
    assert isinstance(audit.get("ok"), bool)
    assert isinstance(audit.get("error_count"), int)
    assert isinstance(audit.get("warning_count"), int)
    assert isinstance(audit.get("errors"), list)
    assert isinstance(audit.get("warnings"), list)

    cache_status = summary.get("cache_status") or {}
    assert isinstance(cache_status.get("key"), str)
    assert isinstance(cache_status.get("has_payload"), bool)
    assert isinstance(cache_status.get("hit_count"), int)
    assert isinstance(cache_status.get("miss_count"), int)
    assert isinstance(cache_status.get("expires_in_seconds"), float)

    config_summary = ((payload.get("config") or {}).get("architecture_export_summary") or {})
    assert config_summary == summary
