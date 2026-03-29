from __future__ import annotations

from plugins.team_mode.workflow_orchestrator import plan_kickoff_targets


def _task(
    *,
    task_id: str,
    role: str,
    status: str = "To Do",
    instruction: str = "run",
    priority: str = "Med",
) -> dict:
    return {
        "id": task_id,
        "role": role,
        "status": status,
        "instruction": instruction,
        "scheduled_instruction": "",
        "priority": priority,
        "task_relationships": [],
    }


def test_kickoff_targets_prioritize_developer_tasks_over_lead() -> None:
    tasks = [
        _task(task_id="dev-1", role="Developer"),
        _task(task_id="dev-2", role="Developer"),
        _task(task_id="lead-1", role="Lead"),
    ]

    payload = plan_kickoff_targets(tasks, max_parallel_dispatch=3)

    assert payload["ok"] is True
    assert payload["kickoff_task_ids"] == ["dev-1", "dev-2"]
    by_role = payload["kickoff_task_ids_by_role"]
    assert by_role["Developer"] == ["dev-1", "dev-2"]
    assert by_role["Lead"] == ["lead-1"]


def test_kickoff_targets_fall_back_to_lead_when_no_developer_candidates() -> None:
    tasks = [
        _task(task_id="dev-completed", role="Developer", status="Completed"),
        _task(task_id="lead-1", role="Lead", status="In Progress"),
    ]

    payload = plan_kickoff_targets(tasks, max_parallel_dispatch=2)

    assert payload["ok"] is True
    assert payload["kickoff_task_ids"] == ["lead-1"]
    by_role = payload["kickoff_task_ids_by_role"]
    assert by_role["Developer"] == []
    assert by_role["Lead"] == ["lead-1"]
