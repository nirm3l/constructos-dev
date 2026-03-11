from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any

from features.agents.codex_mcp_adapter import run_structured_codex_prompt
from shared.classification_cache import ClassificationCache, build_classification_cache_key

_PROMPT_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "shared" / "prompt_templates" / "codex"
_WORKFLOW_SCOPES = {"team_mode", "single_agent", "unknown"}
_EXECUTION_MODES = {"setup_only", "setup_then_kickoff", "kickoff_only", "resume_execution", "unknown"}
_INTENT_CLASSIFIER_VERSION = "instruction-intent-v1"
_INTENT_CLASSIFIER_SCHEMA_VERSION = "1"
_INTENT_CLASSIFICATION_CACHE = ClassificationCache(max_entries=256)
_INTENT_CLASSIFIER_STATS = {
    "classify_calls": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "resolve_reused_envelope": 0,
}
_INTENT_CLASSIFIER_STATS_LOCK = RLock()
_FULL_INTENT_ENVELOPE_FIELDS = (
    "execution_intent",
    "execution_kickoff_intent",
    "project_creation_intent",
    "workflow_scope",
    "execution_mode",
    "deploy_requested",
    "docker_compose_requested",
    "requested_port",
    "exact_task_count",
    "project_name_provided",
    "task_completion_requested",
    "reason",
)
_AUTOMATION_REQUEST_INTENT_FIELDS = (
    "execution_intent",
    "execution_kickoff_intent",
    "project_creation_intent",
    "workflow_scope",
    "execution_mode",
    "task_completion_requested",
    "reason",
)


@lru_cache(maxsize=16)
def _load_prompt_template(name: str) -> str:
    return (_PROMPT_TEMPLATES_DIR / name).read_text(encoding="utf-8")


def _render_prompt_template(name: str, values: dict[str, object]) -> str:
    rendered_values = {key: str(value) for key, value in values.items()}
    return _load_prompt_template(name).format(**rendered_values)


def _normalize_scope(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _WORKFLOW_SCOPES else "unknown"


def _normalize_execution_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _EXECUTION_MODES else "unknown"


def _normalize_optional_port(value: Any) -> int | None:
    try:
        normalized = int(value)
    except Exception:
        return None
    if 1 <= normalized <= 65535:
        return normalized
    return None


def _normalize_optional_task_count(value: Any) -> int | None:
    try:
        normalized = int(value)
    except Exception:
        return None
    if normalized <= 0:
        return None
    return normalized


def _default_intent_envelope() -> dict[str, Any]:
    return {
        "execution_intent": False,
        "execution_kickoff_intent": False,
        "project_creation_intent": False,
        "workflow_scope": "unknown",
        "execution_mode": "unknown",
        "deploy_requested": False,
        "docker_compose_requested": False,
        "requested_port": None,
        "exact_task_count": None,
        "project_name_provided": False,
        "task_completion_requested": False,
        "reason": "",
    }


def _normalize_intent_envelope(values: dict[str, Any] | None) -> dict[str, Any]:
    parsed = dict(values or {})
    normalized = _default_intent_envelope()
    normalized["execution_intent"] = bool(parsed.get("execution_intent"))
    normalized["execution_kickoff_intent"] = bool(parsed.get("execution_kickoff_intent"))
    normalized["project_creation_intent"] = bool(parsed.get("project_creation_intent"))
    normalized["workflow_scope"] = _normalize_scope(parsed.get("workflow_scope"))
    normalized["execution_mode"] = _normalize_execution_mode(parsed.get("execution_mode"))
    normalized["deploy_requested"] = bool(parsed.get("deploy_requested"))
    normalized["docker_compose_requested"] = bool(parsed.get("docker_compose_requested"))
    normalized["requested_port"] = _normalize_optional_port(parsed.get("requested_port"))
    normalized["exact_task_count"] = _normalize_optional_task_count(parsed.get("exact_task_count"))
    normalized["project_name_provided"] = bool(parsed.get("project_name_provided"))
    normalized["task_completion_requested"] = bool(parsed.get("task_completion_requested"))
    normalized["reason"] = str(parsed.get("reason") or "").strip()
    return normalized


def _build_partial_intent_envelope(values: dict[str, Any] | None) -> dict[str, Any]:
    parsed = dict(values or {})
    return {
        "execution_intent": parsed.get("execution_intent"),
        "execution_kickoff_intent": parsed.get("execution_kickoff_intent"),
        "project_creation_intent": parsed.get("project_creation_intent"),
        "workflow_scope": (
            _normalize_scope(parsed.get("workflow_scope"))
            if parsed.get("workflow_scope") is not None
            else None
        ),
        "execution_mode": (
            _normalize_execution_mode(parsed.get("execution_mode"))
            if parsed.get("execution_mode") is not None
            else None
        ),
        "deploy_requested": parsed.get("deploy_requested"),
        "docker_compose_requested": parsed.get("docker_compose_requested"),
        "requested_port": (
            _normalize_optional_port(parsed.get("requested_port"))
            if parsed.get("requested_port") is not None
            else None
        ),
        "exact_task_count": (
            _normalize_optional_task_count(parsed.get("exact_task_count"))
            if parsed.get("exact_task_count") is not None
            else None
        ),
        "project_name_provided": parsed.get("project_name_provided"),
        "task_completion_requested": parsed.get("task_completion_requested"),
        "reason": str(parsed.get("reason") or "").strip() or None,
    }


def _intent_envelope_is_complete(
    values: dict[str, Any] | None,
    *,
    required_fields: tuple[str, ...] | None = None,
) -> bool:
    partial = _build_partial_intent_envelope(values)
    required_keys = required_fields or _FULL_INTENT_ENVELOPE_FIELDS
    return all(partial.get(key) is not None for key in required_keys)


def classify_instruction_intent(
    *,
    instruction: str,
    workspace_id: str,
    project_id: str | None,
    session_id: str | None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    normalized_instruction = str(instruction or "").strip()
    if not normalized_instruction:
        return _default_intent_envelope()
    payload = {
        "instruction": normalized_instruction,
        "workspace_id": str(workspace_id or "").strip() or None,
        "project_id": str(project_id or "").strip() or None,
        "session_id": str(session_id or "").strip() or None,
    }
    output_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "execution_intent": {"type": "boolean"},
            "execution_kickoff_intent": {"type": "boolean"},
            "project_creation_intent": {"type": "boolean"},
            "workflow_scope": {"type": "string", "enum": sorted(_WORKFLOW_SCOPES)},
            "execution_mode": {"type": "string", "enum": sorted(_EXECUTION_MODES)},
            "deploy_requested": {"type": "boolean"},
            "docker_compose_requested": {"type": "boolean"},
            "requested_port": {"type": ["integer", "null"]},
            "exact_task_count": {"type": ["integer", "null"]},
            "project_name_provided": {"type": "boolean"},
            "task_completion_requested": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": [
            "execution_intent",
            "execution_kickoff_intent",
            "project_creation_intent",
            "workflow_scope",
            "execution_mode",
            "deploy_requested",
            "docker_compose_requested",
            "requested_port",
            "exact_task_count",
            "project_name_provided",
            "task_completion_requested",
            "reason",
        ],
    }
    classifier_prompt = _render_prompt_template(
        "chat_intent_classifier.md",
        {"payload_json": json.dumps(payload, ensure_ascii=True)},
    )
    cache_key = build_classification_cache_key(
        cache_name="instruction_intent",
        workspace_id=str(workspace_id or "").strip() or None,
        project_id=str(project_id or "").strip() or None,
        classifier_version=_INTENT_CLASSIFIER_VERSION,
        schema_version=_INTENT_CLASSIFIER_SCHEMA_VERSION,
        payload=payload,
    )
    with _INTENT_CLASSIFIER_STATS_LOCK:
        _INTENT_CLASSIFIER_STATS["classify_calls"] += 1
    cached = _INTENT_CLASSIFICATION_CACHE.get(cache_key)
    if cached is not None:
        with _INTENT_CLASSIFIER_STATS_LOCK:
            _INTENT_CLASSIFIER_STATS["cache_hits"] += 1
        return _normalize_intent_envelope(cached)
    with _INTENT_CLASSIFIER_STATS_LOCK:
        _INTENT_CLASSIFIER_STATS["cache_misses"] += 1
    try:
        parsed = run_structured_codex_prompt(
            prompt=classifier_prompt,
            output_schema=output_schema,
            workspace_id=str(workspace_id or "").strip() or None,
            session_key=(
                f"chat-intent-classifier:{_INTENT_CLASSIFIER_VERSION}:{_INTENT_CLASSIFIER_SCHEMA_VERSION}:"
                f"{str(workspace_id or '').strip()}:{str(project_id or '').strip()}:{str(session_id or '').strip()}:"
                f"{hashlib.sha256(normalized_instruction.encode('utf-8')).hexdigest()[:16]}"
            ),
            actor_user_id=str(actor_user_id or "").strip() or None,
            mcp_servers=[],
            use_cache=True,
        )
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    normalized = _normalize_intent_envelope(parsed)
    _INTENT_CLASSIFICATION_CACHE.set(cache_key, normalized)
    return deepcopy(normalized)


def resolve_instruction_intent(
    *,
    instruction: str | None,
    workspace_id: str,
    project_id: str | None,
    session_id: str | None,
    current: dict[str, Any] | None = None,
    classify_fn=None,
    required_fields: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    partial = _build_partial_intent_envelope(current)
    if not str(instruction or "").strip():
        return partial
    if _intent_envelope_is_complete(partial, required_fields=required_fields):
        with _INTENT_CLASSIFIER_STATS_LOCK:
            _INTENT_CLASSIFIER_STATS["resolve_reused_envelope"] += 1
        return _normalize_intent_envelope(partial)
    effective_classify = classify_fn or classify_instruction_intent
    classified = effective_classify(
        instruction=str(instruction or "").strip(),
        workspace_id=workspace_id,
        project_id=project_id,
        session_id=session_id,
    )
    merged = dict(_normalize_intent_envelope(classified))
    for key, value in partial.items():
        if value is not None:
            merged[key] = value
    return _normalize_intent_envelope(merged)


def clear_instruction_intent_cache() -> None:
    _INTENT_CLASSIFICATION_CACHE.clear()


AUTOMATION_REQUEST_INTENT_FIELDS = _AUTOMATION_REQUEST_INTENT_FIELDS


def reset_instruction_intent_stats() -> None:
    with _INTENT_CLASSIFIER_STATS_LOCK:
        for key in _INTENT_CLASSIFIER_STATS:
            _INTENT_CLASSIFIER_STATS[key] = 0


def get_instruction_intent_stats() -> dict[str, int]:
    with _INTENT_CLASSIFIER_STATS_LOCK:
        return {key: int(value) for key, value in _INTENT_CLASSIFIER_STATS.items()}


def is_team_mode_kickoff_classification(classification: dict[str, Any] | None) -> bool:
    normalized = dict(classification or {})
    if str(normalized.get("workflow_scope") or "").strip().lower() != "team_mode":
        return False
    if not bool(normalized.get("execution_kickoff_intent")):
        return False
    execution_mode = _normalize_execution_mode(normalized.get("execution_mode"))
    return execution_mode in {"setup_then_kickoff", "kickoff_only"}
