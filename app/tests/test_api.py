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
