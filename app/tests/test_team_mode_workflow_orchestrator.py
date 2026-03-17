from plugins.team_mode.workflow_orchestrator import plan_kickoff_targets, plan_team_mode_dispatch


def _task(task_id: str, role: str, status: str, instruction: str = "do work") -> dict[str, str]:
    return {
        "id": task_id,
        "role": role,
        "status": status,
        "instruction": instruction,
        "scheduled_instruction": "",
    }


def test_plan_kickoff_targets_prioritizes_runnable_implementation_work():
    tasks = [
        _task("lead-1", "Lead", "In Progress"),
        _task("dev-1", "Developer", "To do"),
        _task("qa-1", "QA", "In Progress"),
    ]

    plan = plan_kickoff_targets(tasks, max_parallel_dispatch=2)

    assert plan["ok"] is True
    assert plan["kickoff_task_ids"] == ["dev-1", "lead-1"]
    assert plan["kickoff_task_ids_by_role"]["Developer"] == ["dev-1"]
    assert plan["kickoff_task_ids_by_role"]["Lead"] == ["lead-1"]


def test_plan_kickoff_targets_allows_direct_implementation_start_without_lead_task():
    tasks = [
        _task("dev-1", "Developer", "To do"),
        _task("qa-1", "QA", "In Progress"),
    ]

    plan = plan_kickoff_targets(tasks, max_parallel_dispatch=3)

    assert plan["ok"] is True
    assert plan["kickoff_task_ids"] == ["dev-1"]
    assert plan["kickoff_task_ids_by_role"]["Developer"] == ["dev-1"]


def test_plan_team_mode_dispatch_prioritizes_high_priority_developers_and_spreads_slots():
    tasks = [
        {
            "id": "dev-low-a",
            "role": "Developer",
            "status": "To do",
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
            "status": "In Progress",
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
            "status": "Blocked",
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
            "status": "In Progress",
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
    assert plan["counts"]["busy_total"] == 1
    assert plan["counts"]["available_slots"] == 2


def test_plan_team_mode_dispatch_allows_qa_after_deploy_cycle_is_active():
    tasks = [
        {
            "id": "dev-med",
            "role": "Developer",
            "status": "To do",
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
            "status": "In Progress",
            "instruction": "validate release",
            "scheduled_instruction": "",
            "priority": "High",
            "automation_state": "idle",
            "assigned_agent_code": "qa-a",
            "dispatch_ready": True,
        },
    ]

    plan = plan_team_mode_dispatch(tasks, max_parallel_dispatch=2)

    assert plan["ok"] is True
    assert plan["queue_task_ids"] == ["dev-med", "qa-ready"]
    assert plan["selected_by_role"]["Developer"] == ["dev-med"]
    assert plan["selected_by_role"]["QA"] == ["qa-ready"]


def test_plan_kickoff_targets_skips_tasks_with_unsatisfied_dependencies():
    tasks = [
        {
            "id": "foundation",
            "role": "Developer",
            "status": "To Do",
            "instruction": "Build the shared core.",
            "scheduled_instruction": "",
            "priority": "High",
            "task_relationships": [],
        },
        {
            "id": "gameplay",
            "role": "Developer",
            "status": "To Do",
            "instruction": "Build gameplay on top of the shared core.",
            "scheduled_instruction": "",
            "priority": "High",
            "task_relationships": [
                {"kind": "depends_on", "task_ids": ["foundation"], "statuses": ["merged"]},
            ],
        },
    ]

    plan = plan_kickoff_targets(tasks, max_parallel_dispatch=2)

    assert plan["ok"] is True
    assert plan["kickoff_task_ids"] == ["foundation"]
    assert plan["kickoff_task_ids_by_role"]["Developer"] == ["foundation"]


def test_plan_team_mode_dispatch_respects_dependency_graph_before_priority():
    tasks = [
        {
            "id": "foundation",
            "role": "Developer",
            "status": "To Do",
            "instruction": "Build the shared Tetris engine.",
            "scheduled_instruction": "",
            "priority": "Med",
            "automation_state": "idle",
            "assigned_agent_code": "dev-a",
            "dispatch_ready": True,
            "task_relationships": [],
        },
        {
            "id": "gameplay",
            "role": "Developer",
            "status": "To Do",
            "instruction": "Build gameplay and scoring on top of the engine.",
            "scheduled_instruction": "",
            "priority": "High",
            "automation_state": "idle",
            "assigned_agent_code": "dev-b",
            "dispatch_ready": True,
            "task_relationships": [
                {"kind": "depends_on", "task_ids": ["foundation"], "statuses": ["merged"]},
            ],
        },
        {
            "id": "ui-shell",
            "role": "Developer",
            "status": "To Do",
            "instruction": "Build the independent UI shell.",
            "scheduled_instruction": "",
            "priority": "Low",
            "automation_state": "idle",
            "assigned_agent_code": "dev-c",
            "dispatch_ready": True,
            "task_relationships": [],
        },
    ]

    plan = plan_team_mode_dispatch(tasks, max_parallel_dispatch=2)

    assert plan["ok"] is True
    assert plan["mode"] == "developer_dispatch"
    assert plan["queue_task_ids"] == ["foundation", "ui-shell"]
    assert plan["selected_by_role"]["Developer"] == ["foundation", "ui-shell"]
