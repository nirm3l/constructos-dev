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
