from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared.serializers import to_iso_utc


def _now_iso_utc() -> str:
    return to_iso_utc(datetime.now(timezone.utc))


def _normalize_provider_context(summary: dict[str, Any]) -> dict[str, Any]:
    provider = str(summary.get("provider") or "").strip().lower() or None
    model = str(summary.get("model") or "").strip() or None
    reasoning_effort = str(summary.get("reasoning_effort") or "").strip().lower() or None
    if provider is None:
        provider = str(summary.get("execution_provider") or "").strip().lower() or None
    if model is None:
        model = str(summary.get("execution_model") or "").strip() or None
    if reasoning_effort is None:
        reasoning_effort = str(summary.get("execution_reasoning_effort") or "").strip().lower() or None
    if (provider is None or model is None or reasoning_effort is None) and isinstance(summary.get("verify_fix_attempts_detail"), list):
        for attempt in summary.get("verify_fix_attempts_detail") or []:
            if not isinstance(attempt, dict):
                continue
            if provider is None:
                provider = str(attempt.get("provider") or "").strip().lower() or None
            if model is None:
                model = str(attempt.get("model") or "").strip() or None
            if reasoning_effort is None:
                reasoning_effort = str(attempt.get("reasoning_effort") or "").strip().lower() or None
            if provider is not None and model is not None and reasoning_effort is not None:
                break
    return {
        "provider": provider,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }


def build_provider_neutral_transcript(*, session_payload: dict[str, Any]) -> list[dict[str, Any]]:
    phase_history = list(session_payload.get("phase_history") or [])
    queued_task_ids = [str(item or "").strip() for item in list(session_payload.get("queued_task_ids") or []) if str(item or "").strip()]
    blocked_reasons = [str(item or "").strip() for item in list(session_payload.get("blocked_reasons") or []) if str(item or "").strip()]
    summary = dict(session_payload.get("summary") or {})
    transcript: list[dict[str, Any]] = []

    for index, item in enumerate(phase_history, start=1):
        phase = str((item or {}).get("phase") or "").strip() or "unknown"
        at = str((item or {}).get("entered_at") or "").strip() or _now_iso_utc()
        reason = str((item or {}).get("reason") or "").strip() or None
        transcript.append(
            {
                "event_type": "phase",
                "index": index,
                "at": at,
                "phase": phase,
                "reason": reason,
            }
        )

    if queued_task_ids:
        transcript.append(
            {
                "event_type": "queue",
                "index": len(transcript) + 1,
                "at": str(session_payload.get("completed_at") or session_payload.get("updated_at") or _now_iso_utc()),
                "queued_task_ids": queued_task_ids,
            }
        )
    if blocked_reasons:
        transcript.append(
            {
                "event_type": "blocked",
                "index": len(transcript) + 1,
                "at": str(session_payload.get("completed_at") or session_payload.get("updated_at") or _now_iso_utc()),
                "blocked_reasons": blocked_reasons,
            }
        )
    verify_fix_attempts = summary.get("verify_fix_attempts_detail")
    if isinstance(verify_fix_attempts, list) and verify_fix_attempts:
        transcript.append(
            {
                "event_type": "verify_fix",
                "index": len(transcript) + 1,
                "at": str(session_payload.get("completed_at") or session_payload.get("updated_at") or _now_iso_utc()),
                "ok": bool(summary.get("verify_fix_ok")),
                "attempt_count": int(summary.get("verify_fix_attempts") or len(verify_fix_attempts)),
                "fix_attempt_count": int(summary.get("verify_fix_fix_attempt_count") or 0),
                "runner_error_count": int(summary.get("verify_fix_runner_error_count") or 0),
                "attempts": verify_fix_attempts,
            }
        )
    if summary:
        transcript.append(
            {
                "event_type": "summary",
                "index": len(transcript) + 1,
                "at": str(session_payload.get("completed_at") or session_payload.get("updated_at") or _now_iso_utc()),
                "payload": summary,
            }
        )

    return transcript


def serialize_provider_neutral_session(*, session_payload: dict[str, Any]) -> dict[str, Any]:
    summary = dict(session_payload.get("summary") or {})
    return {
        "id": str(session_payload.get("id") or "").strip(),
        "workspace_id": str(session_payload.get("workspace_id") or "").strip(),
        "project_id": str(session_payload.get("project_id") or "").strip(),
        "command_id": str(session_payload.get("command_id") or "").strip() or None,
        "trigger": str(session_payload.get("trigger") or "").strip() or None,
        "status": str(session_payload.get("status") or "").strip() or "unknown",
        "phase": str(session_payload.get("phase") or "").strip() or None,
        "started_at": str(session_payload.get("started_at") or "").strip() or None,
        "completed_at": str(session_payload.get("completed_at") or "").strip() or None,
        "updated_at": str(session_payload.get("updated_at") or "").strip() or None,
        "provider_context": _normalize_provider_context(summary),
        "lineage": {
            "source": "team_mode_execution_session",
            "initiated_by": str(session_payload.get("initiated_by") or "").strip() or None,
        },
        "transcript": build_provider_neutral_transcript(session_payload=session_payload),
    }
