from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback.
    import tomli as tomllib  # type: ignore[no-redef]


DEFAULT_APP_MCP_NAME = "task-management-tools"
DEFAULT_APP_MCP_URL = "http://localhost:8091/mcp"
DEFAULT_SYSTEM_PROMPT_FILE = "~/.cos/system.md"
DEFAULT_APP_MCP_BEARER_ENV = ""
DEFAULT_TERMINAL_THEME = "green"
DEFAULT_CODEX_BACKEND = "docker"
DEFAULT_DOCKER_CONTAINER = "task-app"
DEFAULT_DOCKER_WORKDIR = "/app"
DEFAULT_DOCKER_CODEX_BINARY = "codex"
DEFAULT_DOCKER_APP_MCP_URL = "http://mcp-tools:8090/mcp"
DEFAULT_DOCKER_CODEX_HOME_ROOT = "/home/app/codex-home/workspace"

VALID_SANDBOX = {"read-only", "workspace-write", "danger-full-access"}
VALID_APPROVAL = {"untrusted", "on-request", "never"}
VALID_TERMINAL_THEME = {"default", "green"}
VALID_CODEX_BACKEND = {"local", "docker"}

DEFAULTS: dict[str, Any] = {
    "repo": "",
    "model": "",
    "sandbox": "workspace-write",
    "approval": "on-request",
    "terminal_theme": DEFAULT_TERMINAL_THEME,
    "codex_backend": DEFAULT_CODEX_BACKEND,
    "docker_container": DEFAULT_DOCKER_CONTAINER,
    "docker_workdir": DEFAULT_DOCKER_WORKDIR,
    "docker_codex_binary": DEFAULT_DOCKER_CODEX_BINARY,
    "docker_app_mcp_url": DEFAULT_DOCKER_APP_MCP_URL,
    "docker_codex_home_root": DEFAULT_DOCKER_CODEX_HOME_ROOT,
    "app_mcp_name": DEFAULT_APP_MCP_NAME,
    "app_mcp_url": DEFAULT_APP_MCP_URL,
    "app_mcp_bearer_env": DEFAULT_APP_MCP_BEARER_ENV,
    "system_prompt_file": DEFAULT_SYSTEM_PROMPT_FILE,
}

ENV_VAR_MAP: dict[str, str] = {
    "repo": "COS_REPO",
    "model": "COS_MODEL",
    "sandbox": "COS_SANDBOX",
    "approval": "COS_APPROVAL",
    "terminal_theme": "COS_TERMINAL_THEME",
    "codex_backend": "COS_CODEX_BACKEND",
    "docker_container": "COS_DOCKER_CONTAINER",
    "docker_workdir": "COS_DOCKER_WORKDIR",
    "docker_codex_binary": "COS_DOCKER_CODEX_BINARY",
    "docker_app_mcp_url": "COS_DOCKER_APP_MCP_URL",
    "docker_codex_home_root": "COS_DOCKER_CODEX_HOME_ROOT",
    "app_mcp_name": "COS_APP_MCP_NAME",
    "app_mcp_url": "COS_APP_MCP_URL",
    "app_mcp_bearer_env": "COS_APP_MCP_BEARER_ENV",
    "system_prompt_file": "COS_SYSTEM_PROMPT_FILE",
}

CONFIG_KEYS = set(DEFAULTS.keys())


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedConfig:
    values: dict[str, Any]
    sources: dict[str, str]
    global_config_path: Path
    local_config_path: Path
    global_config_exists: bool
    local_config_exists: bool


def _coerce_string(key: str, value: Any, source: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{source}: key '{key}' must be a string.")
    return value.strip()


def _validate_value(key: str, value: Any, source: str) -> Any:
    text_value = _coerce_string(key, value, source)
    if key == "sandbox" and text_value not in VALID_SANDBOX:
        allowed = ", ".join(sorted(VALID_SANDBOX))
        raise ConfigError(f"{source}: invalid value for '{key}' ({text_value!r}). Allowed: {allowed}.")
    if key == "approval" and text_value not in VALID_APPROVAL:
        allowed = ", ".join(sorted(VALID_APPROVAL))
        raise ConfigError(f"{source}: invalid value for '{key}' ({text_value!r}). Allowed: {allowed}.")
    if key == "terminal_theme" and text_value not in VALID_TERMINAL_THEME:
        allowed = ", ".join(sorted(VALID_TERMINAL_THEME))
        raise ConfigError(f"{source}: invalid value for '{key}' ({text_value!r}). Allowed: {allowed}.")
    if key == "codex_backend" and text_value not in VALID_CODEX_BACKEND:
        allowed = ", ".join(sorted(VALID_CODEX_BACKEND))
        raise ConfigError(f"{source}: invalid value for '{key}' ({text_value!r}). Allowed: {allowed}.")
    return text_value


def _config_file_paths(repo_hint: str | None = None) -> tuple[Path, Path]:
    global_path = Path("~/.cos/config.toml").expanduser()
    if str(repo_hint or "").strip():
        repo_root = Path(str(repo_hint)).expanduser()
    else:
        repo_root = Path.cwd()
    local_path = repo_root / ".cos" / "config.toml"
    return global_path, local_path


def _load_config_file(path: Path) -> tuple[dict[str, str], list[str]]:
    with path.open("rb") as handle:
        loaded = tomllib.load(handle)

    if not isinstance(loaded, dict):
        raise ConfigError(f"{path}: expected TOML object at root.")

    section_data: Any
    if "cos" in loaded:
        section_data = loaded.get("cos")
        if not isinstance(section_data, dict):
            raise ConfigError(f"{path}: [cos] section must be a table.")
    else:
        section_data = loaded

    values: dict[str, str] = {}
    unknown_keys: list[str] = []
    for key, raw_value in section_data.items():
        if key not in CONFIG_KEYS:
            unknown_keys.append(str(key))
            continue
        values[key] = _validate_value(key, raw_value, str(path))
    return values, unknown_keys


def _load_existing_config_file(path: Path) -> tuple[dict[str, str], list[str], bool]:
    if not path.exists():
        return {}, [], False
    if not path.is_file():
        raise ConfigError(f"{path}: expected a regular file.")
    values, unknown_keys = _load_config_file(path)
    return values, unknown_keys, True


def resolve_effective_config(
    *,
    repo_hint: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> ResolvedConfig:
    values: dict[str, Any] = dict(DEFAULTS)
    sources: dict[str, str] = {key: "default" for key in CONFIG_KEYS}

    global_path, local_path = _config_file_paths(repo_hint=repo_hint)
    global_values, _, global_exists = _load_existing_config_file(global_path)
    local_values, _, local_exists = _load_existing_config_file(local_path)

    for key, value in global_values.items():
        values[key] = value
        sources[key] = "global_config"
    for key, value in local_values.items():
        values[key] = value
        sources[key] = "local_config"

    for key, env_name in ENV_VAR_MAP.items():
        env_value = str(os.getenv(env_name, "")).strip()
        if not env_value:
            continue
        values[key] = _validate_value(key, env_value, f"environment variable {env_name}")
        sources[key] = "env"

    for key, raw_value in (overrides or {}).items():
        if key not in CONFIG_KEYS or raw_value is None:
            continue
        values[key] = _validate_value(key, raw_value, "CLI option")
        sources[key] = "cli"

    return ResolvedConfig(
        values=values,
        sources=sources,
        global_config_path=global_path,
        local_config_path=local_path,
        global_config_exists=global_exists,
        local_config_exists=local_exists,
    )


def validate_config_files(repo_hint: str | None = None) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    global_path, local_path = _config_file_paths(repo_hint=repo_hint)

    for label, path in (("global", global_path), ("local", local_path)):
        if not path.exists():
            checks.append(
                {
                    "name": f"{label}_config_file",
                    "status": "ok",
                    "message": f"Optional file not found: {path}",
                }
            )
            continue

        if not path.is_file():
            checks.append(
                {
                    "name": f"{label}_config_file",
                    "status": "fail",
                    "message": f"Expected a regular file: {path}",
                }
            )
            continue

        try:
            _, unknown_keys = _load_config_file(path)
            checks.append(
                {
                    "name": f"{label}_config_file",
                    "status": "ok",
                    "message": f"Parsed successfully: {path}",
                }
            )
            for key in unknown_keys:
                checks.append(
                    {
                        "name": f"{label}_config_unknown_key",
                        "status": "warn",
                        "message": f"Unknown key '{key}' in {path}",
                    }
                )
        except ConfigError as exc:
            checks.append(
                {
                    "name": f"{label}_config_file",
                    "status": "fail",
                    "message": str(exc),
                }
            )

    return checks
