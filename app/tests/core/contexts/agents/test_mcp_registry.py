from __future__ import annotations

import threading
import time


def test_opencode_registry_path_skips_codex_cli_discovery(monkeypatch):
    from features.agents import mcp_registry

    def _fail_if_called():
        raise AssertionError("codex CLI discovery must not run for this path")

    monkeypatch.setattr(mcp_registry, "_run_codex_mcp_list_json", _fail_if_called)
    monkeypatch.setattr(
        mcp_registry,
        "_load_mcp_servers_from_config",
        lambda: {"constructos-tools": {"url": "http://ignored-from-core-url"}},
    )

    payload = mcp_registry.build_selected_opencode_mcp_config_payload(
        selected_servers=["constructos-tools"],
        task_management_mcp_url="http://core-mcp.local",
        include_codex_cli=False,
    )

    assert payload["mcp"]["constructos-tools"]["type"] == "remote"
    assert payload["mcp"]["constructos-tools"]["url"] == "http://core-mcp.local"


def test_list_available_mcp_servers_returns_stale_cache_while_refreshing(monkeypatch):
    from features.agents import mcp_registry

    stale_rows = [
        {
            "name": "constructos-tools",
            "display_name": "Constructos Tools",
            "enabled": True,
            "disabled_reason": None,
            "auth_status": None,
            "config": {"url": "http://stale"},
        }
    ]
    refreshed_rows = [
        {
            "name": "constructos-tools",
            "display_name": "Constructos Tools",
            "enabled": True,
            "disabled_reason": None,
            "auth_status": "ok",
            "config": {"url": "http://fresh"},
        }
    ]

    refresh_called = threading.Event()

    def _slow_discover(*, include_codex_cli: bool = True):
        assert include_codex_cli is True
        refresh_called.set()
        time.sleep(0.3)
        return refreshed_rows

    now = time.monotonic()
    monkeypatch.setattr(mcp_registry, "_CACHE_ROWS", stale_rows.copy())
    monkeypatch.setattr(mcp_registry, "_CACHE_EXPIRES_AT", now - 1.0)
    monkeypatch.setattr(mcp_registry, "_CACHE_REFRESH_IN_PROGRESS", False)
    monkeypatch.setattr(mcp_registry, "_discover_rows_uncached", _slow_discover)

    start = time.monotonic()
    payload = mcp_registry.list_available_mcp_servers()
    elapsed = time.monotonic() - start

    assert elapsed < 0.2
    assert payload and payload[0]["auth_status"] is None
    assert refresh_called.wait(timeout=1.0) is True
    status_during_refresh = mcp_registry.mcp_registry_cache_status()
    assert isinstance(status_during_refresh.get("stale_serve_count"), int)
    assert status_during_refresh.get("stale_serve_count", 0) >= 1

    # Give the background refresh a moment to commit cache.
    time.sleep(0.35)
    refreshed_payload = mcp_registry.list_available_mcp_servers()
    assert refreshed_payload and refreshed_payload[0]["auth_status"] == "ok"
    status_after_refresh = mcp_registry.mcp_registry_cache_status()
    assert isinstance(status_after_refresh.get("refresh_count"), int)
    assert status_after_refresh.get("refresh_count", 0) >= 1
    assert status_after_refresh.get("cache_refresh_in_progress") in {True, False}
