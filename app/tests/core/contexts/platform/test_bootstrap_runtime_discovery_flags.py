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
