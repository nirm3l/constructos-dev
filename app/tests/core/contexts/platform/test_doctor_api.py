from pathlib import Path

from fastapi.testclient import TestClient

from tests.core.support.runtime import build_client as build_runtime_client


def build_client(tmp_path: Path) -> TestClient:
    return build_runtime_client(
        tmp_path,
        extra_env={
            "AGENT_CODEX_WORKDIR": str(tmp_path / "workspace"),
            "AGENT_RUNNER_ENABLED": "false",
        },
    )


def test_workspace_doctor_status_seed_and_run(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    workspace_id = bootstrap['workspaces'][0]['id']

    initial = client.get(f'/api/workspaces/{workspace_id}/doctor')
    assert initial.status_code == 200
    initial_payload = initial.json()
    assert initial_payload['plugin_key'] == 'doctor'
    assert initial_payload['supported'] is True
    assert initial_payload['seeded'] is False

    seeded = client.post(f'/api/workspaces/{workspace_id}/doctor/seed')
    assert seeded.status_code == 200
    seeded_payload = seeded.json()
    assert seeded_payload['seeded'] is True
    assert seeded_payload['project']['id']
    assert seeded_payload['checks']['team_mode_enabled'] is True
    assert seeded_payload['checks']['git_delivery_enabled'] is True
    assert seeded_payload['checks']['seeded_team_task_count'] >= 4

    ran = client.post(f'/api/workspaces/{workspace_id}/doctor/run')
    assert ran.status_code == 200
    run_payload = ran.json()
    run = run_payload['run']
    assert run['project_id'] == seeded_payload['project']['id']
    assert run['status'] == 'passed'
    summary = run['summary']
    counts = summary.get('counts') or {}
    assert int(counts.get('failed') or 0) == 0
    check_by_id = {
        str(item.get('id') or '').strip(): item
        for item in (summary.get('checks') or [])
        if isinstance(item, dict)
    }
    assert check_by_id['project_present']['status'] == 'passed'
    assert check_by_id['team_mode_enabled']['status'] == 'passed'
    assert check_by_id['git_delivery_enabled']['status'] == 'passed'
    assert check_by_id['seeded_team_tasks']['status'] == 'passed'
    assert check_by_id['team_mode_workflow']['status'] == 'passed'
    assert check_by_id['delivery_workflow']['status'] == 'passed'
    assert check_by_id['repo_context_present']['status'] == 'passed'
    assert check_by_id['git_contract_ok']['status'] == 'passed'
    assert check_by_id['compose_manifest_present']['status'] == 'passed'
    assert check_by_id['lead_deploy_decision_evidence_present']['status'] == 'passed'
    assert check_by_id['deploy_execution_evidence_present']['status'] == 'passed'
    assert check_by_id['qa_handoff_current_cycle_ok']['status'] == 'passed'
    assert check_by_id['qa_has_verifiable_artifacts']['status'] == 'passed'

    refreshed = client.get(f'/api/workspaces/{workspace_id}/doctor')
    assert refreshed.status_code == 200
    refreshed_payload = refreshed.json()
    assert refreshed_payload['last_run'] is not None
    assert refreshed_payload['last_run_status'] == 'passed'
    assert len(refreshed_payload['recent_runs']) >= 1

    reset = client.post(f'/api/workspaces/{workspace_id}/doctor/reset')
    assert reset.status_code == 200
    reset_payload = reset.json()
    assert reset_payload['seeded'] is True
    assert reset_payload['project'] is not None
    assert reset_payload['project']['id'] == seeded_payload['project']['id']
    assert reset_payload['last_run_status'] == 'reset'


def test_workspace_doctor_seed_and_run_accept_long_command_id(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    workspace_id = bootstrap['workspaces'][0]['id']

    from shared.models import CommandExecution, SessionLocal

    seed_command_id = "doctor-seed-" + ("x" * 52)
    run_command_id = "doctor-run-" + ("y" * 53)

    seeded = client.post(
        f'/api/workspaces/{workspace_id}/doctor/seed',
        headers={"X-Command-Id": seed_command_id},
    )
    assert seeded.status_code == 200
    assert seeded.json()['seeded'] is True

    ran = client.post(
        f'/api/workspaces/{workspace_id}/doctor/run',
        headers={"X-Command-Id": run_command_id},
    )
    assert ran.status_code == 200
    assert ran.json()['run']['status'] in {'passed', 'failed'}

    with SessionLocal() as db:
        command_rows = (
            db.query(CommandExecution)
            .filter(CommandExecution.command_id.like('doctor-%'))
            .all()
        )
    assert command_rows
    assert all(len(str(row.command_id or "")) <= 64 for row in command_rows)


def test_project_checks_verify_exposes_team_mode_runtime_focus_summary(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    workspace_id = bootstrap['workspaces'][0]['id']

    seeded = client.post(f'/api/workspaces/{workspace_id}/doctor/seed')
    assert seeded.status_code == 200
    seeded_payload = seeded.json()
    project_id = seeded_payload['project']['id']

    checks = client.get(f'/api/projects/{project_id}/checks/verify')
    assert checks.status_code == 200
    payload = checks.json()

    runtime = payload.get('team_mode_runtime') or {}
    execution_session = payload.get('team_mode_execution_session')
    summary = runtime.get('summary') or {}
    focus = summary.get('focus') or {}
    usage_totals = summary.get('usage_totals') or {}

    assert isinstance(focus.get('now_task_ids'), list)
    assert isinstance(focus.get('next_task_ids'), list)
    assert isinstance(focus.get('blocked_task_ids'), list)
    assert isinstance(focus.get('now_total'), int)
    assert isinstance(focus.get('next_total'), int)
    assert isinstance(focus.get('blocked_total'), int)
    assert isinstance(usage_totals.get('tasks_with_usage', 0), int)
    assert isinstance(usage_totals.get('input_tokens', 0), int)
    assert isinstance(usage_totals.get('output_tokens', 0), int)
    assert isinstance(usage_totals.get('cost_usd', 0.0), (int, float))

    assert focus['now_total'] >= len(focus['now_task_ids'])
    assert focus['next_total'] >= len(focus['next_task_ids'])
    assert focus['blocked_total'] >= len(focus['blocked_task_ids'])
    now_ids = set(str(item or '').strip() for item in focus['now_task_ids'] if str(item or '').strip())
    next_ids = set(str(item or '').strip() for item in focus['next_task_ids'] if str(item or '').strip())
    blocked_ids = set(str(item or '').strip() for item in focus['blocked_task_ids'] if str(item or '').strip())
    assert now_ids.isdisjoint(next_ids)
    assert now_ids.isdisjoint(blocked_ids)
    assert next_ids.isdisjoint(blocked_ids)

    tasks = runtime.get('tasks') or []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        runtime_state = str(task.get('runtime_state') or '').strip()
        if runtime_state in {'blocked', 'missing_instruction'}:
            blocker_code = str(task.get('blocker_code') or '').strip()
            assert blocker_code
    if execution_session is not None:
        assert isinstance(execution_session, dict)
        assert isinstance(execution_session.get('id'), str)
        assert isinstance(execution_session.get('status'), str)
        assert isinstance(execution_session.get('phase_history'), list)
        session_summary = execution_session.get('summary')
        if session_summary is not None:
            assert isinstance(session_summary, dict)
            assert isinstance(session_summary.get('verify_fix_attempts'), int)
            assert isinstance(session_summary.get('verify_fix_fix_attempt_count'), int)
