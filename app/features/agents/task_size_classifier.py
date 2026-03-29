from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from features.agents.agent_mcp_adapter import run_structured_agent_prompt
from shared.classification_cache import ClassificationCache, build_classification_cache_key

run_structured_codex_prompt = run_structured_agent_prompt

_PROMPT_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "shared" / "prompt_templates" / "codex"
_TASK_SIZE_CLASSIFIER_VERSION = "task-size-pre-gate-v1"
_TASK_SIZE_CLASSIFIER_SCHEMA_VERSION = "1"
_TASK_SIZE_CLASSIFIER_CACHE = ClassificationCache(max_entries=256)
_TASK_SIZE_VALUES = {"small", "medium", "large", "unknown"}


@lru_cache(maxsize=16)
def _load_prompt_template(name: str) -> str:
    return (_PROMPT_TEMPLATES_DIR / name).read_text(encoding="utf-8")


def _render_prompt_template(name: str, values: dict[str, object]) -> str:
    rendered_values = {key: str(value) for key, value in values.items()}
    return _load_prompt_template(name).format(**rendered_values)


def _normalize_task_size(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _TASK_SIZE_VALUES else "unknown"


def _default_task_size_pre_gate() -> dict[str, Any]:
    return {
        "task_size": "unknown",
        "should_avoid_heavy_orchestration": False,
        "reason": "",
    }


def _normalize_task_size_pre_gate(values: dict[str, Any] | None) -> dict[str, Any]:
    parsed = dict(values or {})
    return {
        "task_size": _normalize_task_size(parsed.get("task_size")),
        "should_avoid_heavy_orchestration": bool(parsed.get("should_avoid_heavy_orchestration")),
        "reason": str(parsed.get("reason") or "").strip(),
    }


def classify_task_size_pre_gate(
    *,
    instruction: str,
    workspace_id: str,
    project_id: str | None,
    session_id: str | None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    normalized_instruction = str(instruction or "").strip()
    if not normalized_instruction:
        return _default_task_size_pre_gate()
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
            "task_size": {"type": "string", "enum": sorted(_TASK_SIZE_VALUES)},
            "should_avoid_heavy_orchestration": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": [
            "task_size",
            "should_avoid_heavy_orchestration",
            "reason",
        ],
    }
    classifier_prompt = _render_prompt_template(
        "task_size_pre_gate_classifier.md",
        {"payload_json": json.dumps(payload, ensure_ascii=True)},
    )
    cache_key = build_classification_cache_key(
        cache_name="task_size_pre_gate",
        workspace_id=str(workspace_id or "").strip() or None,
        project_id=str(project_id or "").strip() or None,
        classifier_version=_TASK_SIZE_CLASSIFIER_VERSION,
        schema_version=_TASK_SIZE_CLASSIFIER_SCHEMA_VERSION,
        payload=payload,
    )
    cached = _TASK_SIZE_CLASSIFIER_CACHE.get(cache_key)
    if cached is not None:
        return _normalize_task_size_pre_gate(cached)

    try:
        parsed = run_structured_codex_prompt(
            prompt=classifier_prompt,
            output_schema=output_schema,
            workspace_id=str(workspace_id or "").strip() or None,
            session_key=(
                f"task-size-pre-gate:{_TASK_SIZE_CLASSIFIER_VERSION}:{_TASK_SIZE_CLASSIFIER_SCHEMA_VERSION}:"
                f"{str(workspace_id or '').strip()}:{str(project_id or '').strip()}:{str(session_id or '').strip()}:"
                f"{hashlib.sha256(normalized_instruction.encode('utf-8')).hexdigest()[:16]}"
            ),
            actor_user_id=str(actor_user_id or "").strip() or None,
            mcp_servers=[],
            use_cache=True,
        )
    except Exception:
        parsed = {}
    normalized = _normalize_task_size_pre_gate(parsed if isinstance(parsed, dict) else {})
    _TASK_SIZE_CLASSIFIER_CACHE.set(cache_key, normalized)
    return normalized

