from __future__ import annotations

import logging
import os
from datetime import datetime, timezone


def _parse_csv_env(name: str) -> set[str]:
    raw = os.getenv(name, "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _parse_csv_list_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    out: list[str] = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        if value in out:
            continue
        out.append(value)
    return out


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


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    return float(raw)


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
AGENT_CHAT_CONTEXT_LIMIT_TOKENS = _env_int("AGENT_CHAT_CONTEXT_LIMIT_TOKENS", 0)
AGENT_CHAT_HISTORY_COMPACT_THRESHOLD = _env_int("AGENT_CHAT_HISTORY_COMPACT_THRESHOLD", 24)
AGENT_CHAT_HISTORY_RECENT_TAIL = _env_int("AGENT_CHAT_HISTORY_RECENT_TAIL", 8)
AGENT_CODEX_COMMAND = os.getenv("AGENT_CODEX_COMMAND", "").strip()
AGENT_CODEX_MCP_URL = os.getenv("AGENT_CODEX_MCP_URL", "http://mcp-tools:8090/mcp").strip()
AGENT_CODEX_MODEL = os.getenv("AGENT_CODEX_MODEL", "").strip()
ATTACHMENTS_DIR = os.getenv("ATTACHMENTS_DIR", "/data/uploads").strip() or "/data/uploads"
AUTH_SESSION_COOKIE_NAME = os.getenv("AUTH_SESSION_COOKIE_NAME", "m4tr1x_session").strip() or "m4tr1x_session"
AUTH_SESSION_TTL_HOURS = _env_int("AUTH_SESSION_TTL_HOURS", 24 * 14)
AUTH_COOKIE_SECURE = _env_bool("AUTH_COOKIE_SECURE", False)
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

KNOWLEDGE_GRAPH_ENABLED = _env_bool("KNOWLEDGE_GRAPH_ENABLED", False)
NEO4J_URI = os.getenv("NEO4J_URI", "").strip()
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "").strip()
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "").strip()
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j").strip() or "neo4j"
GRAPH_PROJECTION_BATCH_SIZE = _env_int("GRAPH_PROJECTION_BATCH_SIZE", 500)
GRAPH_CONTEXT_MAX_HOPS = _env_int("GRAPH_CONTEXT_MAX_HOPS", 2)
GRAPH_CONTEXT_MAX_TOKENS = _env_int("GRAPH_CONTEXT_MAX_TOKENS", 1600)
GRAPH_RAG_ENABLED = _env_bool("GRAPH_RAG_ENABLED", False)
GRAPH_RAG_CANARY_WORKSPACE_IDS = _parse_csv_env("GRAPH_RAG_CANARY_WORKSPACE_IDS")
GRAPH_RAG_CANARY_PROJECT_IDS = _parse_csv_env("GRAPH_RAG_CANARY_PROJECT_IDS")
GRAPH_RAG_SUMMARY_MODEL = os.getenv("GRAPH_RAG_SUMMARY_MODEL", "").strip()
GRAPH_RAG_SLO_CONTEXT_NO_SUMMARY_MS = _env_int("GRAPH_RAG_SLO_CONTEXT_NO_SUMMARY_MS", 1200)
GRAPH_RAG_SLO_CONTEXT_WITH_SUMMARY_MS = _env_int("GRAPH_RAG_SLO_CONTEXT_WITH_SUMMARY_MS", 2500)
GRAPH_RAG_SLO_EMBED_INGEST_P95_MS = _env_int("GRAPH_RAG_SLO_EMBED_INGEST_P95_MS", 800)
GRAPH_RAG_SLO_EMBED_CONTEXT_ERROR_RATE_PCT = _env_float("GRAPH_RAG_SLO_EMBED_CONTEXT_ERROR_RATE_PCT", 0.1)
VECTOR_STORE_ENABLED = _env_bool("VECTOR_STORE_ENABLED", False)
CONTEXT_PACK_EVIDENCE_TOP_K = _env_int("CONTEXT_PACK_EVIDENCE_TOP_K", 10)
CHAT_VECTOR_RETENTION_MODE = os.getenv("CHAT_VECTOR_RETENTION_MODE", "purge").strip().lower() or "purge"
CHAT_GRAPH_RETENTION_MODE = os.getenv("CHAT_GRAPH_RETENTION_MODE", "purge").strip().lower() or "purge"

PERSISTENT_SUBSCRIPTION_READ_MODEL_GROUP = (
    os.getenv("PERSISTENT_SUBSCRIPTION_READ_MODEL_GROUP", "task-management-read-model").strip()
    or "task-management-read-model"
)
PERSISTENT_SUBSCRIPTION_GRAPH_GROUP = (
    os.getenv("PERSISTENT_SUBSCRIPTION_GRAPH_GROUP", "task-management-graph-v2").strip()
    or "task-management-graph-v2"
)
PERSISTENT_SUBSCRIPTION_VECTOR_GROUP = (
    os.getenv("PERSISTENT_SUBSCRIPTION_VECTOR_GROUP", "task-management-vector-v2").strip()
    or "task-management-vector-v2"
)
PERSISTENT_SUBSCRIPTION_EVENT_BUFFER_SIZE = _env_int("PERSISTENT_SUBSCRIPTION_EVENT_BUFFER_SIZE", 150)
PERSISTENT_SUBSCRIPTION_MAX_ACK_BATCH_SIZE = _env_int("PERSISTENT_SUBSCRIPTION_MAX_ACK_BATCH_SIZE", 50)
PERSISTENT_SUBSCRIPTION_MAX_ACK_DELAY_SECONDS = _env_float("PERSISTENT_SUBSCRIPTION_MAX_ACK_DELAY_SECONDS", 0.2)
PERSISTENT_SUBSCRIPTION_STOPPING_GRACE_SECONDS = _env_float("PERSISTENT_SUBSCRIPTION_STOPPING_GRACE_SECONDS", 0.2)
PERSISTENT_SUBSCRIPTION_RETRY_BACKOFF_SECONDS = _env_float("PERSISTENT_SUBSCRIPTION_RETRY_BACKOFF_SECONDS", 1.0)

SYSTEM_NOTIFICATIONS_INTERVAL_SECONDS = _env_float("SYSTEM_NOTIFICATIONS_INTERVAL_SECONDS", 60.0)

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "ollama").strip().lower() or "ollama"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").strip() or "http://ollama:11434"
DEFAULT_EMBEDDING_MODEL = os.getenv("DEFAULT_EMBEDDING_MODEL", "nomic-embed-text").strip() or "nomic-embed-text"
ALLOWED_EMBEDDING_MODELS = _parse_csv_list_env("ALLOWED_EMBEDDING_MODELS") or [DEFAULT_EMBEDDING_MODEL]
OLLAMA_EMBED_GPU_ENABLED = _env_bool("OLLAMA_EMBED_GPU_ENABLED", True)

# License enforcement is intentionally always enabled in runtime.
LICENSE_ENFORCEMENT_ENABLED = True
LICENSE_INSTALLATION_ID = os.getenv("LICENSE_INSTALLATION_ID", "").strip()
# License server endpoint is intentionally fixed in runtime and not configurable
# via customer-side environment variables.
LICENSE_SERVER_URL = "https://licence.constructos.dev"
LICENSE_SERVER_TOKEN = os.getenv("LICENSE_SERVER_TOKEN", "").strip()
LICENSE_PUBLIC_KEY = os.getenv("LICENSE_PUBLIC_KEY", "").strip()
LICENSE_HEARTBEAT_SECONDS = _env_int("LICENSE_HEARTBEAT_SECONDS", 900)
LICENSE_GRACE_HOURS = _env_int("LICENSE_GRACE_HOURS", 72)
LICENSE_TRIAL_DAYS = _env_int("LICENSE_TRIAL_DAYS", 7)
SUPPORT_BUG_REPORT_OUTBOX_ENABLED = _env_bool("SUPPORT_BUG_REPORT_OUTBOX_ENABLED", True)
SUPPORT_BUG_REPORT_OUTBOX_POLL_SECONDS = _env_float("SUPPORT_BUG_REPORT_OUTBOX_POLL_SECONDS", 30.0)
SUPPORT_BUG_REPORT_OUTBOX_BATCH_SIZE = max(1, _env_int("SUPPORT_BUG_REPORT_OUTBOX_BATCH_SIZE", 20))
SUPPORT_BUG_REPORT_OUTBOX_MAX_ATTEMPTS = max(1, _env_int("SUPPORT_BUG_REPORT_OUTBOX_MAX_ATTEMPTS", 15))
SUPPORT_BUG_REPORT_OUTBOX_INITIAL_BACKOFF_SECONDS = max(
    1.0, _env_float("SUPPORT_BUG_REPORT_OUTBOX_INITIAL_BACKOFF_SECONDS", 30.0)
)

logger = logging.getLogger(__name__)
