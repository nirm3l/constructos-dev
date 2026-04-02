from __future__ import annotations

import json
from typing import Any

from shared.models import TeamModeExecutionSession
from shared.serializers import to_iso_utc

from .session_serializers import serialize_provider_neutral_session


def _load_json_array(raw: str | None) -> list[Any]:
    try:
        parsed = json.loads(str(raw or "[]"))
    except Exception:
        return []
    return list(parsed) if isinstance(parsed, list) else []


def _load_json_object(raw: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(str(raw or "{}"))
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _session_payload_from_row(session: TeamModeExecutionSession) -> dict[str, Any]:
    return {
        "id": str(getattr(session, "id", "") or "").strip(),
        "workspace_id": str(getattr(session, "workspace_id", "") or "").strip(),
        "project_id": str(getattr(session, "project_id", "") or "").strip(),
        "initiated_by": str(getattr(session, "initiated_by", "") or "").strip(),
        "command_id": str(getattr(session, "command_id", "") or "").strip() or None,
        "trigger": str(getattr(session, "trigger", "") or "").strip(),
        "status": str(getattr(session, "status", "") or "").strip(),
        "phase": str(getattr(session, "phase", "") or "").strip(),
        "phase_history": _load_json_array(getattr(session, "phase_history_json", "[]")),
        "queued_task_ids": _load_json_array(getattr(session, "queued_task_ids_json", "[]")),
        "blocked_reasons": _load_json_array(getattr(session, "blocked_reasons_json", "[]")),
        "summary": _load_json_object(getattr(session, "run_summary_json", "{}")),
        "started_at": to_iso_utc(getattr(session, "started_at", None)),
        "completed_at": to_iso_utc(getattr(session, "completed_at", None)),
        "updated_at": to_iso_utc(getattr(session, "updated_at", None)),
        "created_at": to_iso_utc(getattr(session, "created_at", None)),
    }


def build_automation_session_log_from_row(*, session: TeamModeExecutionSession) -> dict[str, Any]:
    payload = _session_payload_from_row(session)
    return serialize_provider_neutral_session(session_payload=payload)


def build_automation_session_log(*, session_payload: dict[str, Any]) -> dict[str, Any]:
    return serialize_provider_neutral_session(session_payload=dict(session_payload or {}))

