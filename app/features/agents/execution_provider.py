from __future__ import annotations

from shared.settings import AGENT_DEFAULT_EXECUTION_PROVIDER

_KNOWN_EXECUTION_PROVIDERS = {"codex", "claude"}
_CLAUDE_MODEL_ALIASES = {"sonnet", "opus", "haiku"}


def normalize_execution_provider(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized not in _KNOWN_EXECUTION_PROVIDERS:
        return None
    return normalized


def encode_execution_model(*, provider: str | None, model: object) -> str:
    normalized_model = str(model or "").strip()
    if not normalized_model:
        return ""
    normalized_provider = normalize_execution_provider(provider)
    if not normalized_provider:
        return normalized_model
    return f"{normalized_provider}:{normalized_model}"


def parse_execution_model(value: object) -> tuple[str | None, str | None]:
    raw = str(value or "").strip()
    if not raw:
        return None, None
    for separator in (":", "/"):
        provider_part, separator_value, model_part = raw.partition(separator)
        provider = normalize_execution_provider(provider_part)
        model = str(model_part or "").strip()
        if separator_value and provider and model:
            return provider, model
    lowered = raw.lower()
    if lowered in _CLAUDE_MODEL_ALIASES or lowered.startswith("claude-"):
        return "claude", raw
    return "codex", raw


def resolve_execution_provider(value: object, *, default_provider: str | None = None) -> str:
    provider, _ = parse_execution_model(value)
    if provider:
        return provider
    fallback = normalize_execution_provider(default_provider)
    if fallback:
        return fallback
    return normalize_execution_provider(AGENT_DEFAULT_EXECUTION_PROVIDER) or "codex"
