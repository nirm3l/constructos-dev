from __future__ import annotations

import logging
import os
from datetime import datetime, timezone


def _parse_csv_env(name: str) -> set[str]:
    raw = os.getenv(name, "")
    return {item.strip() for item in raw.split(",") if item.strip()}

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    return int(raw)


DB_PATH = os.getenv("DB_PATH", "/data/app.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or f"sqlite:///{DB_PATH}"
APP_VERSION = os.getenv("APP_VERSION", "dev").strip() or "dev"
APP_BUILD = os.getenv("APP_BUILD", "").strip()
APP_DEPLOYED_AT_UTC = (
    os.getenv("APP_DEPLOYED_AT_UTC", "").strip()
    or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
)
SNAPSHOT_EVERY = int(os.getenv("SNAPSHOT_EVERY", "20"))
EVENTSTORE_URI = os.getenv("EVENTSTORE_URI", "").strip()
DEFAULT_STATUSES = ["To do", "In progress", "Done"]
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
BOOTSTRAP_USERNAME = "m4tr1x"
BOOTSTRAP_FULL_NAME = "m4tr1x"
BOOTSTRAP_WORKSPACE_ID = "10000000-0000-0000-0000-000000000001"
BOOTSTRAP_PROJECT_ID = "20000000-0000-0000-0000-000000000001"
BOOTSTRAP_TASK_ID = "30000000-0000-0000-0000-000000000001"
AGENT_SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000099"
AGENT_SYSTEM_USERNAME = "codex-bot"
AGENT_SYSTEM_FULL_NAME = "Codex Bot"
AGENT_RUNNER_ENABLED = os.getenv("AGENT_RUNNER_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
AGENT_RUNNER_INTERVAL_SECONDS = float(os.getenv("AGENT_RUNNER_INTERVAL_SECONDS", "5"))
AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS = os.getenv("AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
AGENT_EXECUTOR_MODE = os.getenv("AGENT_EXECUTOR_MODE", "placeholder").strip().lower() or "placeholder"
AGENT_EXECUTOR_TIMEOUT_SECONDS = float(os.getenv("AGENT_EXECUTOR_TIMEOUT_SECONDS", "180"))
AGENT_CODEX_COMMAND = os.getenv("AGENT_CODEX_COMMAND", "").strip()
AGENT_CODEX_MCP_URL = os.getenv("AGENT_CODEX_MCP_URL", "http://mcp-tools:8090/mcp").strip()
AGENT_CODEX_MCP_READONLY_URL = os.getenv("AGENT_CODEX_MCP_READONLY_URL", "http://mcp-tools-ro:8090/mcp").strip()
AGENT_CODEX_MODEL = os.getenv("AGENT_CODEX_MODEL", "").strip()
ATTACHMENTS_DIR = os.getenv("ATTACHMENTS_DIR", "/data/uploads").strip() or "/data/uploads"
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "").strip()
MCP_ACTOR_USER_ID = os.getenv("MCP_ACTOR_USER_ID", DEFAULT_USER_ID).strip() or DEFAULT_USER_ID
MCP_DEFAULT_WORKSPACE_ID = os.getenv("MCP_DEFAULT_WORKSPACE_ID", "").strip()
MCP_ALLOWED_WORKSPACE_IDS = _parse_csv_env("MCP_ALLOWED_WORKSPACE_IDS")
MCP_ALLOWED_PROJECT_IDS = _parse_csv_env("MCP_ALLOWED_PROJECT_IDS")

# MCP email tool configuration (optional).
MCP_EMAIL_SMTP_HOST = os.getenv("MCP_EMAIL_SMTP_HOST", "").strip()
MCP_EMAIL_SMTP_PORT = _env_int("MCP_EMAIL_SMTP_PORT", 587)
MCP_EMAIL_SMTP_USERNAME = os.getenv("MCP_EMAIL_SMTP_USERNAME", "").strip()
MCP_EMAIL_SMTP_PASSWORD = os.getenv("MCP_EMAIL_SMTP_PASSWORD", "").strip()
MCP_EMAIL_SMTP_STARTTLS = _env_bool("MCP_EMAIL_SMTP_STARTTLS", True)
MCP_EMAIL_SMTP_SSL = _env_bool("MCP_EMAIL_SMTP_SSL", False)
MCP_EMAIL_FROM = os.getenv("MCP_EMAIL_FROM", "").strip()
MCP_EMAIL_ALLOWED_RECIPIENTS = {s.strip().lower() for s in _parse_csv_env("MCP_EMAIL_ALLOWED_RECIPIENTS")}
MCP_EMAIL_ALLOWED_DOMAINS = {s.strip().lower() for s in _parse_csv_env("MCP_EMAIL_ALLOWED_DOMAINS")}

logger = logging.getLogger(__name__)
