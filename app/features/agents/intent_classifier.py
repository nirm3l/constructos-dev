from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from features.agents.codex_mcp_adapter import run_structured_codex_prompt

_PROMPT_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "shared" / "prompt_templates" / "codex"
_WORKFLOW_SCOPES = {"team_mode", "single_agent", "unknown"}
_EXECUTION_MODES = {"setup_only", "setup_then_kickoff", "kickoff_only", "resume_execution", "unknown"}


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


def classify_instruction_intent(
    *,
    instruction: str,
    workspace_id: str,
    project_id: str | None,
    session_id: str | None,
) -> dict[str, Any]:
    normalized_instruction = str(instruction or "").strip()
    if not normalized_instruction:
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
    try:
        parsed = run_structured_codex_prompt(
            prompt=classifier_prompt,
            output_schema=output_schema,
            workspace_id=str(workspace_id or "").strip() or None,
            session_key=(
                f"chat-intent-classifier:{str(workspace_id or '').strip()}:{str(project_id or '').strip()}:"
                f"{hashlib.sha256(normalized_instruction.encode('utf-8')).hexdigest()[:16]}"
            ),
            mcp_servers=[],
            use_cache=True,
        )
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return {
        "execution_intent": bool(parsed.get("execution_intent")),
        "execution_kickoff_intent": bool(parsed.get("execution_kickoff_intent")),
        "project_creation_intent": bool(parsed.get("project_creation_intent")),
        "workflow_scope": _normalize_scope(parsed.get("workflow_scope")),
        "execution_mode": _normalize_execution_mode(parsed.get("execution_mode")),
        "deploy_requested": bool(parsed.get("deploy_requested")),
        "docker_compose_requested": bool(parsed.get("docker_compose_requested")),
        "requested_port": _normalize_optional_port(parsed.get("requested_port")),
        "exact_task_count": _normalize_optional_task_count(parsed.get("exact_task_count")),
        "project_name_provided": bool(parsed.get("project_name_provided")),
        "task_completion_requested": bool(parsed.get("task_completion_requested")),
        "reason": str(parsed.get("reason") or "").strip(),
    }


def is_team_mode_kickoff_classification(classification: dict[str, Any] | None) -> bool:
    normalized = dict(classification or {})
    if str(normalized.get("workflow_scope") or "").strip().lower() != "team_mode":
        return False
    if not bool(normalized.get("execution_kickoff_intent")):
        return False
    execution_mode = _normalize_execution_mode(normalized.get("execution_mode"))
    return execution_mode in {"setup_then_kickoff", "kickoff_only"}
