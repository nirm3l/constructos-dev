from __future__ import annotations

from features.agents.automation_session_logs import build_automation_session_log


def test_build_automation_session_log_provider_neutral_shape():
    payload = {
        "id": "session-1",
        "workspace_id": "workspace-1",
        "project_id": "project-1",
        "initiated_by": "user-1",
        "command_id": "cmd-1",
        "trigger": "kickoff",
        "status": "completed",
        "phase": "complete",
        "phase_history": [
            {"phase": "team-exec", "entered_at": "2026-04-02T10:00:00Z", "reason": "session-created"},
            {"phase": "team-verify", "entered_at": "2026-04-02T10:00:10Z", "reason": "kickoff-dispatched"},
            {"phase": "complete", "entered_at": "2026-04-02T10:00:20Z", "reason": "session-completed"},
        ],
        "queued_task_ids": ["task-1", "task-2"],
        "blocked_reasons": [],
        "summary": {
            "ok": True,
            "summary": "Kickoff dispatched.",
            "comment": "Developer task became active.",
            "provider": "codex",
            "model": "gpt-5",
            "reasoning_effort": "high",
            "verify_fix_ok": True,
            "verify_fix_attempts": 1,
            "verify_fix_fix_attempt_count": 0,
            "verify_fix_runner_error_count": 0,
            "verify_fix_attempts_detail": [
                {
                    "attempt": 1,
                    "runner_status": "ok",
                    "runner_error": None,
                    "developer_dispatch_confirmed": True,
                    "developer_task_count": 1,
                    "developer_active_count": 1,
                    "developer_idle_count": 0,
                    "provider": "codex",
                    "model": "gpt-5",
                    "reasoning_effort": "high",
                }
            ],
        },
        "started_at": "2026-04-02T10:00:00Z",
        "completed_at": "2026-04-02T10:00:20Z",
        "updated_at": "2026-04-02T10:00:20Z",
    }

    log = build_automation_session_log(session_payload=payload)
    assert isinstance(log, dict)
    assert log.get("id") == "session-1"
    assert log.get("workspace_id") == "workspace-1"
    assert log.get("project_id") == "project-1"
    assert log.get("trigger") == "kickoff"
    assert log.get("status") == "completed"
    assert isinstance(log.get("provider_context"), dict)
    assert log.get("provider_context", {}).get("provider") == "codex"
    assert log.get("provider_context", {}).get("model") == "gpt-5"
    assert log.get("provider_context", {}).get("reasoning_effort") == "high"
    assert isinstance(log.get("transcript"), list)
    assert len(log.get("transcript") or []) >= 4
    event_types = [str(item.get("event_type") or "") for item in (log.get("transcript") or [])]
    assert "phase" in event_types
    assert "queue" in event_types
    assert "verify_fix" in event_types
    assert "summary" in event_types
    verify_fix_event = next(
        (
            item
            for item in (log.get("transcript") or [])
            if isinstance(item, dict) and str(item.get("event_type") or "").strip() == "verify_fix"
        ),
        None,
    )
    assert isinstance(verify_fix_event, dict)
    assert isinstance(verify_fix_event.get("attempt_count"), int)
    assert isinstance(verify_fix_event.get("fix_attempt_count"), int)
    assert isinstance(verify_fix_event.get("runner_error_count"), int)
    assert isinstance(verify_fix_event.get("attempts"), list)


def test_build_automation_session_log_legacy_provider_context_fallback():
    payload = {
        "id": "legacy-session-1",
        "workspace_id": "workspace-1",
        "project_id": "project-1",
        "initiated_by": "user-1",
        "command_id": "cmd-legacy-1",
        "trigger": "kickoff",
        "status": "completed",
        "phase": "complete",
        "phase_history": [
            {"phase": "team-exec", "entered_at": "2026-04-02T10:00:00Z", "reason": "session-created"},
            {"phase": "complete", "entered_at": "2026-04-02T10:00:20Z", "reason": "session-completed"},
        ],
        "queued_task_ids": ["task-1"],
        "blocked_reasons": [],
        "summary": {
            "ok": True,
            "summary": "Legacy kickoff dispatched.",
            "comment": "Legacy provider fields only.",
            "execution_provider": "codex",
            "execution_model": "gpt-5",
            "execution_reasoning_effort": "high",
        },
        "started_at": "2026-04-02T10:00:00Z",
        "completed_at": "2026-04-02T10:00:20Z",
        "updated_at": "2026-04-02T10:00:20Z",
    }

    log = build_automation_session_log(session_payload=payload)
    provider_context = log.get("provider_context") or {}
    assert provider_context.get("provider") == "codex"
    assert provider_context.get("model") == "gpt-5"
    assert provider_context.get("reasoning_effort") == "high"
