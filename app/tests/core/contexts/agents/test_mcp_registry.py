from __future__ import annotations


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

