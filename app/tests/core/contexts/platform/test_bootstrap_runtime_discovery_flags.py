from pathlib import Path

from fastapi.testclient import TestClient

from tests.core.support.runtime import build_client as build_runtime_client


def build_client(tmp_path: Path) -> TestClient:
    return build_runtime_client(
        tmp_path,
        extra_env={
            "AGENT_CODEX_WORKDIR": str(tmp_path / "workspace"),
            "AGENT_RUNNER_ENABLED": "false",
        },
    )


def test_bootstrap_uses_non_runtime_discovery_paths(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)

    calls: dict[str, object] = {
        "agent_models_allow_runtime_discovery": None,
        "mcp_include_codex_cli": None,
    }

    import features.bootstrap.read_models as bootstrap_read_models

    def fake_list_available_agent_models(*, force_refresh: bool = False, allow_runtime_discovery: bool = True):
        calls["agent_models_allow_runtime_discovery"] = allow_runtime_discovery
        return ["codex:gpt-5"], "codex:gpt-5"

    def fake_list_available_mcp_servers(*, force_refresh: bool = False, include_codex_cli: bool = True):
        calls["mcp_include_codex_cli"] = include_codex_cli
        return [{"name": "constructos-tools", "display_name": "Constructos Tools", "enabled": True}]

    monkeypatch.setattr(bootstrap_read_models, "list_available_agent_models", fake_list_available_agent_models)
    monkeypatch.setattr(bootstrap_read_models, "list_available_mcp_servers", fake_list_available_mcp_servers)
    bootstrap_read_models._clear_bootstrap_discovery_cache_for_tests()

    response = client.get("/api/bootstrap")
    assert response.status_code == 200

    payload = response.json()
    assert isinstance(payload.get("agent_chat_available_models"), list)
    assert isinstance(payload.get("agent_chat_available_mcp_servers"), list)
    assert isinstance(payload.get("agent_chat_registry_debug"), dict)
    cache_status = (payload.get("agent_chat_registry_debug") or {}).get("cache_status") or {}
    assert isinstance(cache_status, dict)
    assert isinstance(cache_status.get("hit_count", 0), int)
    assert isinstance(cache_status.get("miss_count", 0), int)
    assert calls["agent_models_allow_runtime_discovery"] is False
    assert calls["mcp_include_codex_cli"] is False


def test_bootstrap_discovery_sections_are_cached_within_ttl(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)
    import features.bootstrap.read_models as bootstrap_read_models

    calls = {
        "models": 0,
        "mcp": 0,
    }

    def fake_list_available_agent_models(*, force_refresh: bool = False, allow_runtime_discovery: bool = True):
        calls["models"] += 1
        return ["codex:gpt-5"], "codex:gpt-5"

    def fake_list_available_mcp_servers(*, force_refresh: bool = False, include_codex_cli: bool = True):
        calls["mcp"] += 1
        return [{"name": "constructos-tools", "display_name": "Constructos Tools", "enabled": True}]

    monkeypatch.setattr(bootstrap_read_models, "list_available_agent_models", fake_list_available_agent_models)
    monkeypatch.setattr(bootstrap_read_models, "list_available_mcp_servers", fake_list_available_mcp_servers)
    bootstrap_read_models._clear_bootstrap_discovery_cache_for_tests()

    first = client.get("/api/bootstrap")
    second = client.get("/api/bootstrap")
    assert first.status_code == 200
    assert second.status_code == 200
    assert calls["models"] == 1
    assert calls["mcp"] == 1


def test_bootstrap_includes_architecture_inventory_summary_and_caches(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)
    import features.bootstrap.read_models as bootstrap_read_models

    calls = {
        "build_inventory": 0,
    }

    def fake_build_architecture_inventory():
        calls["build_inventory"] += 1
        return {
            "generated_at": "2026-04-02T00:00:00+00:00",
            "counts": {
                "execution_providers": 3,
                "workflow_plugins": 4,
                "constructos_mcp_tools": 5,
                "prompt_templates": 2,
                "bootstrap_startup_phases": 3,
                "bootstrap_shutdown_phases": 2,
                "internal_docs": 11,
                "internal_docs_reading_order": 11,
            },
            "internal_docs": {
                "existing_docs": [f"{idx:02d}.md" for idx in range(1, 12)],
                "reading_order": [f"{idx:02d}.md" for idx in range(1, 12)],
                "missing_from_reading_order": [],
                "unreferenced_docs": [],
            },
        }

    def fake_audit_architecture_inventory(_inventory):
        class _Result:
            ok = True
            errors: list[str] = []
            warnings: list[str] = []

        return _Result()

    monkeypatch.setattr(
        bootstrap_read_models, "_build_architecture_inventory_for_bootstrap", fake_build_architecture_inventory
    )
    monkeypatch.setattr(
        bootstrap_read_models, "_audit_architecture_inventory_for_bootstrap", fake_audit_architecture_inventory
    )
    bootstrap_read_models._clear_bootstrap_architecture_inventory_cache_for_tests()

    first = client.get("/api/bootstrap")
    second = client.get("/api/bootstrap")
    assert first.status_code == 200
    assert second.status_code == 200

    summary = first.json().get("architecture_inventory_summary") or {}
    assert isinstance(summary, dict)
    assert summary.get("generated_at") == "2026-04-02T00:00:00+00:00"
    assert (summary.get("counts") or {}).get("execution_providers") == 3
    assert (summary.get("audit") or {}).get("ok") is True
    cache_status = summary.get("cache_status") or {}
    assert isinstance(cache_status, dict)
    assert isinstance(cache_status.get("hit_count", 0), int)
    assert isinstance(cache_status.get("miss_count", 0), int)
    mirrored = ((first.json().get("config") or {}).get("architecture_inventory_summary") or {})
    assert mirrored.get("generated_at") == "2026-04-02T00:00:00+00:00"
    assert ((mirrored.get("audit") or {}).get("ok")) is True
    assert calls["build_inventory"] == 1
