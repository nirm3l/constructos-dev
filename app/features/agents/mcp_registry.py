from __future__ import annotations

import copy
import json
import logging
import math
import os
from pathlib import Path
import subprocess
import threading
import time
import tomllib
from typing import Any

from shared.settings import AGENT_MCP_URL
from shared.models import ProjectPluginConfig, SessionLocal

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.Lock()
_CACHE_EXPIRES_AT = 0.0
_CACHE_ROWS: list[dict[str, Any]] = []
_FALLBACK_SERVER_NAME = "constructos-tools"
_LEGACY_CORE_SERVER_NAME = "constructos_tools"
_PLUGIN_SERVER_ALIASES_BY_KEY: dict[str, set[str]] = {
    "team_mode": {"team-mode", "team_mode", "team-mode-tools", "team_mode_tools"},
    "git_delivery": {"git-delivery", "git_delivery", "git-delivery-tools", "git_delivery_tools"},
    "docker_compose": {"docker-compose", "docker_compose", "docker-compose-tools", "docker_compose_tools"},
}


def _load_positive_float_env(name: str, default: float) -> float:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except Exception:
        return default
    if value <= 0:
        return default
    return value


_CACHE_TTL_SECONDS = _load_positive_float_env("MCP_REGISTRY_CACHE_TTL_SECONDS", 60.0)
_MCP_LIST_TIMEOUT_SECONDS = _load_positive_float_env("MCP_REGISTRY_LIST_TIMEOUT_SECONDS", 2.0)


def _toml_quote(value: str) -> str:
    escaped = (
        str(value or "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _toml_key(value: str) -> str:
    return _toml_quote(str(value or "").strip())


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return _toml_quote(str(value))
        return repr(value)
    if isinstance(value, str):
        return _toml_quote(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        parts: list[str] = []
        for key in sorted(value.keys(), key=lambda item: str(item)):
            item_value = value.get(key)
            if item_value is None:
                continue
            parts.append(f"{_toml_key(str(key))} = {_toml_value(item_value)}")
        return "{ " + ", ".join(parts) + " }"
    return _toml_quote(str(value))


def _codex_home_dir() -> Path:
    raw_home = str(os.getenv("CODEX_HOME", "")).strip()
    if raw_home:
        return Path(raw_home).expanduser()
    return Path.home() / ".codex"


def _codex_config_path() -> Path:
    return _codex_home_dir() / "config.toml"


def _normalize_name(value: str) -> str:
    return str(value or "").strip().lower()


def _normalize_lookup_key(value: str) -> str:
    return _normalize_name(value).replace("_", "-")


def _display_name(name: str) -> str:
    clean = str(name or "").strip()
    if not clean:
        return ""
    words = [part for part in clean.replace("_", " ").replace("-", " ").split(" ") if part]
    if not words:
        return clean
    return " ".join(word[:1].upper() + word[1:] for word in words)


def _coerce_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return None


def _load_mcp_servers_from_config() -> dict[str, dict[str, Any]]:
    path = _codex_config_path()
    if not path.exists() or not path.is_file():
        return {}
    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to parse Codex config at %s: %s", path, exc)
        return {}
    servers_raw = parsed.get("mcp_servers")
    if not isinstance(servers_raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for raw_name, raw_config in servers_raw.items():
        name = str(raw_name or "").strip()
        if not name or not isinstance(raw_config, dict):
            continue
        out[name] = copy.deepcopy(raw_config)
    return out


def _extract_json_list_payload(raw_text: str) -> list[dict[str, Any]]:
    text = str(raw_text or "").strip()
    if not text:
        return []
    candidates = [text]
    list_start = text.find("[")
    list_end = text.rfind("]")
    if list_start >= 0 and list_end >= list_start:
        candidates.append(text[list_start : list_end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if not isinstance(parsed, list):
            continue
        out: list[dict[str, Any]] = []
        for item in parsed:
            if isinstance(item, dict):
                out.append(item)
        return out
    return []


def _run_codex_mcp_list_json() -> list[dict[str, Any]]:
    try:
        proc = subprocess.run(
            ["codex", "mcp", "list", "--json"],
            text=True,
            capture_output=True,
            timeout=_MCP_LIST_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        logger.warning("codex binary not found; MCP server discovery falls back to config/env")
        return []
    except Exception as exc:
        logger.warning("Failed to run `codex mcp list --json`: %s", exc)
        return []
    if proc.returncode != 0:
        logger.warning("`codex mcp list --json` failed: %s", (proc.stderr or proc.stdout or "").strip()[:300])
        return []
    return _extract_json_list_payload(proc.stdout)


def _derive_config_from_list_entry(entry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    transport = entry.get("transport")
    if isinstance(transport, dict):
        for key, raw_value in transport.items():
            if key == "type":
                continue
            if raw_value is None:
                continue
            out[str(key)] = raw_value
    startup_timeout = entry.get("startup_timeout_sec")
    if startup_timeout is not None:
        out["startup_timeout_sec"] = startup_timeout
    tool_timeout = entry.get("tool_timeout_sec")
    if tool_timeout is not None:
        out["tool_timeout_sec"] = tool_timeout
    return out


def _discover_rows_uncached() -> list[dict[str, Any]]:
    config_rows = _load_mcp_servers_from_config()
    list_rows = _run_codex_mcp_list_json()
    list_by_name: dict[str, dict[str, Any]] = {}
    ordered_names: list[str] = []
    for row in list_rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        if name not in ordered_names:
            ordered_names.append(name)
        list_by_name[name] = row
    for name in config_rows.keys():
        if name not in ordered_names:
            ordered_names.append(name)

    rows: list[dict[str, Any]] = []
    for name in ordered_names:
        list_row = list_by_name.get(name) or {}
        config_row = config_rows.get(name) or {}
        config = copy.deepcopy(config_row or _derive_config_from_list_entry(list_row))
        list_enabled = _coerce_optional_bool(list_row.get("enabled")) if list_row else None
        config_enabled = _coerce_optional_bool(config_row.get("enabled"))
        enabled = list_enabled if list_enabled is not None else (config_enabled if config_enabled is not None else True)
        disabled_reason = str(list_row.get("disabled_reason") or "").strip() or None
        if not disabled_reason and enabled is False:
            disabled_reason = str(config_row.get("disabled_reason") or "").strip() or "Disabled in Codex config."
        auth_status = str(list_row.get("auth_status") or "").strip() or None
        rows.append(
            {
                "name": name,
                "display_name": _display_name(name),
                "enabled": enabled,
                "disabled_reason": disabled_reason,
                "auth_status": auth_status,
                "config": config,
            }
        )

    if not rows:
        rows.append(
            {
                "name": _FALLBACK_SERVER_NAME,
                "display_name": _display_name(_FALLBACK_SERVER_NAME),
                "enabled": True,
                "disabled_reason": None,
                "auth_status": None,
                "config": {"url": AGENT_MCP_URL},
            }
        )
        return rows

    by_name = {str(item["name"]): item for item in rows}
    if _FALLBACK_SERVER_NAME in by_name:
        fallback_config = by_name[_FALLBACK_SERVER_NAME].get("config")
        if not isinstance(fallback_config, dict):
            by_name[_FALLBACK_SERVER_NAME]["config"] = {"url": AGENT_MCP_URL}
            fallback_config = by_name[_FALLBACK_SERVER_NAME]["config"]
        fallback_config["url"] = AGENT_MCP_URL
    if _LEGACY_CORE_SERVER_NAME in by_name:
        legacy_config = by_name[_LEGACY_CORE_SERVER_NAME].get("config")
        if not isinstance(legacy_config, dict):
            by_name[_LEGACY_CORE_SERVER_NAME]["config"] = {"url": AGENT_MCP_URL}
            legacy_config = by_name[_LEGACY_CORE_SERVER_NAME]["config"]
        legacy_config["url"] = AGENT_MCP_URL
    return rows


def _get_rows(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    global _CACHE_ROWS, _CACHE_EXPIRES_AT
    now = time.monotonic()
    with _CACHE_LOCK:
        if not force_refresh and _CACHE_ROWS and now < _CACHE_EXPIRES_AT:
            return copy.deepcopy(_CACHE_ROWS)

    discovered = _discover_rows_uncached()
    with _CACHE_LOCK:
        _CACHE_ROWS = copy.deepcopy(discovered)
        _CACHE_EXPIRES_AT = time.monotonic() + _CACHE_TTL_SECONDS
        return copy.deepcopy(_CACHE_ROWS)


def list_available_mcp_servers(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    rows = _get_rows(force_refresh=force_refresh)
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "name": str(row.get("name") or "").strip(),
                "display_name": str(row.get("display_name") or "").strip() or _display_name(str(row.get("name") or "")),
                "enabled": bool(row.get("enabled")),
                "disabled_reason": str(row.get("disabled_reason") or "").strip() or None,
                "auth_status": str(row.get("auth_status") or "").strip() or None,
            }
        )
    return out


def normalize_chat_mcp_servers(raw_servers: list[str] | None, *, strict: bool = True) -> list[str]:
    available_rows = _get_rows()
    enabled_names = [
        str(row.get("name") or "").strip()
        for row in available_rows
        if str(row.get("name") or "").strip() and bool(row.get("enabled"))
    ]
    alias_map: dict[str, str] = {}
    for name in enabled_names:
        alias_map[_normalize_lookup_key(name)] = name
    core_aliases = {_normalize_lookup_key(_FALLBACK_SERVER_NAME), _normalize_lookup_key(_LEGACY_CORE_SERVER_NAME)}
    core_server_name = next((name for name in enabled_names if _normalize_lookup_key(name) in core_aliases), None)

    if raw_servers is None:
        defaults = list(enabled_names)
        if core_server_name and core_server_name not in defaults:
            defaults.insert(0, core_server_name)
        if defaults:
            return defaults
        return []

    requested_aliases: list[str] = []
    for raw in raw_servers:
        normalized = _normalize_lookup_key(str(raw or ""))
        if not normalized:
            continue
        requested_aliases.append(normalized)

    selected_set: set[str] = set()
    unknown: list[str] = []
    for alias in requested_aliases:
        mapped = alias_map.get(alias)
        if mapped:
            selected_set.add(mapped)
            continue
        unknown.append(alias)

    if unknown and strict:
        allowed = ", ".join(enabled_names) if enabled_names else "(none)"
        unknown_text = ", ".join(sorted(set(unknown)))
        raise ValueError(f"Unsupported MCP server '{unknown_text}'. Allowed: {allowed}")
    if core_server_name:
        selected_set.add(core_server_name)
    if not selected_set:
        return []
    return [name for name in enabled_names if name in selected_set]


def build_selected_mcp_config_text(*, selected_servers: list[str], task_management_mcp_url: str | None = None) -> str:
    rows = _get_rows()
    rows_by_name = {str(row.get("name") or "").strip(): row for row in rows}
    core_url = str(task_management_mcp_url or AGENT_MCP_URL).strip() or AGENT_MCP_URL
    lines: list[str] = []
    for server_name in selected_servers:
        clean_name = str(server_name or "").strip()
        if not clean_name:
            continue
        row = rows_by_name.get(clean_name) or {}
        config_raw = row.get("config")
        config = copy.deepcopy(config_raw) if isinstance(config_raw, dict) else {}
        lookup_key = _normalize_lookup_key(clean_name)
        if lookup_key in {_normalize_lookup_key(_FALLBACK_SERVER_NAME), _normalize_lookup_key(_LEGACY_CORE_SERVER_NAME)}:
            config["url"] = core_url
        if not config:
            continue
        lines.append(f"[mcp_servers.{_toml_key(clean_name)}]")
        for key in sorted(config.keys(), key=lambda item: str(item)):
            value = config.get(key)
            if value is None:
                continue
            lines.append(f"{_toml_key(str(key))} = {_toml_value(value)}")
        lines.append("")
    return ("\n".join(lines).strip() + "\n") if lines else ""


def _build_claude_mcp_server_config(*, server_name: str, config: dict[str, Any], core_url: str) -> dict[str, Any]:
    normalized_name = str(server_name or "").strip()
    normalized_lookup = _normalize_lookup_key(normalized_name)
    payload: dict[str, Any] = {}
    source = copy.deepcopy(config) if isinstance(config, dict) else {}
    if normalized_lookup in {_normalize_lookup_key(_FALLBACK_SERVER_NAME), _normalize_lookup_key(_LEGACY_CORE_SERVER_NAME)}:
        source["url"] = core_url
    if str(source.get("url") or "").strip():
        payload["type"] = str(source.get("type") or "http").strip() or "http"
        payload["url"] = str(source.get("url") or "").strip()
    elif str(source.get("command") or "").strip():
        payload["type"] = str(source.get("type") or "stdio").strip() or "stdio"
        payload["command"] = str(source.get("command") or "").strip()
    for key in ("args", "env", "headers"):
        value = source.get(key)
        if value is not None:
            payload[key] = copy.deepcopy(value)
    bearer_token_env_var = str(source.get("bearer_token_env_var") or "").strip()
    if bearer_token_env_var:
        payload["bearer_token_env_var"] = bearer_token_env_var
    return payload


def build_selected_mcp_config_payload(
    *,
    selected_servers: list[str],
    task_management_mcp_url: str | None = None,
) -> dict[str, Any]:
    rows = _get_rows()
    rows_by_name = {str(row.get("name") or "").strip(): row for row in rows}
    core_url = str(task_management_mcp_url or AGENT_MCP_URL).strip() or AGENT_MCP_URL
    servers: dict[str, Any] = {}
    for server_name in selected_servers:
        clean_name = str(server_name or "").strip()
        if not clean_name:
            continue
        row = rows_by_name.get(clean_name) or {}
        config_raw = row.get("config")
        server_payload = _build_claude_mcp_server_config(
            server_name=clean_name,
            config=config_raw if isinstance(config_raw, dict) else {},
            core_url=core_url,
        )
        if server_payload:
            servers[clean_name] = server_payload
    return {"mcpServers": servers} if servers else {}


def _build_opencode_mcp_server_config(*, server_name: str, config: dict[str, Any], core_url: str) -> dict[str, Any]:
    normalized_name = str(server_name or "").strip()
    normalized_lookup = _normalize_lookup_key(normalized_name)
    source = copy.deepcopy(config) if isinstance(config, dict) else {}
    if normalized_lookup in {_normalize_lookup_key(_FALLBACK_SERVER_NAME), _normalize_lookup_key(_LEGACY_CORE_SERVER_NAME)}:
        source["url"] = core_url

    url = str(source.get("url") or "").strip()
    if url:
        payload: dict[str, Any] = {
            "type": "remote",
            "url": url,
            "enabled": True,
        }
        headers = source.get("headers")
        if isinstance(headers, dict) and headers:
            payload["headers"] = copy.deepcopy(headers)
        oauth = source.get("oauth")
        if oauth is False or isinstance(oauth, dict):
            payload["oauth"] = copy.deepcopy(oauth)
        timeout = source.get("timeout")
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
            payload["timeout"] = timeout
        return payload

    command_value = source.get("command")
    args_value = source.get("args")
    command: list[str] = []
    if isinstance(command_value, list):
        command = [str(item) for item in command_value if str(item or "").strip()]
    elif str(command_value or "").strip():
        command = [str(command_value).strip()]
        if isinstance(args_value, list):
            command.extend(str(item) for item in args_value if str(item or "").strip())
    if not command:
        return {}

    payload = {
        "type": "local",
        "command": command,
        "enabled": True,
    }
    environment = source.get("environment")
    if not isinstance(environment, dict):
        environment = source.get("env")
    if isinstance(environment, dict) and environment:
        payload["environment"] = copy.deepcopy(environment)
    timeout = source.get("timeout")
    if isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
        payload["timeout"] = timeout
    return payload


def build_selected_opencode_mcp_config_payload(
    *,
    selected_servers: list[str],
    task_management_mcp_url: str | None = None,
) -> dict[str, Any]:
    rows = _get_rows()
    rows_by_name = {str(row.get("name") or "").strip(): row for row in rows}
    core_url = str(task_management_mcp_url or AGENT_MCP_URL).strip() or AGENT_MCP_URL
    servers: dict[str, Any] = {}
    for server_name in selected_servers:
        clean_name = str(server_name or "").strip()
        if not clean_name:
            continue
        row = rows_by_name.get(clean_name) or {}
        config_raw = row.get("config")
        server_payload = _build_opencode_mcp_server_config(
            server_name=clean_name,
            config=config_raw if isinstance(config_raw, dict) else {},
            core_url=core_url,
        )
        if server_payload:
            servers[clean_name] = server_payload
    return {"mcp": servers} if servers else {}


def filter_mcp_servers_for_project_plugins(
    *,
    project_id: str | None,
    selected_servers: list[str] | None,
) -> list[str]:
    normalized_project_id = str(project_id or "").strip()
    normalized_selected = [str(item or "").strip() for item in (selected_servers or []) if str(item or "").strip()]
    if not normalized_project_id or not normalized_selected:
        return normalized_selected

    with SessionLocal() as db:
        rows = db.query(ProjectPluginConfig.plugin_key, ProjectPluginConfig.enabled).filter(
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key.in_(list(_PLUGIN_SERVER_ALIASES_BY_KEY.keys())),
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        ).all()
    enabled_by_plugin = {
        str(plugin_key or "").strip().lower(): bool(enabled)
        for plugin_key, enabled in rows
        if str(plugin_key or "").strip()
    }
    normalized_alias_map: dict[str, str] = {}
    for plugin_key, aliases in _PLUGIN_SERVER_ALIASES_BY_KEY.items():
        for alias in aliases:
            normalized_alias_map[_normalize_lookup_key(alias)] = plugin_key

    out: list[str] = []
    for server_name in normalized_selected:
        mapped_plugin = normalized_alias_map.get(_normalize_lookup_key(server_name))
        if mapped_plugin and not bool(enabled_by_plugin.get(mapped_plugin, False)):
            continue
        out.append(server_name)
    return out
