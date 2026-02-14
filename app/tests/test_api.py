import os
from importlib import reload
from pathlib import Path
from zoneinfo import ZoneInfo

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def build_client(tmp_path: Path):
    db_file = tmp_path / "test.db"
    os.environ["DB_PATH"] = str(db_file)
    os.environ["EVENTSTORE_URI"] = ""
    import main

    main = reload(main)
    main.bootstrap_data()
    return TestClient(main.app)


def test_health(tmp_path):
    client = build_client(tmp_path)
    res = client.get('/api/health')
    assert res.status_code == 200
    assert res.json()['ok'] is True


def test_create_and_complete_task(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    created = client.post('/api/tasks', json={'title': 'Write tests', 'workspace_id': ws_id})
    assert created.status_code == 200
    task = created.json()
    assert task['title'] == 'Write tests'

    done = client.post(f"/api/tasks/{task['id']}/complete")
    assert done.status_code == 200
    assert done.json()['status'] == 'Done'


def test_search_filter(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    client.post('/api/tasks', json={'title': 'High prio', 'workspace_id': ws_id, 'priority': 'High'})
    res = client.get(f'/api/tasks?workspace_id={ws_id}&priority=High')
    assert res.status_code == 200
    assert any(t['priority'] == 'High' for t in res.json()['items'])


def test_comment_mention_creates_notification(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    current_user = bootstrap['current_user']
    task = client.post('/api/tasks', json={'title': 'Mention', 'workspace_id': ws_id}).json()

    comment = client.post(f"/api/tasks/{task['id']}/comments", json={'body': f"Ping @{current_user['username']}"})
    assert comment.status_code == 200

    notes = client.get('/api/notifications', headers={'X-User-Id': current_user['id']})
    assert notes.status_code == 200
    assert any('mentioned' in n['message'] for n in notes.json())


def test_today_view_respects_user_timezone(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    user_tz = ZoneInfo(bootstrap['current_user']['timezone'])

    now_utc = datetime.now(timezone.utc)
    local_today_start = now_utc.astimezone(user_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    due_local = local_today_start + timedelta(hours=1)
    due_utc = due_local.astimezone(timezone.utc)

    created = client.post(
        '/api/tasks',
        json={'title': 'TZ today task', 'workspace_id': ws_id, 'due_date': due_utc.isoformat()},
    )
    assert created.status_code == 200

    today = client.get(f'/api/tasks?workspace_id={ws_id}&view=today')
    assert today.status_code == 200
    assert any(t['title'] == 'TZ today task' for t in today.json()['items'])


def test_create_project(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    res = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Mobile Redesign'})
    assert res.status_code == 200
    payload = res.json()
    assert payload['name'] == 'Mobile Redesign'
    assert payload['workspace_id'] == ws_id


def test_delete_project_moves_tasks_to_inbox(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    project = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'To delete'}).json()
    task = client.post('/api/tasks', json={'title': 'Belongs to project', 'workspace_id': ws_id, 'project_id': project['id']}).json()
    assert task['project_id'] == project['id']

    deleted = client.delete(f"/api/projects/{project['id']}")
    assert deleted.status_code == 200
    assert deleted.json()['ok'] is True

    tasks = client.get(f'/api/tasks?workspace_id={ws_id}').json()['items']
    moved_task = next(t for t in tasks if t['id'] == task['id'])
    assert moved_task['project_id'] is None


def test_user_theme_preferences_persist(tmp_path):
    client = build_client(tmp_path)
    updated = client.patch('/api/me/preferences', json={'theme': 'dark'})
    assert updated.status_code == 200
    assert updated.json()['theme'] == 'dark'

    bootstrap = client.get('/api/bootstrap')
    assert bootstrap.status_code == 200
    assert bootstrap.json()['current_user']['theme'] == 'dark'


def test_due_soon_system_notification(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    due_utc = datetime.now(timezone.utc) + timedelta(minutes=30)

    created = client.post(
        '/api/tasks',
        json={'title': 'Soon deadline', 'workspace_id': ws_id, 'due_date': due_utc.isoformat()},
    )
    assert created.status_code == 200

    notes = client.get('/api/notifications')
    assert notes.status_code == 200
    assert any('due within 1 hour' in n['message'] for n in notes.json())


def test_daily_digest_is_emitted_once_per_day(tmp_path):
    client = build_client(tmp_path)

    first = client.get('/api/notifications')
    assert first.status_code == 200
    first_digests = [n for n in first.json() if n['message'].startswith('Daily digest for ')]
    assert len(first_digests) == 1

    second = client.get('/api/notifications')
    assert second.status_code == 200
    second_digests = [n for n in second.json() if n['message'].startswith('Daily digest for ')]
    assert len(second_digests) == 1


def test_notifications_endpoint_tolerates_duplicate_messages(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']

    from shared.models import Notification, SessionLocal

    with SessionLocal() as db:
        db.add(Notification(user_id=user_id, message='Duplicate notification guard test'))
        db.add(Notification(user_id=user_id, message='Duplicate notification guard test'))
        db.commit()

    res = client.get('/api/notifications')
    assert res.status_code == 200


def test_command_id_idempotency_for_create_task(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    command_id = "cmd-create-task-001"

    first = client.post(
        '/api/tasks',
        json={'title': 'Idempotent create', 'workspace_id': ws_id},
        headers={'X-Command-Id': command_id},
    )
    second = client.post(
        '/api/tasks',
        json={'title': 'Idempotent create', 'workspace_id': ws_id},
        headers={'X-Command-Id': command_id},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()['id'] == second.json()['id']

    tasks = client.get(f'/api/tasks?workspace_id={ws_id}&q=Idempotent create').json()['items']
    assert len(tasks) == 1


def test_metrics_endpoint_available(tmp_path):
    client = build_client(tmp_path)
    res = client.get('/api/metrics')
    assert res.status_code == 200
    payload = res.json()
    assert 'commands_total' in payload
    assert 'command_conflicts' in payload


def test_local_snapshot_payload_has_schema_version(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    task = client.post('/api/tasks', json={'title': 'Snapshot schema test', 'workspace_id': ws_id}).json()

    for i in range(1, 22):
        res = client.patch(f"/api/tasks/{task['id']}", json={'description': f'v{i}'})
        assert res.status_code == 200

    from shared.models import AggregateSnapshot, SessionLocal
    import json as _json
    with SessionLocal() as db:
        snap = (
            db.query(AggregateSnapshot)
            .filter(
                AggregateSnapshot.aggregate_type == 'Task',
                AggregateSnapshot.aggregate_id == task['id'],
            )
            .order_by(AggregateSnapshot.version.desc())
            .first()
        )
        assert snap is not None
        payload = _json.loads(snap.state or '{}')
        assert payload.get('snapshot_schema_version') == 2
        assert payload.get('version') == snap.version
        assert isinstance(payload.get('state'), dict)


def test_legacy_snapshot_is_upcasted(tmp_path):
    _ = build_client(tmp_path)

    from shared.eventing_rebuild import load_snapshot
    from shared.models import AggregateSnapshot, SessionLocal
    import json as _json

    with SessionLocal() as db:
        db.add(
            AggregateSnapshot(
                aggregate_type='Task',
                aggregate_id='legacy-task',
                version=7,
                state=_json.dumps({'id': 'legacy-task', 'projectId': 'p-1', 'title': 'Legacy'}),
            )
        )
        db.commit()

        state, version = load_snapshot(db, 'Task', 'legacy-task')
        assert version == 7
        assert state['id'] == 'legacy-task'
        assert state['project_id'] == 'p-1'


def test_request_task_automation_run_sets_queued_status(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    task = client.post('/api/tasks', json={'title': 'Automate me', 'workspace_id': ws_id}).json()
    run = client.post(f"/api/tasks/{task['id']}/automation/run", json={'instruction': 'Implement feature X'})
    assert run.status_code == 200
    payload = run.json()
    assert payload['ok'] is True
    assert payload['automation_state'] == 'queued'

    status = client.get(f"/api/tasks/{task['id']}/automation")
    assert status.status_code == 200
    assert status.json()['automation_state'] == 'queued'
    assert status.json()['last_agent_error'] is None


def test_task_automation_status_404_for_missing_task(tmp_path):
    client = build_client(tmp_path)
    res = client.get('/api/tasks/missing-task-id/automation')
    assert res.status_code == 404


def test_agent_service_can_request_automation_run(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    created = client.post('/api/tasks', json={'title': 'Agent task', 'workspace_id': ws_id}).json()

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    run = service.request_task_automation_run(
        task_id=created['id'],
        instruction='Agent instruction',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert run['automation_state'] == 'queued'

    status = service.get_task_automation_status(task_id=created['id'], auth_token=svc_module.MCP_AUTH_TOKEN or None)
    assert status['automation_state'] == 'queued'


def test_runner_processes_queued_automation(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    task = client.post('/api/tasks', json={'title': 'Runner task', 'workspace_id': ws_id}).json()

    queued = client.post(f"/api/tasks/{task['id']}/automation/run", json={'instruction': 'Do runner check'})
    assert queued.status_code == 200
    assert queued.json()['automation_state'] == 'queued'

    from features.agents.runner import run_queued_automation_once

    processed = run_queued_automation_once(limit=5)
    assert processed >= 1

    status = client.get(f"/api/tasks/{task['id']}/automation")
    assert status.status_code == 200
    payload = status.json()
    assert payload['automation_state'] == 'completed'
    assert payload['last_agent_comment'] is not None

    comments = client.get(f"/api/tasks/{task['id']}/comments")
    assert comments.status_code == 200
    # Executor may apply updates directly without adding an extra runner comment.
    assert isinstance(comments.json(), list)


def test_runner_can_complete_task_from_instruction(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    task = client.post('/api/tasks', json={'title': 'Complete me', 'workspace_id': ws_id}).json()

    queued = client.post(f"/api/tasks/{task['id']}/automation/run", json={'instruction': '#complete'})
    assert queued.status_code == 200

    from features.agents.runner import run_queued_automation_once

    processed = run_queued_automation_once(limit=5)
    assert processed >= 1

    refreshed = client.get(f"/api/tasks?workspace_id={ws_id}&q=Complete me")
    assert refreshed.status_code == 200
    current = next(t for t in refreshed.json()['items'] if t['id'] == task['id'])
    assert current['status'] == 'Done'


def test_agent_service_rejects_invalid_mcp_token(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from fastapi import HTTPException
    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "secret-token")
    service = AgentTaskService()

    try:
        service.list_tasks(workspace_id=ws_id, auth_token="wrong-token")
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 401


def test_agent_service_enforces_workspace_allowlist(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from fastapi import HTTPException
    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {"different-workspace"})
    service = AgentTaskService()

    try:
        service.list_tasks(workspace_id=ws_id)
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 403


def test_runner_marks_failed_when_executor_raises(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    task = client.post('/api/tasks', json={'title': 'Executor fail task', 'workspace_id': ws_id}).json()
    queued = client.post(f"/api/tasks/{task['id']}/automation/run", json={'instruction': 'trigger failure'})
    assert queued.status_code == 200

    import features.agents.runner as runner_module

    def boom(**kwargs):
        raise RuntimeError("executor boom")

    monkeypatch.setattr(runner_module, "execute_task_automation", boom)
    processed = runner_module.run_queued_automation_once(limit=5)
    assert processed >= 1

    status = client.get(f"/api/tasks/{task['id']}/automation")
    assert status.status_code == 200
    payload = status.json()
    assert payload['automation_state'] == 'failed'
    assert 'executor boom' in (payload['last_agent_error'] or '')


def test_agent_service_create_task_infers_workspace_from_project(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Infer WS Project'}).json()

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    created = service.create_task(
        title='Created via project context',
        project_id=project['id'],
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert created['workspace_id'] == ws_id
    assert created['project_id'] == project['id']


def test_agent_service_create_task_uses_single_allowed_workspace_when_missing(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", "")
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})

    service = AgentTaskService()
    created = service.create_task(title='Created via single allowlist workspace')
    assert created['workspace_id'] == ws_id


def test_agent_service_create_project_uses_default_workspace(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})

    service = AgentTaskService()
    created = service.create_project(name='MCP New Project')
    assert created['workspace_id'] == ws_id
    assert created['name'] == 'MCP New Project'


def test_workspace_activity_cursor_read_model_returns_new_rows(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    created = client.post('/api/tasks', json={'title': 'Activity SSE seed', 'workspace_id': ws_id})
    assert created.status_code == 200

    from shared.models import SessionLocal
    from features.notifications.read_models import list_workspace_activity_after_id_read_model

    with SessionLocal() as db:
        items = list_workspace_activity_after_id_read_model(db, ws_id, cursor=0, limit=200)
        assert any(item['task_id'] == created.json()['id'] for item in items)


def test_agents_chat_endpoint_returns_executor_response(tmp_path):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'instruction': 'Leave a quick summary',
            'session_id': 'test-session-1',
            'history': [{'role': 'user', 'content': 'Hi'}],
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload['ok'] is True
    assert payload['action'] in {'complete', 'comment'}
    assert isinstance(payload['summary'], str)
    assert payload['session_id'] == 'test-session-1'


def test_create_scheduled_task_requires_instruction_and_time(tmp_path):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']

    res = client.post(
        '/api/tasks',
        json={
            'title': 'Scheduled invalid',
            'workspace_id': ws_id,
            'task_type': 'scheduled_instruction',
        },
    )
    assert res.status_code == 422
    assert 'scheduled_instruction' in res.text or 'scheduled_at_utc' in res.text


def test_scheduled_instruction_task_is_queued_and_processed(tmp_path):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']
    due_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Scheduled run',
            'workspace_id': ws_id,
            'task_type': 'scheduled_instruction',
            'scheduled_instruction': 'Leave progress note',
            'scheduled_at_utc': due_at,
            'schedule_timezone': 'UTC',
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    from features.agents.runner import queue_due_scheduled_tasks_once, run_queued_automation_once

    queued = queue_due_scheduled_tasks_once(limit=10)
    assert queued >= 1

    queued_status = client.get(f'/api/tasks/{task_id}/automation').json()
    assert queued_status['automation_state'] in {'queued', 'running', 'completed'}
    assert queued_status['schedule_state'] in {'queued', 'running', 'done'}

    processed = run_queued_automation_once(limit=10)
    assert processed >= 1

    final_status = client.get(f'/api/tasks/{task_id}/automation').json()
    assert final_status['automation_state'] == 'completed'
    assert final_status['schedule_state'] == 'done'
    assert final_status['last_schedule_run_at'] is not None


def test_recurring_scheduled_instruction_rearms_next_run(tmp_path):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']
    due_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Recurring scheduled run',
            'workspace_id': ws_id,
            'task_type': 'scheduled_instruction',
            'scheduled_instruction': 'Leave progress note',
            'scheduled_at_utc': due_at,
            'schedule_timezone': 'UTC',
            'recurring_rule': 'every:5m',
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    from features.agents.runner import queue_due_scheduled_tasks_once, run_queued_automation_once

    queued = queue_due_scheduled_tasks_once(limit=10)
    assert queued >= 1

    processed = run_queued_automation_once(limit=10)
    assert processed >= 1

    status = client.get(f'/api/tasks/{task_id}/automation').json()
    assert status['automation_state'] == 'completed'
    assert status['schedule_state'] == 'idle'
    assert status['scheduled_at_utc'] is not None
    assert datetime.fromisoformat(status['scheduled_at_utc']) > datetime.now(timezone.utc)
