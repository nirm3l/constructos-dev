from plugins.team_mode.workflow_orchestrator import plan_kickoff_targets, plan_team_mode_dispatch


def _task(task_id: str, role: str, status: str, instruction: str = "do work") -> dict[str, str]:
    return {
        "id": task_id,
        "role": role,
        "status": status,
        "instruction": instruction,
        "scheduled_instruction": "",
    }


def test_plan_kickoff_targets_lead_first_with_parallel_limit():
    tasks = [
        _task("lead-1", "Lead", "Lead"),
        _task("dev-1", "Developer", "Dev"),
        _task("qa-1", "QA", "QA"),
    ]

    plan = plan_kickoff_targets(tasks, max_parallel_dispatch=2)

    assert plan["ok"] is True
    assert plan["kickoff_task_ids"] == ["lead-1"]
    by_role = plan["kickoff_task_ids_by_role"]
    assert by_role["Lead"] == ["lead-1"]
    assert by_role["Developer"] == []
    assert by_role["QA"] == []


def test_plan_kickoff_targets_blocks_when_no_runnable_lead():
    tasks = [
        _task("dev-1", "Developer", "Dev"),
        _task("qa-1", "QA", "QA"),
    ]

    plan = plan_kickoff_targets(tasks, max_parallel_dispatch=3)

    assert plan["ok"] is False
    assert plan["kickoff_task_ids"] == []
    assert any("no Team Mode Lead task exists" in reason for reason in plan["blocked_reasons"])


def test_plan_team_mode_dispatch_prioritizes_high_priority_developers_and_spreads_slots():
    tasks = [
        {
            "id": "dev-low-a",
            "role": "Developer",
            "status": "Dev",
            "instruction": "implement low",
            "scheduled_instruction": "",
            "priority": "Low",
            "automation_state": "idle",
            "assigned_agent_code": "dev-a",
            "dispatch_ready": True,
        },
        {
            "id": "dev-high-a",
            "role": "Developer",
            "status": "Dev",
            "instruction": "implement high a",
            "scheduled_instruction": "",
            "priority": "High",
            "automation_state": "idle",
            "assigned_agent_code": "dev-a",
            "dispatch_ready": True,
        },
        {
            "id": "dev-high-b",
            "role": "Developer",
            "status": "Dev",
            "instruction": "implement high b",
            "scheduled_instruction": "",
            "priority": "High",
            "automation_state": "idle",
            "assigned_agent_code": "dev-b",
            "dispatch_ready": True,
        },
        {
            "id": "dev-running-c",
            "role": "Developer",
            "status": "Dev",
            "instruction": "already running",
            "scheduled_instruction": "",
            "priority": "High",
            "automation_state": "running",
            "assigned_agent_code": "dev-c",
            "dispatch_ready": True,
        },
    ]

    plan = plan_team_mode_dispatch(tasks, max_parallel_dispatch=3)

    assert plan["ok"] is True
    assert plan["mode"] == "developer_dispatch"
    assert plan["queue_task_ids"] == ["dev-high-a", "dev-high-b"]
    assert plan["selected_by_role"]["Developer"] == ["dev-high-a", "dev-high-b"]
    counts = plan["counts"]
    assert counts["busy_total"] == 1
    assert counts["available_slots"] == 2


def test_plan_team_mode_dispatch_defers_qa_until_developer_capacity_is_filled():
    tasks = [
        {
            "id": "dev-med",
            "role": "Developer",
            "status": "Dev",
            "instruction": "implement medium",
            "scheduled_instruction": "",
            "priority": "Med",
            "automation_state": "idle",
            "assigned_agent_code": "dev-a",
            "dispatch_ready": True,
        },
        {
            "id": "qa-ready",
            "role": "QA",
            "status": "QA",
            "instruction": "validate release",
            "scheduled_instruction": "",
            "priority": "High",
            "automation_state": "idle",
            "assigned_agent_code": "qa-a",
            "dispatch_ready": True,
        },
        {
            "id": "qa-not-ready",
            "role": "QA",
            "status": "QA",
            "instruction": "validate blocked release",
            "scheduled_instruction": "",
            "priority": "High",
            "automation_state": "idle",
            "assigned_agent_code": "qa-b",
            "dispatch_ready": False,
        },
    ]

    plan = plan_team_mode_dispatch(tasks, max_parallel_dispatch=2)

    assert plan["ok"] is True
    assert plan["queue_task_ids"] == ["dev-med", "qa-ready"]
    assert plan["selected_by_role"]["Developer"] == ["dev-med"]
    assert plan["selected_by_role"]["QA"] == ["qa-ready"]
