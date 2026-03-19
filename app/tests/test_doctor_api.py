import os
from importlib import reload
from pathlib import Path

from fastapi.testclient import TestClient


def build_client(tmp_path: Path) -> TestClient:
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ["AGENT_CODEX_WORKDIR"] = str(tmp_path / "workspace")
    os.environ["AGENT_RUNNER_ENABLED"] = "false"
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    import main

    main = reload(main)
    main.bootstrap_data()
    client = TestClient(main.app)
    login = client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'})
    assert login.status_code == 200
    return client


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
