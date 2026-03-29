from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.models import TeamModeExecutionSession
from shared.serializers import to_iso_utc


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


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


def create_team_mode_execution_session(
    *,
    db: Session,
    workspace_id: str,
    project_id: str,
    initiated_by: str,
    command_id: str | None,
    trigger: str = "kickoff",
    phase: str = "team-exec",
    summary: dict[str, Any] | None = None,
) -> TeamModeExecutionSession:
    normalized_trigger = str(trigger or "kickoff").strip() or "kickoff"
    normalized_phase = str(phase or "team-exec").strip() or "team-exec"
    now = _now_utc()
    phase_history = [
        {
            "phase": normalized_phase,
            "entered_at": to_iso_utc(now),
            "reason": "session-created",
        }
    ]
    row = TeamModeExecutionSession(
        workspace_id=str(workspace_id or "").strip(),
        project_id=str(project_id or "").strip(),
        initiated_by=str(initiated_by or "").strip(),
        command_id=str(command_id or "").strip() or None,
        trigger=normalized_trigger,
        status="active",
        phase=normalized_phase,
        phase_history_json=json.dumps(phase_history),
        run_summary_json=json.dumps(dict(summary or {})),
        started_at=now,
    )
    db.add(row)
    db.flush()
    return row


def advance_team_mode_execution_phase(
    *,
    session: TeamModeExecutionSession,
    phase: str,
    reason: str | None = None,
) -> None:
    normalized_phase = str(phase or "").strip()
    if not normalized_phase:
        return
    history = _load_json_array(getattr(session, "phase_history_json", "[]"))
    history.append(
        {
            "phase": normalized_phase,
            "entered_at": to_iso_utc(_now_utc()),
            "reason": str(reason or "").strip() or None,
        }
    )
    session.phase = normalized_phase
    session.phase_history_json = json.dumps(history)
    session.updated_at = _now_utc()


def complete_team_mode_execution_session(
    *,
    session: TeamModeExecutionSession,
    status: str,
    summary: dict[str, Any] | None = None,
    queued_task_ids: list[str] | None = None,
    blocked_reasons: list[str] | None = None,
) -> None:
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"completed", "failed", "cancelled"}:
        normalized_status = "failed"
    terminal_phase = "complete" if normalized_status == "completed" else "failed"
    advance_team_mode_execution_phase(
        session=session,
        phase=terminal_phase,
        reason=f"session-{normalized_status}",
    )
    session.status = normalized_status
    session.queued_task_ids_json = json.dumps(
        [str(item or "").strip() for item in (queued_task_ids or []) if str(item or "").strip()]
    )
    session.blocked_reasons_json = json.dumps(
        [str(item or "").strip() for item in (blocked_reasons or []) if str(item or "").strip()]
    )
    session.run_summary_json = json.dumps(dict(summary or {}))
    session.completed_at = _now_utc()
    session.updated_at = _now_utc()


def serialize_team_mode_execution_session(session: TeamModeExecutionSession | None) -> dict[str, Any] | None:
    if session is None:
        return None
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


def get_latest_team_mode_execution_session(
    *,
    db: Session,
    project_id: str,
) -> TeamModeExecutionSession | None:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return None
    return db.execute(
        select(TeamModeExecutionSession)
        .where(TeamModeExecutionSession.project_id == normalized_project_id)
        .order_by(TeamModeExecutionSession.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
