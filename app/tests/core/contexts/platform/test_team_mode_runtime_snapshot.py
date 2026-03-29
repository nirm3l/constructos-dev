from plugins.team_mode.runtime_snapshot import _task_runtime_state


def test_completed_task_is_not_runtime_blocked_by_dependency_gate() -> None:
    runtime_state, blocker_reason, blocker_code, runnable = _task_runtime_state(
        task={
            "role": "Developer",
            "semantic_status": "completed",
            "automation_state": "idle",
            "has_instruction": True,
            "dispatch_ready": True,
        },
        dependency_ready=False,
        dependency_reason="waiting for dependency",
    )

    assert runtime_state == "waiting"
    assert blocker_reason is None
    assert blocker_code is None
    assert runnable is False
