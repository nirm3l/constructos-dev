from pathlib import Path

from tests.core.support.runtime import bootstrap_app_runtime


def test_team_mode_execution_session_roundtrip(tmp_path: Path):
    bootstrap_app_runtime(
        tmp_path,
        extra_env={
            "AGENT_CODEX_WORKDIR": str(tmp_path / "workspace"),
            "AGENT_RUNNER_ENABLED": "false",
        },
    )

    from plugins.team_mode.execution_sessions import (
        complete_team_mode_execution_session,
        create_team_mode_execution_session,
        get_latest_team_mode_execution_session,
        serialize_team_mode_execution_session,
    )
    from shared.models import SessionLocal

    with SessionLocal() as db:
        session = create_team_mode_execution_session(
            db=db,
            workspace_id="ws-1",
            project_id="project-1",
            initiated_by="user-1",
            command_id="cmd-1",
            trigger="kickoff",
            phase="team-exec",
            summary={"parallel_limit": 3},
        )
        complete_team_mode_execution_session(
            session=session,
            status="completed",
            summary={"ok": True, "summary": "Kickoff dispatched"},
            queued_task_ids=["task-1", "task-2"],
            blocked_reasons=[],
        )
        db.commit()

        latest = get_latest_team_mode_execution_session(db=db, project_id="project-1")
        payload = serialize_team_mode_execution_session(latest)

    assert payload is not None
    assert payload["project_id"] == "project-1"
    assert payload["status"] == "completed"
    assert payload["phase"] == "complete"
    assert payload["queued_task_ids"] == ["task-1", "task-2"]
    assert isinstance(payload["phase_history"], list)
    assert len(payload["phase_history"]) >= 2
