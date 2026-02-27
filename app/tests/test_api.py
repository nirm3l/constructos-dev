import asyncio
import json
import os
import threading
from importlib import reload
from pathlib import Path
import zipfile
from zoneinfo import ZoneInfo

from datetime import datetime, timedelta, timezone
from io import BytesIO

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, text


def build_client(tmp_path: Path):
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    import main

    main = reload(main)
    main.bootstrap_data()
    client = TestClient(main.app)
    login = client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'})
    assert login.status_code == 200
    return client


def build_anonymous_client(tmp_path: Path):
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    import main

    main = reload(main)
    main.bootstrap_data()
    return TestClient(main.app)


def trigger_system_notifications_for_user(user_id: str) -> int:
    from shared.core import emit_system_notifications
    from shared.models import SessionLocal, User

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        return emit_system_notifications(db, user)


def test_health(tmp_path):
    client = build_client(tmp_path)
    res = client.get('/api/health')
    assert res.status_code == 200
    assert res.json()['ok'] is True


def test_bootstrap_requires_authenticated_session(tmp_path):
    client = build_anonymous_client(tmp_path)
    res = client.get('/api/bootstrap')
    assert res.status_code == 401


def test_version_endpoint_is_stable_per_deploy(tmp_path):
    os.environ["APP_VERSION"] = "test-1.2.3"
    os.environ["APP_BUILD"] = "build-test"
    os.environ["APP_DEPLOYED_AT_UTC"] = "2026-02-16T20:00:00Z"
    client = build_client(tmp_path)

    first = client.get('/api/version')
    second = client.get('/api/version')

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["backend_version"] == "test-1.2.3"
    assert first.json()["backend_build"] == "build-test"
    assert first.json()["deployed_at_utc"] == "2026-02-16T20:00:00Z"


def test_create_and_complete_task(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post('/api/tasks', json={'title': 'Write tests', 'workspace_id': ws_id, 'project_id': project_id})
    assert created.status_code == 200
    task = created.json()
    assert task['title'] == 'Write tests'

    done = client.post(f"/api/tasks/{task['id']}/complete")
    assert done.status_code == 200
    assert done.json()['status'] == 'Done'


def test_create_task_is_case_insensitive_idempotent_by_title(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    first = client.post('/api/tasks', json={'title': 'FK Sarajevo Plan', 'workspace_id': ws_id, 'project_id': project_id})
    second = client.post('/api/tasks', json={'title': 'fk sarajevo plan', 'workspace_id': ws_id, 'project_id': project_id})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()['id'] == second.json()['id']

    listed = client.get(f"/api/tasks?workspace_id={ws_id}&project_id={project_id}&q=fk sarajevo plan")
    assert listed.status_code == 200
    assert len([item for item in listed.json()['items'] if item['title'].strip().lower() == 'fk sarajevo plan']) == 1


def test_search_filter(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    client.post('/api/tasks', json={'title': 'High prio', 'workspace_id': ws_id, 'project_id': project_id, 'priority': 'High'})
    res = client.get(f'/api/tasks?workspace_id={ws_id}&project_id={project_id}&priority=High')
    assert res.status_code == 200
    assert any(t['priority'] == 'High' for t in res.json()['items'])


def test_create_note_is_case_insensitive_idempotent_by_title(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    first = client.post('/api/notes', json={'title': 'FK Sarajevo Note', 'workspace_id': ws_id, 'project_id': project_id, 'body': 'one'})
    second = client.post('/api/notes', json={'title': 'fk sarajevo note', 'workspace_id': ws_id, 'project_id': project_id, 'body': 'two'})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()['id'] == second.json()['id']

    listed = client.get(f"/api/notes?workspace_id={ws_id}&project_id={project_id}&q=fk sarajevo note")
    assert listed.status_code == 200
    assert len([item for item in listed.json()['items'] if item['title'].strip().lower() == 'fk sarajevo note']) == 1


def test_create_note_after_deleted_title_allocates_new_identity(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    first = client.post(
        '/api/notes?command_id=test-note-recreate-first',
        json={'title': 'Untitled note', 'workspace_id': ws_id, 'project_id': project_id, 'body': ''},
    )
    assert first.status_code == 200
    first_note = first.json()

    deleted = client.post(f"/api/notes/{first_note['id']}/delete?command_id=test-note-recreate-delete")
    assert deleted.status_code == 200

    recreated = client.post(
        '/api/notes?command_id=test-note-recreate-second',
        json={'title': 'Untitled note', 'workspace_id': ws_id, 'project_id': project_id, 'body': ''},
    )
    assert recreated.status_code == 200
    recreated_note = recreated.json()
    assert recreated_note['id'] != first_note['id']
    assert recreated_note['title'] == 'Untitled note'

    recreated_again = client.post(
        '/api/notes?command_id=test-note-recreate-third',
        json={'title': 'Untitled note', 'workspace_id': ws_id, 'project_id': project_id, 'body': ''},
    )
    assert recreated_again.status_code == 200
    assert recreated_again.json()['id'] == recreated_note['id']

    listed = client.get(f"/api/notes?workspace_id={ws_id}&project_id={project_id}&q=untitled note")
    assert listed.status_code == 200
    active_ids = [item['id'] for item in listed.json()['items'] if item['title'].strip().lower() == 'untitled note']
    assert active_ids == [recreated_note['id']]


def test_create_note_force_new_bypasses_title_idempotency(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    first = client.post(
        '/api/notes?command_id=test-note-force-new-first',
        json={
            'title': 'Untitled note',
            'workspace_id': ws_id,
            'project_id': project_id,
            'body': '',
        },
    )
    assert first.status_code == 200
    first_note = first.json()

    second = client.post(
        '/api/notes?command_id=test-note-force-new-second',
        json={
            'title': 'Untitled note',
            'workspace_id': ws_id,
            'project_id': project_id,
            'body': '',
            'force_new': True,
        },
    )
    assert second.status_code == 200
    second_note = second.json()
    assert second_note['id'] != first_note['id']

    listed = client.get(f"/api/notes?workspace_id={ws_id}&project_id={project_id}&q=untitled note")
    assert listed.status_code == 200
    matching = [item for item in listed.json()['items'] if item['title'].strip().lower() == 'untitled note']
    assert len(matching) == 2


def test_task_list_reports_linked_note_count(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created_task = client.post(
        '/api/tasks',
        json={
            'title': 'Task with linked notes',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    assert created_task.status_code == 200
    task = created_task.json()

    active_note = client.post(
        '/api/notes',
        json={
            'title': 'Active linked note',
            'workspace_id': ws_id,
            'project_id': project_id,
            'task_id': task['id'],
            'body': 'hello',
        },
    )
    assert active_note.status_code == 200

    archived_note = client.post(
        '/api/notes',
        json={
            'title': 'Archived linked note',
            'workspace_id': ws_id,
            'project_id': project_id,
            'task_id': task['id'],
            'body': 'archive me',
            'force_new': True,
        },
    )
    assert archived_note.status_code == 200
    archived_note_id = archived_note.json()['id']

    archived_res = client.post(f'/api/notes/{archived_note_id}/archive')
    assert archived_res.status_code == 200

    listed = client.get(f'/api/tasks?workspace_id={ws_id}&project_id={project_id}')
    assert listed.status_code == 200
    listed_task = next(item for item in listed.json()['items'] if item['id'] == task['id'])
    assert listed_task['linked_note_count'] == 1


def test_project_and_task_refs_roundtrip(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    project = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'With refs',
            'external_refs': [{'url': 'https://docs.example.com/spec', 'title': 'Spec'}],
            'attachment_refs': [{'path': '/tmp/spec.pdf', 'name': 'spec.pdf'}],
        },
    )
    assert project.status_code == 200
    project_payload = project.json()
    assert project_payload['external_refs'][0]['url'] == 'https://docs.example.com/spec'
    assert project_payload['attachment_refs'][0]['path'] == '/tmp/spec.pdf'

    task = client.post(
        '/api/tasks',
        json={
            'title': 'Task refs',
            'workspace_id': ws_id,
            'project_id': project_payload['id'],
            'external_refs': [{'url': 'https://jira.example.com/TASK-1'}],
            'attachment_refs': [{'path': '/tmp/local.txt'}],
        },
    )
    assert task.status_code == 200
    task_payload = task.json()
    assert task_payload['external_refs'][0]['url'] == 'https://jira.example.com/TASK-1'
    assert task_payload['attachment_refs'][0]['path'] == '/tmp/local.txt'


def test_local_attachment_upload_and_download(tmp_path):
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    task = client.post('/api/tasks', json={'title': 'Attachment target', 'workspace_id': ws_id, 'project_id': project_id})
    assert task.status_code == 200
    task_id = task.json()['id']

    uploaded = client.post(
        '/api/attachments/upload',
        data={'workspace_id': ws_id, 'project_id': project_id, 'task_id': task_id},
        files={'file': ('hello.txt', BytesIO(b'hello world'), 'text/plain')},
    )
    assert uploaded.status_code == 200
    payload = uploaded.json()
    assert payload['name'] == 'hello.txt'
    assert payload['size_bytes'] == 11
    assert payload['path'].startswith(f'workspace/{ws_id}/')

    downloaded = client.get(
        f"/api/attachments/download?workspace_id={ws_id}&path={payload['path']}"
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b'hello world'

    deleted = client.post('/api/attachments/delete', json={'workspace_id': ws_id, 'path': payload['path']})
    assert deleted.status_code == 200
    assert deleted.json()['ok'] is True

    after_delete = client.get(
        f"/api/attachments/download?workspace_id={ws_id}&path={payload['path']}"
    )
    assert after_delete.status_code == 404


def test_comment_mention_creates_notification(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    current_user = bootstrap['current_user']
    task = client.post('/api/tasks', json={'title': 'Mention', 'workspace_id': ws_id, 'project_id': project_id}).json()

    comment = client.post(f"/api/tasks/{task['id']}/comments", json={'body': f"Ping @{current_user['username']}"})
    assert comment.status_code == 200

    notes = client.get('/api/notifications')
    assert notes.status_code == 200
    mentioned = [n for n in notes.json() if 'mentioned' in n['message']]
    assert mentioned
    assert any(n.get('task_id') == task['id'] for n in mentioned)
    assert any(n.get('project_id') == project_id for n in mentioned)


def test_comment_mention_respects_target_notification_preference(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    current_user = bootstrap['current_user']

    disabled = client.patch('/api/me/preferences', json={'notifications_enabled': False})
    assert disabled.status_code == 200
    assert disabled.json()['notifications_enabled'] is False

    task = client.post('/api/tasks', json={'title': 'Mention preference', 'workspace_id': ws_id, 'project_id': project_id}).json()
    comment = client.post(f"/api/tasks/{task['id']}/comments", json={'body': f"Ping @{current_user['username']}"})
    assert comment.status_code == 200

    notes = client.get('/api/notifications')
    assert notes.status_code == 200
    mentioned = [n for n in notes.json() if 'mentioned you on task' in n['message'] and n.get('task_id') == task['id']]
    assert mentioned == []


def test_delete_comment(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    task = client.post('/api/tasks', json={'title': 'Delete comment', 'workspace_id': ws_id, 'project_id': project_id}).json()

    comment = client.post(f"/api/tasks/{task['id']}/comments", json={'body': "Temporary"}).json()
    assert comment.get('id') is not None

    deleted = client.post(f"/api/tasks/{task['id']}/comments/{comment['id']}/delete")
    assert deleted.status_code == 200
    assert deleted.json()['ok'] is True

    comments = client.get(f"/api/tasks/{task['id']}/comments")
    assert comments.status_code == 200
    assert all(c['id'] != comment['id'] for c in comments.json())


def test_today_view_respects_user_timezone(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    user_tz = ZoneInfo(bootstrap['current_user']['timezone'])

    now_utc = datetime.now(timezone.utc)
    local_today_start = now_utc.astimezone(user_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    due_local = local_today_start + timedelta(hours=1)
    due_utc = due_local.astimezone(timezone.utc)

    created = client.post(
        '/api/tasks',
        json={'title': 'TZ today task', 'workspace_id': ws_id, 'project_id': project_id, 'due_date': due_utc.isoformat()},
    )
    assert created.status_code == 200

    today = client.get(f'/api/tasks?workspace_id={ws_id}&project_id={project_id}&view=today')
    assert today.status_code == 200
    assert any(t['title'] == 'TZ today task' for t in today.json()['items'])


def test_inbox_view_shows_actionable_tasks_for_current_user(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    current_user = bootstrap['current_user']
    current_user_id = current_user['id']
    user_tz = ZoneInfo(current_user['timezone'])
    other_user_id = next(
        item['id']
        for item in bootstrap['users']
        if item['id'] != current_user_id
    )

    now_utc = datetime.now(timezone.utc)
    local_today_start = now_utc.astimezone(user_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    due_today_utc = (local_today_start + timedelta(hours=10)).astimezone(timezone.utc)
    due_tomorrow_utc = (local_today_start + timedelta(days=1, hours=11)).astimezone(timezone.utc)
    due_later_utc = (local_today_start + timedelta(days=3, hours=9)).astimezone(timezone.utc)

    no_due = client.post(
        '/api/tasks',
        json={'title': 'Inbox no due', 'workspace_id': ws_id, 'project_id': project_id},
    )
    assert no_due.status_code == 200

    due_today = client.post(
        '/api/tasks',
        json={
            'title': 'Inbox due today',
            'workspace_id': ws_id,
            'project_id': project_id,
            'assignee_id': current_user_id,
            'due_date': due_today_utc.isoformat(),
        },
    )
    assert due_today.status_code == 200

    due_tomorrow = client.post(
        '/api/tasks',
        json={
            'title': 'Inbox due tomorrow',
            'workspace_id': ws_id,
            'project_id': project_id,
            'due_date': due_tomorrow_utc.isoformat(),
        },
    )
    assert due_tomorrow.status_code == 200

    due_later = client.post(
        '/api/tasks',
        json={
            'title': 'Inbox due later',
            'workspace_id': ws_id,
            'project_id': project_id,
            'due_date': due_later_utc.isoformat(),
        },
    )
    assert due_later.status_code == 200

    assigned_other = client.post(
        '/api/tasks',
        json={
            'title': 'Inbox assigned other',
            'workspace_id': ws_id,
            'project_id': project_id,
            'assignee_id': other_user_id,
            'due_date': due_today_utc.isoformat(),
        },
    )
    assert assigned_other.status_code == 200

    done_task = client.post(
        '/api/tasks',
        json={
            'title': 'Inbox done task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'due_date': due_today_utc.isoformat(),
        },
    )
    assert done_task.status_code == 200
    done_complete = client.post(f"/api/tasks/{done_task.json()['id']}/complete")
    assert done_complete.status_code == 200

    inbox = client.get(f'/api/tasks?workspace_id={ws_id}&project_id={project_id}&view=inbox')
    assert inbox.status_code == 200
    titles = {item['title'] for item in inbox.json()['items']}

    assert 'Inbox no due' in titles
    assert 'Inbox due today' in titles
    assert 'Inbox due tomorrow' in titles
    assert 'Inbox due later' not in titles
    assert 'Inbox assigned other' not in titles
    assert 'Inbox done task' not in titles


def test_create_project(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    res = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Mobile Redesign'})
    assert res.status_code == 200
    payload = res.json()
    assert payload['name'] == 'Mobile Redesign'
    assert payload['workspace_id'] == ws_id


def test_bootstrap_exposes_embedding_runtime_config(tmp_path, monkeypatch):
    from features.agents import mcp_registry

    monkeypatch_rows = [
        {
            'name': 'task-management-tools',
            'display_name': 'Task Management Tools',
            'enabled': True,
            'disabled_reason': None,
            'auth_status': None,
            'config': {'url': 'http://mcp-tools:8091/mcp'},
        },
        {
            'name': 'jira',
            'display_name': 'Jira',
            'enabled': True,
            'disabled_reason': None,
            'auth_status': 'authorized',
            'config': {'url': 'http://jira-mcp:9000/mcp'},
        },
    ]

    monkeypatch.setattr(mcp_registry, '_get_rows', lambda force_refresh=False: monkeypatch_rows)

    client = build_client(tmp_path)
    payload = client.get('/api/bootstrap').json()

    assert isinstance(payload.get('embedding_allowed_models'), list)
    assert len(payload['embedding_allowed_models']) >= 1
    assert isinstance(payload.get('embedding_default_model'), str)
    assert payload['embedding_default_model'] in payload['embedding_allowed_models']
    assert isinstance(payload.get('vector_store_enabled'), bool)
    assert isinstance(payload.get('context_pack_evidence_top_k_default'), int)
    assert payload.get('agent_chat_available_mcp_servers') == [
        {
            'name': 'task-management-tools',
            'display_name': 'Task Management Tools',
            'enabled': True,
            'disabled_reason': None,
            'auth_status': None,
        },
        {
            'name': 'jira',
            'display_name': 'Jira',
            'enabled': True,
            'disabled_reason': None,
            'auth_status': 'authorized',
        },
    ]


def test_project_embedding_config_and_index_status_roundtrip(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    allowed_models = bootstrap['embedding_allowed_models']

    created = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Embeddings project',
            'embedding_enabled': True,
            'context_pack_evidence_top_k': 9,
        },
    )
    assert created.status_code == 200
    project = created.json()
    assert project['embedding_enabled'] is True
    assert project['embedding_model'] in allowed_models
    assert project['context_pack_evidence_top_k'] == 9
    assert project['embedding_index_status'] == 'not_indexed'

    patched = client.patch(
        f"/api/projects/{project['id']}",
        json={'embedding_enabled': False, 'context_pack_evidence_top_k': None},
    )
    assert patched.status_code == 200
    patched_payload = patched.json()
    assert patched_payload['embedding_enabled'] is False
    assert patched_payload['context_pack_evidence_top_k'] is None
    assert patched_payload['embedding_index_status'] == 'not_indexed'

    invalid = client.patch(
        f"/api/projects/{project['id']}",
        json={'embedding_model': 'not-allowed-model'},
    )
    assert invalid.status_code == 422
    assert 'embedding_model must be one of' in invalid.text

    invalid_top_k = client.patch(
        f"/api/projects/{project['id']}",
        json={'context_pack_evidence_top_k': 99},
    )
    assert invalid_top_k.status_code == 422


def test_reindex_project_uses_runtime_override_model(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOWED_EMBEDDING_MODELS", "nomic-embed-text,mxbai-embed-large")
    monkeypatch.setenv("DEFAULT_EMBEDDING_MODEL", "nomic-embed-text")
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post(
        '/api/tasks',
        json={'title': 'Vector test task', 'workspace_id': ws_id, 'project_id': project_id, 'description': 'Body'},
    )
    assert created.status_code == 200

    from shared import vector_store
    from shared.models import Project, SessionLocal, VectorChunk

    monkeypatch.setattr(vector_store, "vector_store_enabled", lambda: True)
    monkeypatch.setattr(
        vector_store,
        "normalize_embedding_model",
        lambda value: str(value or "nomic-embed-text").strip() or "nomic-embed-text",
    )
    monkeypatch.setattr(vector_store, "_ollama_embed_text", lambda _text, _model: [0.11, 0.22, 0.33])

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.embedding_enabled = True
        project.embedding_model = "nomic-embed-text"
        db.commit()

        indexed = vector_store.maybe_reindex_project(
            db,
            project_id=project_id,
            embedding_enabled=True,
            embedding_model="mxbai-embed-large",
        )
        db.commit()

        models = db.execute(
            select(VectorChunk.embedding_model).where(
                VectorChunk.project_id == project_id,
                VectorChunk.is_deleted == False,
            )
        ).scalars().all()

    assert indexed >= 1
    assert models
    assert set(models) == {"mxbai-embed-large"}


def test_create_project_is_case_insensitive_idempotent_by_name(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    first = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'FK Sarajevo'})
    second = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'fk sarajevo'})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()['id'] == second.json()['id']
    assert first.json()['workspace_id'] == second.json()['workspace_id'] == ws_id

    projects = client.get('/api/bootstrap').json()['projects']
    matching = [p for p in projects if p['name'].strip().lower() == 'fk sarajevo']
    assert len(matching) == 1


def test_patch_project_name_and_description(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Docs'}).json()

    patched = client.patch(
        f"/api/projects/{project['id']}",
        json={'name': 'Docs v2', 'description': '## Overview\n\nUpdated project description.'},
    )
    assert patched.status_code == 200
    payload = patched.json()
    assert payload['id'] == project['id']
    assert payload['name'] == 'Docs v2'
    assert payload['description'] == '## Overview\n\nUpdated project description.'


def test_project_custom_statuses_can_be_configured_and_patched(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    created = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Workflow project',
            'custom_statuses': ['Backlog', 'In progress', 'Blocked', 'backlog'],
        },
    )
    assert created.status_code == 200
    project = created.json()
    assert project['custom_statuses'] == ['Backlog', 'In progress', 'Blocked', 'Done']

    board = client.get(f"/api/projects/{project['id']}/board")
    assert board.status_code == 200
    assert board.json()['statuses'] == ['Backlog', 'In progress', 'Blocked', 'Done']

    task = client.post(
        '/api/tasks',
        json={'title': 'Status seed', 'workspace_id': ws_id, 'project_id': project['id']},
    )
    assert task.status_code == 200
    assert task.json()['status'] == 'Backlog'

    patched = client.patch(
        f"/api/projects/{project['id']}",
        json={'custom_statuses': ['Backlog', 'In progress', 'Ready for QA', 'Done']},
    )
    assert patched.status_code == 200
    patched_payload = patched.json()
    assert patched_payload['custom_statuses'] == ['Backlog', 'In progress', 'Ready for QA', 'Done']

    board_after = client.get(f"/api/projects/{project['id']}/board")
    assert board_after.status_code == 200
    assert board_after.json()['statuses'] == ['Backlog', 'In progress', 'Ready for QA', 'Done']


def test_project_board_supports_tag_filtering(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    project = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Board tag filter'}).json()

    task_alpha = client.post(
        '/api/tasks',
        json={'title': 'Alpha task', 'workspace_id': ws_id, 'project_id': project['id'], 'labels': ['alpha']},
    )
    assert task_alpha.status_code == 200
    alpha_id = task_alpha.json()['id']

    task_beta = client.post(
        '/api/tasks',
        json={'title': 'Beta task', 'workspace_id': ws_id, 'project_id': project['id'], 'labels': ['beta']},
    )
    assert task_beta.status_code == 200
    beta_id = task_beta.json()['id']

    board_all = client.get(f"/api/projects/{project['id']}/board")
    assert board_all.status_code == 200
    all_ids = {task['id'] for lane in board_all.json()['lanes'].values() for task in lane}
    assert {alpha_id, beta_id}.issubset(all_ids)

    board_alpha = client.get(f"/api/projects/{project['id']}/board?tags=ALPHA")
    assert board_alpha.status_code == 200
    alpha_ids = {task['id'] for lane in board_alpha.json()['lanes'].values() for task in lane}
    assert alpha_id in alpha_ids
    assert beta_id not in alpha_ids

    board_alpha_beta = client.get(f"/api/projects/{project['id']}/board?tags=alpha,beta")
    assert board_alpha_beta.status_code == 200
    alpha_beta_ids = {task['id'] for lane in board_alpha_beta.json()['lanes'].values() for task in lane}
    assert {alpha_id, beta_id}.issubset(alpha_beta_ids)


def test_project_members_assignment_and_user_types(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    owner_id = bootstrap['current_user']['id']

    from shared.models import SessionLocal, User, WorkspaceMember

    second_user_id = '00000000-0000-0000-0000-000000000222'
    with SessionLocal() as db:
        if not db.get(User, second_user_id):
            db.add(User(id=second_user_id, username='alice', full_name='Alice Example', user_type='human'))
        member = db.query(WorkspaceMember).filter_by(workspace_id=ws_id, user_id=second_user_id).first()
        if not member:
            db.add(WorkspaceMember(workspace_id=ws_id, user_id=second_user_id, role='Member'))
        db.commit()

    created = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Members project',
            'member_user_ids': [second_user_id],
        },
    )
    assert created.status_code == 200
    project_id = created.json()['id']

    members = client.get(f'/api/projects/{project_id}/members')
    assert members.status_code == 200
    payload = members.json()
    member_ids = {item['user_id'] for item in payload['items']}
    assert owner_id in member_ids
    assert second_user_id in member_ids
    assert payload['total'] >= 2

    removed = client.post(f'/api/projects/{project_id}/members/{second_user_id}/remove')
    assert removed.status_code == 200
    members_after = client.get(f'/api/projects/{project_id}/members').json()
    member_ids_after = {item['user_id'] for item in members_after['items']}
    assert second_user_id not in member_ids_after

    refreshed = client.get('/api/bootstrap').json()
    assert refreshed['current_user']['user_type'] in {'human', 'agent'}
    assert all(u['user_type'] in {'human', 'agent'} for u in refreshed['users'])
    assert any(pm['project_id'] == project_id for pm in refreshed['project_members'])


def test_non_admin_user_sees_only_assigned_projects(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    assigned_project_id = bootstrap['projects'][0]['id']

    hidden_project = client.post(
        '/api/projects',
        json={'workspace_id': ws_id, 'name': 'Hidden project for member'},
    )
    assert hidden_project.status_code == 200
    hidden_project_id = hidden_project.json()['id']

    created_user = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'member-assigned-only', 'full_name': 'Assigned Member'},
    )
    assert created_user.status_code == 200
    created_payload = created_user.json()
    member_id = created_payload['user']['id']
    temp_password = created_payload['temporary_password']

    assigned = client.post(
        f'/api/projects/{assigned_project_id}/members',
        json={'user_id': member_id, 'role': 'Contributor'},
    )
    assert assigned.status_code == 200

    logout = client.post('/api/auth/logout')
    assert logout.status_code == 200

    login = client.post('/api/auth/login', json={'username': 'member-assigned-only', 'password': temp_password})
    assert login.status_code == 200
    assert login.json()['user']['must_change_password'] is True

    changed = client.post(
        '/api/auth/change-password',
        json={'current_password': temp_password, 'new_password': 'memberpass1'},
    )
    assert changed.status_code == 200
    assert changed.json()['user']['must_change_password'] is False

    member_bootstrap = client.get('/api/bootstrap')
    assert member_bootstrap.status_code == 200
    visible_project_ids = {item['id'] for item in member_bootstrap.json()['projects']}
    assert assigned_project_id in visible_project_ids
    assert hidden_project_id not in visible_project_ids

    hidden_tasks = client.get(f'/api/tasks?workspace_id={ws_id}&project_id={hidden_project_id}')
    assert hidden_tasks.status_code == 403
    assert hidden_tasks.json()['detail'] == 'Project access required'


def test_delete_project_deletes_project_resources(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    project = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'To delete'}).json()
    task = client.post('/api/tasks', json={'title': 'Belongs to project', 'workspace_id': ws_id, 'project_id': project['id']}).json()
    assert task['project_id'] == project['id']

    note = client.post('/api/notes', json={'title': 'Project note', 'workspace_id': ws_id, 'project_id': project['id']}).json()

    deleted = client.delete(f"/api/projects/{project['id']}")
    assert deleted.status_code == 200
    assert deleted.json()['ok'] is True
    assert deleted.json()['deleted_tasks'] == 1
    assert deleted.json()['deleted_notes'] == 1

    tasks = client.get(f'/api/tasks?workspace_id={ws_id}&project_id={project["id"]}').json()['items']
    assert all(t['id'] != task['id'] for t in tasks)
    notes = client.get(f'/api/notes?workspace_id={ws_id}&project_id={project["id"]}').json()['items']
    assert all(n['id'] != note['id'] for n in notes)


def test_project_tags_are_shared_between_tasks_notes_and_specifications(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    task = client.post(
        '/api/tasks',
        json={'title': 'Tagged task', 'workspace_id': ws_id, 'project_id': project_id, 'labels': ['Shared', 'TaskOnly']},
    )
    assert task.status_code == 200

    note = client.post(
        '/api/notes',
        json={'title': 'Tagged note', 'workspace_id': ws_id, 'project_id': project_id, 'tags': ['shared', 'NoteOnly']},
    )
    assert note.status_code == 200

    specification = client.post(
        '/api/specifications',
        json={
            'title': 'Tagged specification',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Draft',
            'tags': ['shared', 'SpecOnly'],
        },
    )
    assert specification.status_code == 200

    tags = client.get(f"/api/projects/{project_id}/tags")
    assert tags.status_code == 200
    payload = tags.json()
    assert payload['project_id'] == project_id
    assert {'noteonly', 'shared', 'taskonly', 'speconly'}.issubset(set(payload['tags']))
    assert payload['tags'] == [item['tag'] for item in payload['tag_stats']]

    usage_by_tag = {item['tag']: item['usage_count'] for item in payload['tag_stats']}
    assert usage_by_tag['shared'] == 3
    assert usage_by_tag['taskonly'] == 1
    assert usage_by_tag['noteonly'] == 1
    assert usage_by_tag['speconly'] == 1


def test_project_knowledge_graph_endpoints(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    project_id = bootstrap['projects'][0]['id']

    import features.agents.service as agent_service_module
    from features.projects import api as projects_api

    monkeypatch.setattr(
        agent_service_module,
        'require_graph_available',
        lambda: None,
    )
    monkeypatch.setattr(
        agent_service_module,
        'graph_get_project_overview_query',
        lambda project_id, top_limit=8: {
            'project_id': project_id,
            'project_name': 'Stub Project',
            'counts': {'tasks': 2, 'notes': 1, 'specifications': 1, 'project_rules': 1},
            'top_tags': [{'tag': 'shared', 'usage': 3}],
            'top_relationships': [{'relationship': 'IN_PROJECT', 'count': 10}],
        },
    )
    monkeypatch.setattr(
        agent_service_module,
        'graph_context_pack_query',
        lambda project_id, focus_entity_type=None, focus_entity_id=None, limit=20: {
            'project_id': project_id,
            'focus_entity_type': focus_entity_type,
            'focus_entity_id': focus_entity_id,
            'overview': {
                'project_id': project_id,
                'project_name': 'Stub Project',
                'counts': {'tasks': 2, 'notes': 1, 'specifications': 1, 'project_rules': 1},
                'top_tags': [{'tag': 'shared', 'usage': 3}],
                'top_relationships': [{'relationship': 'IN_PROJECT', 'count': 10}],
            },
            'focus_neighbors': [],
            'connected_resources': [{'entity_type': 'Task', 'entity_id': 't1', 'title': 'Task one', 'degree': 4}],
            'markdown': '# Graph Context',
        },
    )
    monkeypatch.setattr(projects_api, 'require_graph_available', lambda: None)
    monkeypatch.setattr(
        projects_api,
        'graph_get_project_subgraph',
        lambda project_id, limit_nodes=48, limit_edges=160: {
            'project_id': project_id,
            'project_name': 'Stub Project',
            'node_count': 3,
            'edge_count': 2,
            'nodes': [
                {'entity_type': 'Project', 'entity_id': project_id, 'title': 'Stub Project', 'degree': 2},
                {'entity_type': 'Task', 'entity_id': 't1', 'title': 'Task one', 'degree': 1},
                {'entity_type': 'Note', 'entity_id': 'n1', 'title': 'Note one', 'degree': 1},
            ],
            'edges': [
                {'source_entity_id': project_id, 'target_entity_id': 't1', 'relationship': 'IN_PROJECT'},
                {'source_entity_id': project_id, 'target_entity_id': 'n1', 'relationship': 'IN_PROJECT'},
            ],
        },
    )

    overview = client.get(f"/api/projects/{project_id}/knowledge-graph/overview")
    assert overview.status_code == 200
    assert overview.json()['project_id'] == project_id
    assert overview.json()['counts']['tasks'] == 2

    context_pack = client.get(f"/api/projects/{project_id}/knowledge-graph/context-pack")
    assert context_pack.status_code == 200
    assert context_pack.json()['project_id'] == project_id
    assert context_pack.json()['markdown'] == '# Graph Context'

    subgraph = client.get(f"/api/projects/{project_id}/knowledge-graph/subgraph")
    assert subgraph.status_code == 200
    assert subgraph.json()['project_id'] == project_id
    assert subgraph.json()['node_count'] == 3
    assert subgraph.json()['edge_count'] == 2

    bad_focus = client.get(f"/api/projects/{project_id}/knowledge-graph/context-pack?focus_entity_type=Task")
    assert bad_focus.status_code == 400
    assert 'focus_entity_type and focus_entity_id' in bad_focus.json()['detail']


def test_project_knowledge_search_endpoint(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    project_id = bootstrap['projects'][0]['id']

    import features.agents.service as agent_service_module

    monkeypatch.setattr(
        agent_service_module,
        'search_project_knowledge_query',
        lambda project_id, query, focus_entity_type=None, focus_entity_id=None, limit=20: {
            'project_id': project_id,
            'query': query,
            'mode': 'graph+vector',
            'items': [
                {
                    'rank': 1,
                    'entity_type': 'Task',
                    'entity_id': 'task-1',
                    'source_type': 'task.description',
                    'snippet': 'Define command payload contracts',
                    'vector_similarity': 0.91,
                    'graph_score': 0.77,
                    'final_score': 0.84,
                    'graph_path': ['Task'],
                    'updated_at': None,
                }
            ],
        },
    )

    response = client.get(f"/api/projects/{project_id}/knowledge/search?q=command%20payload")
    assert response.status_code == 200
    payload = response.json()
    assert payload['project_id'] == project_id
    assert payload['mode'] == 'graph+vector'
    assert payload['items'][0]['entity_type'] == 'Task'

    bad_focus = client.get(f"/api/projects/{project_id}/knowledge/search?q=test&focus_entity_type=Task")
    assert bad_focus.status_code == 400
    assert 'focus_entity_type and focus_entity_id' in bad_focus.json()['detail']


def test_project_knowledge_graph_endpoint_returns_503_when_unavailable(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService

    def _raise_unavailable(self, project_id, top_limit=8):
        raise HTTPException(status_code=503, detail='Knowledge graph is unavailable: disabled')

    monkeypatch.setattr(AgentTaskService, 'graph_get_project_overview', _raise_unavailable)
    res = client.get(f"/api/projects/{project_id}/knowledge-graph/overview")
    assert res.status_code == 503
    assert 'Knowledge graph is unavailable' in res.json()['detail']


def test_user_theme_preferences_persist(tmp_path):
    client = build_client(tmp_path)
    updated = client.patch('/api/me/preferences', json={'theme': 'dark'})
    assert updated.status_code == 200
    assert updated.json()['theme'] == 'dark'

    bootstrap = client.get('/api/bootstrap')
    assert bootstrap.status_code == 200
    assert bootstrap.json()['current_user']['theme'] == 'dark'


def test_admin_create_user_forces_password_change_flow(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    created = client.post(
        '/api/admin/users',
        json={
            'workspace_id': ws_id,
            'username': 'new-user-01',
            'full_name': 'New User',
        },
    )
    assert created.status_code == 200
    payload = created.json()
    temp_password = payload['temporary_password']
    created_user_id = payload['user']['id']
    assert payload['user']['must_change_password'] is True

    users_page = client.get(f'/api/admin/users?workspace_id={ws_id}')
    assert users_page.status_code == 200
    assert any(item['id'] == created_user_id for item in users_page.json()['items'])

    logout = client.post('/api/auth/logout')
    assert logout.status_code == 200

    login = client.post('/api/auth/login', json={'username': 'new-user-01', 'password': temp_password})
    assert login.status_code == 200
    assert login.json()['user']['must_change_password'] is True

    blocked_bootstrap = client.get('/api/bootstrap')
    assert blocked_bootstrap.status_code == 403
    assert blocked_bootstrap.json()['detail'] == 'Password change required'

    changed = client.post(
        '/api/auth/change-password',
        json={'current_password': temp_password, 'new_password': 'newpass88'},
    )
    assert changed.status_code == 200
    assert changed.json()['user']['must_change_password'] is False

    bootstrap_after = client.get('/api/bootstrap')
    assert bootstrap_after.status_code == 200
    assert bootstrap_after.json()['current_user']['username'] == 'new-user-01'


def test_admin_reset_password_rotates_login_secret(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    created = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'reset-target'},
    )
    assert created.status_code == 200
    target_id = created.json()['user']['id']
    first_temp_password = created.json()['temporary_password']

    reset = client.post(
        f'/api/admin/users/{target_id}/reset-password',
        json={'workspace_id': ws_id},
    )
    assert reset.status_code == 200
    second_temp_password = reset.json()['temporary_password']
    assert second_temp_password != first_temp_password

    logout = client.post('/api/auth/logout')
    assert logout.status_code == 200

    old_login = client.post('/api/auth/login', json={'username': 'reset-target', 'password': first_temp_password})
    assert old_login.status_code == 401

    new_login = client.post('/api/auth/login', json={'username': 'reset-target', 'password': second_temp_password})
    assert new_login.status_code == 200
    assert new_login.json()['user']['must_change_password'] is True


def test_admin_can_create_user_with_admin_role(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    created = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'admin-created-user', 'role': 'Admin'},
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload['user']['role'] == 'Admin'

    users_page = client.get(f'/api/admin/users?workspace_id={ws_id}')
    assert users_page.status_code == 200
    created_row = next((item for item in users_page.json()['items'] if item['id'] == payload['user']['id']), None)
    assert created_row is not None
    assert created_row['role'] == 'Admin'


def test_admin_can_update_workspace_user_role(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    created = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'role-update-target', 'role': 'Member'},
    )
    assert created.status_code == 200
    target_id = created.json()['user']['id']

    updated = client.post(
        f'/api/admin/users/{target_id}/set-role',
        json={'workspace_id': ws_id, 'role': 'Admin'},
    )
    assert updated.status_code == 200
    assert updated.json()['ok'] is True
    assert updated.json()['role'] == 'Admin'

    users_page = client.get(f'/api/admin/users?workspace_id={ws_id}')
    assert users_page.status_code == 200
    updated_row = next((item for item in users_page.json()['items'] if item['id'] == target_id), None)
    assert updated_row is not None
    assert updated_row['role'] == 'Admin'


def test_admin_can_deactivate_workspace_user(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    created = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'deactivate-target'},
    )
    assert created.status_code == 200
    target_id = created.json()['user']['id']
    temp_password = created.json()['temporary_password']

    login_before_deactivate = client.post(
        '/api/auth/login',
        json={'username': 'deactivate-target', 'password': temp_password},
    )
    assert login_before_deactivate.status_code == 200

    admin_login = client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'})
    assert admin_login.status_code == 200

    deactivated = client.post(
        f'/api/admin/users/{target_id}/deactivate',
        json={'workspace_id': ws_id},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()['ok'] is True
    assert deactivated.json()['is_active'] is False

    users_page = client.get(f'/api/admin/users?workspace_id={ws_id}')
    assert users_page.status_code == 200
    deactivated_row = next((item for item in users_page.json()['items'] if item['id'] == target_id), None)
    assert deactivated_row is not None
    assert deactivated_row['is_active'] is False
    assert deactivated_row['can_deactivate'] is False

    client.post('/api/auth/logout')
    login_after_deactivate = client.post(
        '/api/auth/login',
        json={'username': 'deactivate-target', 'password': temp_password},
    )
    assert login_after_deactivate.status_code == 401


def test_admin_cannot_deactivate_own_account(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    me_id = bootstrap['current_user']['id']

    blocked = client.post(
        f'/api/admin/users/{me_id}/deactivate',
        json={'workspace_id': ws_id},
    )
    assert blocked.status_code == 409
    assert blocked.json()['detail'] == 'You cannot deactivate your own account'


def test_admin_cannot_reset_password_for_agent_user(tmp_path):
    from shared.settings import AGENT_SYSTEM_USER_ID

    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    users_page = client.get(f'/api/admin/users?workspace_id={ws_id}')
    assert users_page.status_code == 200
    agent_item = next((item for item in users_page.json()['items'] if item['id'] == AGENT_SYSTEM_USER_ID), None)
    assert agent_item is not None
    assert agent_item['user_type'] in {'agent', 'bot'}
    assert agent_item['role'] in {'Owner', 'Admin'}
    assert agent_item['must_change_password'] is False
    assert agent_item['can_reset_password'] is False
    assert agent_item['can_deactivate'] is False

    reset = client.post(
        f'/api/admin/users/{AGENT_SYSTEM_USER_ID}/reset-password',
        json={'workspace_id': ws_id},
    )
    assert reset.status_code == 404

    deactivate = client.post(
        f'/api/admin/users/{AGENT_SYSTEM_USER_ID}/deactivate',
        json={'workspace_id': ws_id},
    )
    assert deactivate.status_code == 422


def test_due_soon_system_notification(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    due_utc = datetime.now(timezone.utc) + timedelta(minutes=30)

    created = client.post(
        '/api/tasks',
        json={'title': 'Soon deadline', 'workspace_id': ws_id, 'project_id': project_id, 'due_date': due_utc.isoformat()},
    )
    assert created.status_code == 200

    emitted = trigger_system_notifications_for_user(user_id)
    assert emitted >= 1

    notes = client.get('/api/notifications')
    assert notes.status_code == 200
    due_soon = [n for n in notes.json() if 'due within 1 hour' in n['message']]
    assert due_soon
    assert any(n.get('task_id') == created.json()['id'] for n in due_soon)
    assert any(n.get('project_id') == project_id for n in due_soon)


def test_notifications_get_is_read_only_and_does_not_emit_system_notifications(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    due_utc = datetime.now(timezone.utc) + timedelta(minutes=30)

    created = client.post(
        '/api/tasks',
        json={'title': 'Read-only notifications GET', 'workspace_id': ws_id, 'project_id': project_id, 'due_date': due_utc.isoformat()},
    )
    assert created.status_code == 200

    from shared.models import Notification, SessionLocal

    with SessionLocal() as db:
        before = db.execute(select(Notification).where(Notification.user_id == user_id)).scalars().all()
    assert before == []

    notes = client.get('/api/notifications')
    assert notes.status_code == 200
    assert not any('due within 1 hour' in n['message'] for n in notes.json())

    with SessionLocal() as db:
        after = db.execute(select(Notification).where(Notification.user_id == user_id)).scalars().all()
    assert len(after) == 0


def test_bootstrap_get_is_read_only_and_does_not_emit_system_notifications(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    due_utc = datetime.now(timezone.utc) + timedelta(minutes=30)

    created = client.post(
        '/api/tasks',
        json={'title': 'Read-only bootstrap GET', 'workspace_id': ws_id, 'project_id': project_id, 'due_date': due_utc.isoformat()},
    )
    assert created.status_code == 200

    from shared.models import Notification, SessionLocal

    with SessionLocal() as db:
        before = db.execute(select(Notification).where(Notification.user_id == user_id)).scalars().all()
    assert before == []

    refreshed = client.get('/api/bootstrap')
    assert refreshed.status_code == 200

    with SessionLocal() as db:
        after = db.execute(select(Notification).where(Notification.user_id == user_id)).scalars().all()
    assert len(after) == 0


def test_daily_digest_is_suppressed_when_all_counters_are_zero(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']

    emitted = trigger_system_notifications_for_user(user_id)
    assert emitted == 0

    first = client.get('/api/notifications')
    assert first.status_code == 200
    first_digests = [n for n in first.json() if n['message'].startswith('Daily digest for ')]
    assert first_digests == []

    second = client.get('/api/notifications')
    assert second.status_code == 200
    second_digests = [n for n in second.json() if n['message'].startswith('Daily digest for ')]
    assert second_digests == []


def test_daily_digest_is_actionable_and_lists_top_priorities(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    overdue_utc = datetime.now(timezone.utc) - timedelta(days=1, hours=2)
    due_today_utc = datetime.now(timezone.utc) + timedelta(hours=3)

    first = client.post(
        '/api/tasks',
        json={'title': 'Overdue task', 'workspace_id': ws_id, 'project_id': project_id, 'due_date': overdue_utc.isoformat()},
    )
    second = client.post(
        '/api/tasks',
        json={'title': 'Due today task', 'workspace_id': ws_id, 'project_id': project_id, 'due_date': due_today_utc.isoformat()},
    )
    third = client.post(
        '/api/tasks',
        json={'title': 'High priority task', 'workspace_id': ws_id, 'project_id': project_id, 'priority': 'High'},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200

    emitted = trigger_system_notifications_for_user(user_id)
    assert emitted >= 1

    notes = client.get('/api/notifications')
    assert notes.status_code == 200
    digests = [n for n in notes.json() if n['message'].startswith('Daily digest for ')]
    assert len(digests) == 1
    message = digests[0]['message']
    assert '1 due today' in message
    assert '1 overdue' in message
    assert '1 high priority' in message
    assert '"Overdue task" (overdue)' in message
    assert '"Due today task" (due today)' in message
    assert '"High priority task" (high priority)' in message

    overdue_pos = message.find('"Overdue task" (overdue)')
    due_today_pos = message.find('"Due today task" (due today)')
    high_pos = message.find('"High priority task" (high priority)')
    assert overdue_pos >= 0
    assert due_today_pos >= 0
    assert high_pos >= 0
    assert overdue_pos < due_today_pos < high_pos


def test_system_notifications_respect_notifications_enabled_preference(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    disabled = client.patch('/api/me/preferences', json={'notifications_enabled': False})
    assert disabled.status_code == 200
    assert disabled.json()['notifications_enabled'] is False

    due_utc = datetime.now(timezone.utc) + timedelta(minutes=30)
    created = client.post(
        '/api/tasks',
        json={'title': 'Preference-gated due soon', 'workspace_id': ws_id, 'project_id': project_id, 'due_date': due_utc.isoformat()},
    )
    assert created.status_code == 200

    emitted = trigger_system_notifications_for_user(user_id)
    assert emitted == 0

    notes = client.get('/api/notifications')
    assert notes.status_code == 200
    assert not any('due within 1 hour' in n['message'] for n in notes.json())
    assert not any(n['message'].startswith('Daily digest for ') for n in notes.json())


def test_notifications_table_has_user_created_at_index(tmp_path):
    build_client(tmp_path)

    from shared.models import SessionLocal

    with SessionLocal() as db:
        rows = db.execute(text("PRAGMA index_list('notifications')")).all()
    names = {str(row[1]) for row in rows}
    assert 'ix_notifications_user_created_at' in names


def test_notifications_table_has_typed_columns_and_dedupe_index(tmp_path):
    build_client(tmp_path)

    from shared.models import SessionLocal

    with SessionLocal() as db:
        column_rows = db.execute(text("PRAGMA table_info('notifications')")).all()
        index_rows = db.execute(text("PRAGMA index_list('notifications')")).all()
    columns = {str(row[1]) for row in column_rows}
    index_names = {str(row[1]) for row in index_rows}
    assert "notification_type" in columns
    assert "severity" in columns
    assert "dedupe_key" in columns
    assert "payload_json" in columns
    assert "source_event" in columns
    assert "ix_notifications_user_dedupe_created_at" in index_names


def test_notifications_api_returns_typed_fields(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from shared.models import Notification, SessionLocal

    with SessionLocal() as db:
        db.add(
            Notification(
                user_id=user_id,
                workspace_id=ws_id,
                project_id=project_id,
                task_id="task-api-typed-fields",
                message="Typed payload test",
                notification_type="TaskAssignedToMe",
                severity="warning",
                dedupe_key="typed-test-001",
                payload_json='{"task_id":"task-api-typed-fields","status":"To do"}',
                source_event="TaskUpdated",
            )
        )
        db.commit()

    listed = client.get('/api/notifications')
    assert listed.status_code == 200
    typed = next(item for item in listed.json() if item.get("dedupe_key") == "typed-test-001")
    assert typed["notification_type"] == "TaskAssignedToMe"
    assert typed["severity"] == "warning"
    assert typed["source_event"] == "TaskUpdated"
    assert typed["payload"]["task_id"] == "task-api-typed-fields"


def test_task_assigned_to_me_notification_is_typed(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    actor_id = bootstrap['current_user']['id']

    created_user = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'typed-assignee', 'full_name': 'Typed Assignee'},
    )
    assert created_user.status_code == 200
    assignee_id = created_user.json()['user']['id']

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Typed assignee task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'assignee_id': assignee_id,
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    from shared.models import Notification, SessionLocal
    from shared.typed_notifications import NOTIFICATION_TYPE_TASK_ASSIGNED_TO_ME

    with SessionLocal() as db:
        rows = db.execute(
            select(Notification).where(
                Notification.user_id == assignee_id,
                Notification.task_id == task_id,
                Notification.notification_type == NOTIFICATION_TYPE_TASK_ASSIGNED_TO_ME,
            )
        ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.severity == "info"
    assert row.source_event == "TaskCreated"
    assert row.dedupe_key == f"task-assigned:{task_id}:{assignee_id}:1"
    assert actor_id != assignee_id


def test_task_assigned_to_me_skips_self_assignment(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    actor_id = bootstrap['current_user']['id']

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Self assignment should not notify',
            'workspace_id': ws_id,
            'project_id': project_id,
            'assignee_id': actor_id,
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    from shared.models import Notification, SessionLocal
    from shared.typed_notifications import NOTIFICATION_TYPE_TASK_ASSIGNED_TO_ME

    with SessionLocal() as db:
        rows = db.execute(
            select(Notification).where(
                Notification.user_id == actor_id,
                Notification.task_id == task_id,
                Notification.notification_type == NOTIFICATION_TYPE_TASK_ASSIGNED_TO_ME,
            )
        ).scalars().all()
    assert rows == []


def test_watched_task_status_changed_notification_is_typed(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created_user = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'typed-watcher', 'full_name': 'Typed Watcher'},
    )
    assert created_user.status_code == 200
    watcher_id = created_user.json()['user']['id']
    assigned = client.post(f'/api/projects/{project_id}/members', json={'user_id': watcher_id, 'role': 'Contributor'})
    assert assigned.status_code == 200

    task = client.post('/api/tasks', json={'title': 'Status watch target', 'workspace_id': ws_id, 'project_id': project_id})
    assert task.status_code == 200
    task_id = task.json()['id']

    from shared.core import append_event
    from shared.models import Notification, SessionLocal
    from shared.typed_notifications import NOTIFICATION_TYPE_WATCHED_TASK_STATUS_CHANGED

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=task_id,
            event_type='TaskWatchToggled',
            payload={'task_id': task_id, 'user_id': watcher_id, 'watched': True},
            metadata={'actor_id': watcher_id, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': task_id},
        )
        db.commit()

    patched = client.patch(f'/api/tasks/{task_id}', json={'status': 'In progress'})
    assert patched.status_code == 200

    with SessionLocal() as db:
        rows = db.execute(
            select(Notification).where(
                Notification.user_id == watcher_id,
                Notification.task_id == task_id,
                Notification.notification_type == NOTIFICATION_TYPE_WATCHED_TASK_STATUS_CHANGED,
            )
        ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.severity == "info"
    assert row.dedupe_key == f"watch-status:{task_id}:{watcher_id}:In progress:3"
    assert row.source_event == "TaskUpdated"


def test_task_automation_failed_notification_is_typed_and_dedupes(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    assignee_user = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'typed-auto-assignee', 'full_name': 'Typed Auto Assignee'},
    )
    watcher_user = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'typed-auto-watcher', 'full_name': 'Typed Auto Watcher'},
    )
    assert assignee_user.status_code == 200
    assert watcher_user.status_code == 200
    assignee_id = assignee_user.json()['user']['id']
    watcher_id = watcher_user.json()['user']['id']
    assert client.post(f'/api/projects/{project_id}/members', json={'user_id': assignee_id, 'role': 'Contributor'}).status_code == 200
    assert client.post(f'/api/projects/{project_id}/members', json={'user_id': watcher_id, 'role': 'Contributor'}).status_code == 200

    task = client.post(
        '/api/tasks',
        json={
            'title': 'Automation failure target',
            'workspace_id': ws_id,
            'project_id': project_id,
            'assignee_id': assignee_id,
        },
    )
    assert task.status_code == 200
    task_id = task.json()['id']

    from shared.core import append_event
    from shared.models import Notification, SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID
    from shared.typed_notifications import NOTIFICATION_TYPE_TASK_AUTOMATION_FAILED

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=task_id,
            event_type='TaskWatchToggled',
            payload={'task_id': task_id, 'user_id': watcher_id, 'watched': True},
            metadata={'actor_id': watcher_id, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': task_id},
        )
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=task_id,
            event_type='TaskAutomationFailed',
            payload={'failed_at': datetime.now(timezone.utc).isoformat(), 'error': 'Runner exploded', 'summary': 'Failed'},
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': task_id},
        )
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=task_id,
            event_type='TaskAutomationFailed',
            payload={'failed_at': datetime.now(timezone.utc).isoformat(), 'error': 'Runner exploded', 'summary': 'Failed'},
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': task_id},
        )
        db.commit()

    with SessionLocal() as db:
        rows = db.execute(
            select(Notification).where(
                Notification.task_id == task_id,
                Notification.notification_type == NOTIFICATION_TYPE_TASK_AUTOMATION_FAILED,
            )
        ).scalars().all()
    user_ids = {row.user_id for row in rows}
    assert user_ids == {assignee_id, watcher_id}
    assert len(rows) == 2
    assert all(row.severity == "warning" for row in rows)


def test_task_schedule_failed_notification_is_typed_and_dedupes(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    assignee_user = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'typed-sched-assignee', 'full_name': 'Typed Schedule Assignee'},
    )
    assert assignee_user.status_code == 200
    assignee_id = assignee_user.json()['user']['id']
    assert client.post(f'/api/projects/{project_id}/members', json={'user_id': assignee_id, 'role': 'Contributor'}).status_code == 200

    scheduled_at = datetime.now(timezone.utc) + timedelta(hours=2)
    task = client.post(
        '/api/tasks',
        json={
            'title': 'Schedule failure target',
            'workspace_id': ws_id,
            'project_id': project_id,
            'assignee_id': assignee_id,
            'task_type': 'scheduled_instruction',
            'scheduled_instruction': 'Run diagnostics',
            'scheduled_at_utc': scheduled_at.isoformat(),
        },
    )
    assert task.status_code == 200
    task_id = task.json()['id']

    from shared.core import append_event
    from shared.models import Notification, SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID
    from shared.typed_notifications import NOTIFICATION_TYPE_TASK_SCHEDULE_FAILED

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=task_id,
            event_type='TaskScheduleFailed',
            payload={'failed_at': datetime.now(timezone.utc).isoformat(), 'error': 'Schedule timeout'},
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': task_id},
        )
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=task_id,
            event_type='TaskScheduleFailed',
            payload={'failed_at': datetime.now(timezone.utc).isoformat(), 'error': 'Schedule timeout'},
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': task_id},
        )
        db.commit()

    with SessionLocal() as db:
        rows = db.execute(
            select(Notification).where(
                Notification.user_id == assignee_id,
                Notification.task_id == task_id,
                Notification.notification_type == NOTIFICATION_TYPE_TASK_SCHEDULE_FAILED,
            )
        ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.severity == "warning"
    assert row.payload_json and "scheduled_at_utc" in row.payload_json


def test_project_membership_changed_notification_is_typed(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created_user = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'typed-member-change', 'full_name': 'Typed Member Change'},
    )
    assert created_user.status_code == 200
    member_id = created_user.json()['user']['id']

    added = client.post(f'/api/projects/{project_id}/members', json={'user_id': member_id, 'role': 'Contributor'})
    assert added.status_code == 200
    removed = client.post(f'/api/projects/{project_id}/members/{member_id}/remove')
    assert removed.status_code == 200

    from shared.models import Notification, SessionLocal
    from shared.typed_notifications import NOTIFICATION_TYPE_PROJECT_MEMBERSHIP_CHANGED

    with SessionLocal() as db:
        rows = db.execute(
            select(Notification).where(
                Notification.user_id == member_id,
                Notification.project_id == project_id,
                Notification.notification_type == NOTIFICATION_TYPE_PROJECT_MEMBERSHIP_CHANGED,
            ).order_by(Notification.created_at.asc(), Notification.id.asc())
        ).scalars().all()
    assert len(rows) == 2
    assert rows[0].source_event == "ProjectMemberUpserted"
    assert rows[1].source_event == "ProjectMemberRemoved"


def test_license_grace_ending_soon_notification_is_typed_and_deduped(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']

    from shared.models import LicenseInstallation, Notification, SessionLocal
    from shared.typed_notifications import NOTIFICATION_TYPE_LICENSE_GRACE_ENDING_SOON

    with SessionLocal() as db:
        installation = db.execute(select(LicenseInstallation).order_by(LicenseInstallation.id.asc()).limit(1)).scalar_one()
        installation.trial_ends_at = datetime.now(timezone.utc) - timedelta(hours=1)
        installation.status = "grace"
        db.commit()

    emitted_first = trigger_system_notifications_for_user(user_id)
    emitted_second = trigger_system_notifications_for_user(user_id)
    assert emitted_first >= 1
    assert emitted_second == 0

    with SessionLocal() as db:
        rows = db.execute(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.notification_type == NOTIFICATION_TYPE_LICENSE_GRACE_ENDING_SOON,
            )
        ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.dedupe_key and row.dedupe_key.startswith("license-grace:")
    assert row.severity in {"warning", "critical"}


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


def test_mark_all_notifications_read(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    due_utc = datetime.now(timezone.utc) + timedelta(minutes=25)
    created = client.post(
        '/api/tasks',
        json={
            'title': 'Mark all notifications test',
            'workspace_id': ws_id,
            'project_id': project_id,
            'due_date': due_utc.isoformat(),
        },
    )
    assert created.status_code == 200

    emitted = trigger_system_notifications_for_user(user_id)
    assert emitted >= 1

    first = client.get('/api/notifications')
    assert first.status_code == 200
    unread_before = [item for item in first.json() if not item.get('is_read')]
    assert unread_before

    mark_all = client.post('/api/notifications/read-all')
    assert mark_all.status_code == 200
    payload = mark_all.json()
    assert payload['ok'] is True
    assert int(payload.get('updated', 0)) >= len(unread_before)

    second = client.get('/api/notifications')
    assert second.status_code == 200
    unread_after = [item for item in second.json() if not item.get('is_read')]
    assert unread_after == []


def test_command_id_idempotency_for_create_task(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    command_id = "cmd-create-task-001"

    first = client.post(
        '/api/tasks',
        json={'title': 'Idempotent create', 'workspace_id': ws_id, 'project_id': project_id},
        headers={'X-Command-Id': command_id},
    )
    second = client.post(
        '/api/tasks',
        json={'title': 'Idempotent create', 'workspace_id': ws_id, 'project_id': project_id},
        headers={'X-Command-Id': command_id},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()['id'] == second.json()['id']

    tasks = client.get(f'/api/tasks?workspace_id={ws_id}&project_id={project_id}&q=Idempotent create').json()['items']
    assert len(tasks) == 1


def test_metrics_endpoint_available(tmp_path):
    client = build_client(tmp_path)
    res = client.get('/api/metrics')
    assert res.status_code == 200
    payload = res.json()
    assert 'commands_total' in payload
    assert 'command_conflicts' in payload

    rag = client.get('/api/metrics/graph-rag')
    assert rag.status_code == 200
    rag_payload = rag.json()
    assert 'requests' in rag_payload
    assert 'grounded_claim_ratio_pct' in rag_payload
    assert 'context_latency_ms' in rag_payload
    assert 'with_summary' in rag_payload['context_latency_ms']
    assert 'without_summary' in rag_payload['context_latency_ms']


def test_local_snapshot_payload_has_schema_version(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    task = client.post('/api/tasks', json={'title': 'Snapshot schema test', 'workspace_id': ws_id, 'project_id': project_id}).json()

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
    project_id = bootstrap['projects'][0]['id']

    task = client.post('/api/tasks', json={'title': 'Automate me', 'workspace_id': ws_id, 'project_id': project_id}).json()
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
    project_id = bootstrap['projects'][0]['id']
    created = client.post('/api/tasks', json={'title': 'Agent task', 'workspace_id': ws_id, 'project_id': project_id}).json()

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


def test_task_automation_requested_event_wakes_runner(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    created = client.post('/api/tasks', json={'title': 'Wake runner task', 'workspace_id': ws_id, 'project_id': project_id}).json()

    import features.agents.runner as runner_module

    calls = {"count": 0}

    def fake_wake():
        calls["count"] += 1

    monkeypatch.setattr(runner_module, "wake_automation_runner", fake_wake)

    queued = client.post(f"/api/tasks/{created['id']}/automation/run", json={'instruction': 'wake check'})
    assert queued.status_code == 200
    assert calls["count"] >= 1


def test_runner_processes_queued_automation(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    task = client.post('/api/tasks', json={'title': 'Runner task', 'workspace_id': ws_id, 'project_id': project_id}).json()

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
    project_id = bootstrap['projects'][0]['id']
    task = client.post('/api/tasks', json={'title': 'Complete me', 'workspace_id': ws_id, 'project_id': project_id}).json()

    queued = client.post(f"/api/tasks/{task['id']}/automation/run", json={'instruction': '#complete'})
    assert queued.status_code == 200

    from features.agents.runner import run_queued_automation_once

    processed = run_queued_automation_once(limit=5)
    assert processed >= 1

    refreshed = client.get(f"/api/tasks?workspace_id={ws_id}&project_id={project_id}&q=Complete me")
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


def test_agent_service_blocks_write_when_license_is_expired(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    from shared.models import LicenseInstallation, SessionLocal

    with SessionLocal() as db:
        installation = db.execute(select(LicenseInstallation).order_by(LicenseInstallation.id.asc())).scalars().first()
        assert installation is not None
        installation.status = "trial"
        installation.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=10)
        db.commit()

    service = AgentTaskService()
    try:
        service.create_task(
            title='Should be blocked by license',
            workspace_id=ws_id,
            project_id=project_id,
            auth_token=svc_module.MCP_AUTH_TOKEN or None,
        )
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 402
        assert "License expired" in str(exc.detail)


def test_agent_service_allows_read_when_license_is_expired(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    from shared.models import LicenseInstallation, SessionLocal

    with SessionLocal() as db:
        installation = db.execute(select(LicenseInstallation).order_by(LicenseInstallation.id.asc())).scalars().first()
        assert installation is not None
        installation.status = "trial"
        installation.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=10)
        db.commit()

    service = AgentTaskService()
    payload = service.list_tasks(
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert isinstance(payload, dict)
    assert "items" in payload


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
    project_id = bootstrap['projects'][0]['id']
    task = client.post('/api/tasks', json={'title': 'Executor fail task', 'workspace_id': ws_id, 'project_id': project_id}).json()
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


def test_runner_marks_running_while_executor_is_in_progress(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    task = client.post('/api/tasks', json={'title': 'Slow executor task', 'workspace_id': ws_id, 'project_id': project_id}).json()
    queued = client.post(f"/api/tasks/{task['id']}/automation/run", json={'instruction': 'slow run'})
    assert queued.status_code == 200

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome

    entered_executor = threading.Event()
    release_executor = threading.Event()

    def slow_executor(**_kwargs):
        entered_executor.set()
        release_executor.wait(timeout=3)
        return AutomationOutcome(action='comment', summary='Slow run finished.', comment='done')

    monkeypatch.setattr(runner_module, "execute_task_automation", slow_executor)

    run_thread = threading.Thread(target=lambda: runner_module.run_queued_automation_once(limit=5), daemon=True)
    run_thread.start()

    assert entered_executor.wait(timeout=2), "Executor did not start in time"
    mid_status = client.get(f"/api/tasks/{task['id']}/automation")
    assert mid_status.status_code == 200
    assert mid_status.json()['automation_state'] == 'running'

    release_executor.set()
    run_thread.join(timeout=5)
    assert not run_thread.is_alive()

    final_status = client.get(f"/api/tasks/{task['id']}/automation")
    assert final_status.status_code == 200
    assert final_status.json()['automation_state'] == 'completed'


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
        task_type='scheduled_instruction',
        scheduled_instruction='Post current time in comment',
        scheduled_at_utc='2026-02-16T12:10:53+00:00',
        schedule_timezone='UTC',
        recurring_rule='every:1m',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert created['workspace_id'] == ws_id
    assert created['project_id'] == project['id']
    assert created['recurring_rule'] == 'every:1m'


def test_agent_service_create_task_accepts_json_string_execution_triggers(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    due_at = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    created = service.create_task(
        title='MCP JSON trigger create',
        workspace_id=ws_id,
        project_id=project_id,
        instruction='Write a status update note',
        execution_triggers=json.dumps(
            [
                {
                    'kind': 'schedule',
                    'enabled': True,
                    'scheduled_at_utc': due_at,
                    'schedule_timezone': 'UTC',
                    'run_on_statuses': ['In progress'],
                }
            ]
        ),
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert created['task_type'] == 'scheduled_instruction'
    assert any(trigger.get('kind') == 'schedule' for trigger in created['execution_triggers'])


def test_agent_service_update_task_accepts_json_string_execution_triggers(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    created = service.create_task(
        title='MCP JSON trigger update target',
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )

    updated = service.update_task(
        task_id=created['id'],
        patch={
            'instruction': 'Run checks when task is done',
            'execution_triggers': json.dumps(
                [
                    {
                        'kind': 'status_change',
                        'enabled': True,
                        'scope': 'self',
                        'match_mode': 'any',
                        'to_statuses': ['Done'],
                    }
                ]
            ),
        },
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    status_change = [trigger for trigger in updated['execution_triggers'] if trigger.get('kind') == 'status_change']
    assert len(status_change) == 1
    assert status_change[0].get('to_statuses') == ['Done']


def test_agent_service_update_task_accepts_execution_trigger_mapping_payload(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    created = service.create_task(
        title='MCP trigger mapping target',
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )

    updated = service.update_task(
        task_id=created['id'],
        patch={
            'instruction': 'Run checks when status changes',
            'execution_triggers': {
                'status_change': {
                    'enabled': True,
                    'scope': 'self',
                    'match_mode': 'any',
                    'to_statuses': ['Done'],
                }
            },
        },
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    status_change = [trigger for trigger in updated['execution_triggers'] if trigger.get('kind') == 'status_change']
    assert len(status_change) == 1
    assert status_change[0].get('to_statuses') == ['Done']


def test_agent_service_update_task_persists_status_change_direct_target_mapping(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    source = service.create_task(
        title='MCP direct mapping source',
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    target = service.create_task(
        title='MCP direct mapping target',
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )

    updated = service.update_task(
        task_id=source['id'],
        patch={
            'instruction': 'Run target task automation after completion',
            'execution_triggers': {
                'status_change': {
                    'enabled': True,
                    'scope': 'self',
                    'match_mode': 'any',
                    'to_statuses': ['Done'],
                    'action': 'run_automation',
                    'target_task_id': target['id'],
                }
            },
        },
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    status_change = [trigger for trigger in updated['execution_triggers'] if trigger.get('kind') == 'status_change']
    assert len(status_change) == 1
    assert status_change[0].get('action') == 'run_automation'
    assert status_change[0].get('target_task_id') == target['id']
    assert status_change[0].get('target_task_ids') == [target['id']]


def test_agent_service_update_task_scope_other_maps_to_external_with_source_task_ids(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    source = service.create_task(
        title='MCP scope other source',
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    target = service.create_task(
        title='MCP scope other target',
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )

    updated = service.update_task(
        task_id=target['id'],
        patch={
            'instruction': 'Run when dependency changes status',
            'execution_triggers': {
                'status_change': {
                    'enabled': True,
                    'scope': 'other',
                    'match_mode': 'any',
                    'source_task_ids': [source['id']],
                    'to_statuses': ['Done'],
                }
            },
        },
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    status_change = [trigger for trigger in updated['execution_triggers'] if trigger.get('kind') == 'status_change']
    assert len(status_change) == 1
    assert status_change[0].get('scope') == 'external'
    assert status_change[0].get('selector', {}).get('task_ids') == [source['id']]


def test_agent_service_create_task_is_idempotent_without_explicit_command_id(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    first = service.create_task(
        title='Idempotent MCP task',
        workspace_id=ws_id,
        project_id=project_id,
        description='same payload',
        priority='High',
        labels=['mcp', 'idempotent'],
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    second = service.create_task(
        title='Idempotent MCP task',
        workspace_id=ws_id,
        project_id=project_id,
        description='same payload',
        priority='High',
        labels=['mcp', 'idempotent'],
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )

    assert first['id'] == second['id']
    listed = service.list_tasks(
        workspace_id=ws_id,
        project_id=project_id,
        q='Idempotent MCP task',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert len([item for item in listed['items'] if item['title'] == 'Idempotent MCP task']) == 1


def test_agent_service_create_note_is_idempotent_without_explicit_command_id(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    first = service.create_note(
        title='Idempotent MCP note',
        body='same payload',
        workspace_id=ws_id,
        project_id=project_id,
        tags=['mcp', 'idempotent'],
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    second = service.create_note(
        title='Idempotent MCP note',
        body='same payload',
        workspace_id=ws_id,
        project_id=project_id,
        tags=['mcp', 'idempotent'],
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )

    assert first['id'] == second['id']
    listed = service.list_notes(
        workspace_id=ws_id,
        project_id=project_id,
        q='Idempotent MCP note',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert len([item for item in listed['items'] if item['title'] == 'Idempotent MCP note']) == 1


def test_agent_service_can_toggle_my_theme(tmp_path):
    build_client(tmp_path)

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    before = service.get_my_preferences(auth_token=svc_module.MCP_AUTH_TOKEN or None)
    first_toggle = service.toggle_my_theme(
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id='test-mcp-theme-toggle-1',
    )
    second_toggle = service.toggle_my_theme(
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id='test-mcp-theme-toggle-2',
    )

    assert before['theme'] in {'light', 'dark'}
    assert first_toggle['theme'] in {'light', 'dark'}
    assert first_toggle['theme'] != before['theme']
    assert second_toggle['theme'] == before['theme']

    refreshed = service.get_my_preferences(auth_token=svc_module.MCP_AUTH_TOKEN or None)
    assert refreshed['theme'] == before['theme']


def test_agent_service_can_set_my_theme(tmp_path):
    build_client(tmp_path)

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    to_dark = service.set_my_theme(
        theme='dark',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id='test-mcp-theme-set-dark',
    )
    assert to_dark['theme'] == 'dark'

    to_light = service.set_my_theme(
        theme='light',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id='test-mcp-theme-set-light',
    )
    assert to_light['theme'] == 'light'


def test_ui_and_mcp_theme_updates_follow_same_gateway_path(tmp_path):
    client = build_client(tmp_path)

    ui_updated = client.patch('/api/me/preferences', json={'theme': 'dark'})
    assert ui_updated.status_code == 200
    assert ui_updated.json()['theme'] == 'dark'

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    mcp_updated = service.set_my_theme(
        theme='light',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id='test-mcp-theme-to-light-after-ui-dark',
    )
    assert mcp_updated['theme'] == 'light'

    refreshed = client.get('/api/bootstrap')
    assert refreshed.status_code == 200
    assert refreshed.json()['current_user']['theme'] == 'light'


def test_notifications_stream_emits_refresh_when_user_state_changes_without_signal(tmp_path, monkeypatch):
    client = build_client(tmp_path)

    import features.notifications.api as notifications_api
    from shared.models import SessionLocal, User

    class DummyRequest:
        def __init__(self):
            self.calls = 0

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 4

    class DummySubscription:
        async def get(self):
            await asyncio.sleep(999)

        def close(self):
            return None

    monkeypatch.setattr(notifications_api.realtime_hub, 'subscribe', lambda channels: DummySubscription())  # noqa: ARG005

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.username == 'admin')).scalar_one()
        user_id = user.id
        before_theme = user.theme

    wait_calls = {'count': 0}
    toggled = {'done': False}

    async def fake_wait_for_signal(subscription, timeout_seconds):  # noqa: ARG001
        _ = subscription
        wait_calls['count'] += 1
        if not toggled['done']:
            with SessionLocal() as db:
                target = db.get(User, user_id)
                target.theme = 'dark' if target.theme != 'dark' else 'light'
                db.commit()
            toggled['done'] = True
        raise asyncio.TimeoutError()

    monkeypatch.setattr(notifications_api, '_wait_for_signal', fake_wait_for_signal)

    async def consume_stream_once():
        with SessionLocal() as db:
            local_user = db.get(User, user_id)
            response = await notifications_api.notifications_stream(
                request=DummyRequest(),
                last_id=None,
                workspace_id=None,
                last_activity_id=0,
                db=db,
                user=local_user,
            )
            async for raw_chunk in response.body_iterator:
                chunk = raw_chunk.decode() if isinstance(raw_chunk, (bytes, bytearray)) else str(raw_chunk)
                if 'event: task_event' in chunk and 'data: {}' in chunk:
                    return chunk
        return ''

    first_chunk = asyncio.run(consume_stream_once())

    assert wait_calls['count'] >= 1
    assert toggled['done'] is True
    assert 'event: task_event' in first_chunk
    assert 'data: {}' in first_chunk

    refreshed_theme = client.get('/api/bootstrap').json()['current_user']['theme']
    assert refreshed_theme != before_theme


def test_notifications_stream_emits_refresh_on_mark_read_signal(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    due_utc = datetime.now(timezone.utc) + timedelta(minutes=30)

    created = client.post(
        '/api/tasks',
        json={'title': 'Stream mark-read signal', 'workspace_id': ws_id, 'project_id': project_id, 'due_date': due_utc.isoformat()},
    )
    assert created.status_code == 200

    emitted = trigger_system_notifications_for_user(user_id)
    assert emitted >= 1

    notes = client.get('/api/notifications')
    assert notes.status_code == 200
    notification_id = notes.json()[0]['id']

    import features.notifications.api as notifications_api
    from features.notifications.application import NotificationApplicationService
    from shared.models import SessionLocal, User

    original_wait_for_signal = notifications_api._wait_for_signal

    async def short_wait_for_signal(subscription, timeout_seconds):  # noqa: ARG001
        await original_wait_for_signal(subscription, timeout_seconds=1.0)

    monkeypatch.setattr(notifications_api, '_wait_for_signal', short_wait_for_signal)

    class DummyRequest:
        def __init__(self):
            self.calls = 0

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 8

    async def mark_read_later():
        await asyncio.sleep(0.05)
        with SessionLocal() as db:
            local_user = db.get(User, user_id)
            assert local_user is not None
            result = NotificationApplicationService(
                db,
                local_user,
                command_id='test-stream-mark-read-signal',
            ).mark_read(notification_id)
            assert result['ok'] is True

    async def consume_stream_once():
        mark_task = asyncio.create_task(mark_read_later())
        try:
            with SessionLocal() as db:
                local_user = db.get(User, user_id)
                assert local_user is not None
                response = await notifications_api.notifications_stream(
                    request=DummyRequest(),
                    last_id=notification_id,
                    workspace_id=None,
                    last_activity_id=0,
                    db=db,
                    user=local_user,
                )
                async for raw_chunk in response.body_iterator:
                    chunk = raw_chunk.decode() if isinstance(raw_chunk, (bytes, bytearray)) else str(raw_chunk)
                    if 'event: task_event' in chunk and 'data: {}' in chunk:
                        return chunk
            return ''
        finally:
            await mark_task

    first_chunk = asyncio.run(consume_stream_once())
    assert 'event: task_event' in first_chunk
    assert 'data: {}' in first_chunk

    refreshed = client.get('/api/notifications')
    assert refreshed.status_code == 200
    marked = next(item for item in refreshed.json() if item['id'] == notification_id)
    assert marked['is_read'] is True


def test_notifications_stream_defaults_to_tail_and_does_not_replay_history(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    now = datetime.now(timezone.utc)

    import features.notifications.api as notifications_api
    from shared.models import Notification, SessionLocal, User

    with SessionLocal() as db:
        seeded = Notification(
            user_id=user_id,
            workspace_id=ws_id,
            project_id=project_id,
            message='Existing notification before stream connect',
            created_at=now,
            updated_at=now,
        )
        db.add(seeded)
        db.commit()
        seeded_id = seeded.id

    original_wait_for_signal = notifications_api._wait_for_signal

    async def short_wait_for_signal(subscription, timeout_seconds):  # noqa: ARG001
        await original_wait_for_signal(subscription, timeout_seconds=0.01)

    monkeypatch.setattr(notifications_api, '_wait_for_signal', short_wait_for_signal)

    class DummyRequest:
        headers = {}

        def __init__(self):
            self.calls = 0

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 4

    async def consume_first_chunk():
        with SessionLocal() as db:
            local_user = db.get(User, user_id)
            assert local_user is not None
            response = await notifications_api.notifications_stream(
                request=DummyRequest(),
                last_id=None,
                workspace_id=None,
                last_activity_id=0,
                db=db,
                user=local_user,
            )
            async for raw_chunk in response.body_iterator:
                chunk = raw_chunk.decode() if isinstance(raw_chunk, (bytes, bytearray)) else str(raw_chunk)
                if chunk.strip():
                    return chunk
        return ''

    first_chunk = asyncio.run(consume_first_chunk())

    assert 'event: notification' not in first_chunk
    assert seeded_id not in first_chunk


def test_notifications_stream_resumes_from_last_event_id_header(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    now = datetime.now(timezone.utc)

    import features.notifications.api as notifications_api
    from shared.models import Notification, SessionLocal, User

    with SessionLocal() as db:
        first = Notification(
            user_id=user_id,
            workspace_id=ws_id,
            project_id=project_id,
            message='Resume cursor first',
            created_at=now,
            updated_at=now,
        )
        second = Notification(
            user_id=user_id,
            workspace_id=ws_id,
            project_id=project_id,
            message='Resume cursor second',
            created_at=now + timedelta(seconds=1),
            updated_at=now + timedelta(seconds=1),
        )
        db.add_all([first, second])
        db.commit()
        first_id = first.id
        second_id = second.id

    class DummyRequest:
        def __init__(self, last_event_id: str):
            self.calls = 0
            self.headers = {'last-event-id': last_event_id}

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 3

    async def consume_first_notification():
        with SessionLocal() as db:
            local_user = db.get(User, user_id)
            assert local_user is not None
            response = await notifications_api.notifications_stream(
                request=DummyRequest(first_id),
                last_id=None,
                workspace_id=None,
                last_activity_id=0,
                db=db,
                user=local_user,
            )
            async for raw_chunk in response.body_iterator:
                chunk = raw_chunk.decode() if isinstance(raw_chunk, (bytes, bytearray)) else str(raw_chunk)
                if 'event: notification' in chunk:
                    return chunk
        return ''

    first_notification_chunk = asyncio.run(consume_first_notification())

    assert f'id: {second_id}' in first_notification_chunk
    assert 'Resume cursor second' in first_notification_chunk
    assert f'id: {first_id}' not in first_notification_chunk


def test_notifications_stream_init_is_read_only_and_does_not_emit_system_notifications(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    due_utc = datetime.now(timezone.utc) + timedelta(minutes=30)

    created = client.post(
        '/api/tasks',
        json={'title': 'Read-only stream init', 'workspace_id': ws_id, 'project_id': project_id, 'due_date': due_utc.isoformat()},
    )
    assert created.status_code == 200

    from shared.models import Notification, SessionLocal, User
    import features.notifications.api as notifications_api

    class ImmediateDisconnectRequest:
        async def is_disconnected(self):
            return True

    with SessionLocal() as db:
        before_rows = db.execute(select(Notification).where(Notification.user_id == user_id)).scalars().all()
    assert before_rows == []

    async def connect_and_disconnect():
        with SessionLocal() as db:
            local_user = db.get(User, user_id)
            response = await notifications_api.notifications_stream(
                request=ImmediateDisconnectRequest(),
                last_id=None,
                workspace_id=None,
                last_activity_id=0,
                db=db,
                user=local_user,
            )
            async for _ in response.body_iterator:
                break

    asyncio.run(connect_and_disconnect())

    with SessionLocal() as db:
        after_rows = db.execute(select(Notification).where(Notification.user_id == user_id)).scalars().all()
    assert len(after_rows) == 0


def test_agent_service_theme_without_user_id_targets_primary_user(tmp_path):
    build_client(tmp_path)

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    bot_user_id = '00000000-0000-0000-0000-000000000099'

    service.set_my_theme(
        theme='dark',
        user_id=bot_user_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id='test-mcp-theme-bot-dark',
    )
    service.set_my_theme(
        theme='dark',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id='test-mcp-theme-primary-dark',
    )

    primary = service.set_my_theme(
        theme='light',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id='test-mcp-theme-primary-light',
    )
    bot = service.get_my_preferences(
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        user_id=bot_user_id,
    )

    assert primary['id'] == svc_module.DEFAULT_USER_ID
    assert primary['theme'] == 'light'
    assert bot['id'] == bot_user_id
    assert bot['theme'] == 'dark'


def test_agent_service_explicit_cross_user_theme_requires_admin(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']

    from fastapi import HTTPException
    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    from shared.models import SessionLocal, User, WorkspaceMember

    member_user_id = '00000000-0000-0000-0000-000000000222'
    with SessionLocal() as db:
        if not db.get(User, member_user_id):
            db.add(User(id=member_user_id, username='member-user', full_name='Member User', user_type='human'))
        membership = db.query(WorkspaceMember).filter_by(
            workspace_id=ws_id,
            user_id=member_user_id,
        ).first()
        if not membership:
            db.add(
                WorkspaceMember(
                    workspace_id=ws_id,
                    user_id=member_user_id,
                    role='Member',
                )
            )
        else:
            membership.role = 'Member'
        db.commit()

    monkeypatch.setattr(svc_module, 'MCP_ACTOR_USER_ID', member_user_id)
    service = AgentTaskService()

    try:
        service.set_my_theme(
            theme='dark',
            user_id=svc_module.DEFAULT_USER_ID,
            auth_token=svc_module.MCP_AUTH_TOKEN or None,
            command_id='test-mcp-theme-cross-user-denied',
        )
        assert False, 'Expected HTTPException'
    except HTTPException as exc:
        assert exc.status_code == 403
        assert 'Admin access required' in exc.detail


def test_agent_service_rejects_invalid_set_my_theme_value(tmp_path):
    build_client(tmp_path)

    from fastapi import HTTPException
    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    try:
        service.set_my_theme(theme='blue', auth_token=svc_module.MCP_AUTH_TOKEN or None)
        assert False, 'Expected HTTPException'
    except HTTPException as exc:
        assert exc.status_code == 422
        assert 'theme must be one of' in exc.detail


def test_agent_service_set_my_theme_does_not_replay_stale_llm_command_id(tmp_path):
    build_client(tmp_path)

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    shared_command_id = 'test-shared-theme-command-id'

    first = service.set_my_theme(
        theme='dark',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id=shared_command_id,
    )
    transition = service.set_my_theme(
        theme='light',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id='test-transition-theme-command-id',
    )
    second = service.set_my_theme(
        theme='dark',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id=shared_command_id,
    )
    refreshed = service.get_my_preferences(auth_token=svc_module.MCP_AUTH_TOKEN or None)

    assert first['theme'] == 'dark'
    assert transition['theme'] == 'light'
    assert second['theme'] == 'dark'
    assert refreshed['theme'] == 'dark'


def test_agent_service_task_note_group_lifecycle_and_filters(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    task_group = service.create_task_group(
        name='MCP Task Group',
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    note_group = service.create_note_group(
        name='MCP Note Group',
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )

    created_task = service.create_task(
        title='Task with group from MCP',
        workspace_id=ws_id,
        project_id=project_id,
        task_group_id=task_group['id'],
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    created_note = service.create_note(
        title='Note with group from MCP',
        workspace_id=ws_id,
        project_id=project_id,
        note_group_id=note_group['id'],
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert created_task['task_group_id'] == task_group['id']
    assert created_note['note_group_id'] == note_group['id']

    listed_tasks = service.list_tasks(
        workspace_id=ws_id,
        project_id=project_id,
        task_group_id=task_group['id'],
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    listed_notes = service.list_notes(
        workspace_id=ws_id,
        project_id=project_id,
        note_group_id=note_group['id'],
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert any(item['id'] == created_task['id'] for item in listed_tasks['items'])
    assert any(item['id'] == created_note['id'] for item in listed_notes['items'])

    second_task_group = service.create_task_group(
        name='MCP Task Group B',
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    reordered = service.reorder_task_groups(
        ordered_ids=[second_task_group['id'], task_group['id']],
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert reordered['ok'] is True

    task_groups = service.list_task_groups(
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )['items']
    assert [item['id'] for item in task_groups[:2]] == [second_task_group['id'], task_group['id']]

    deleted = service.delete_task_group(group_id=task_group['id'], auth_token=svc_module.MCP_AUTH_TOKEN or None)
    assert deleted['ok'] is True
    refreshed = service.get_task(task_id=created_task['id'], auth_token=svc_module.MCP_AUTH_TOKEN or None)
    assert refreshed['task_group_id'] is None


def test_agent_service_create_task_requires_project_id(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']

    from fastapi import HTTPException
    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", "")
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})

    service = AgentTaskService()
    try:
        service.create_task(title='Missing project')
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400


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


def test_agent_service_search_project_knowledge(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})
    monkeypatch.setattr(
        svc_module,
        "search_project_knowledge_query",
        lambda project_id, query, focus_entity_type=None, focus_entity_id=None, limit=20: {
            "project_id": project_id,
            "query": query,
            "mode": "graph+vector",
            "items": [{"rank": 1, "entity_type": "Task", "entity_id": "x"}],
        },
    )

    service = AgentTaskService()
    payload = service.search_project_knowledge(
        project_id=project_id,
        query='command contracts',
    )
    assert payload['project_id'] == project_id
    assert payload['mode'] == 'graph+vector'
    assert payload['items'][0]['entity_type'] == 'Task'


def test_agent_service_get_project_chat_context_by_id(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(
        svc_module,
        "build_graph_context_pack",
        lambda **_: {
            "markdown": "## Graph\nTask A IMPLEMENTS Spec B",
            "evidence": [{"evidence_id": "E1", "claim": "Task A implements Spec B"}],
            "summary": {
                "executive": "Graph summary",
                "key_points": [{"claim": "Task A implements Spec B", "evidence_ids": ["E1"]}],
            },
        },
    )

    service = AgentTaskService()
    payload = service.get_project_chat_context(
        project_ref=project_id,
        workspace_id=ws_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert payload['project_id'] == project_id
    assert payload['resolved_by'] == 'id'
    assert payload['workspace_id'] == ws_id
    assert 'Soul.md' in payload['context_pack_markdown']
    assert 'ProjectRules.md' in payload['context_pack_markdown']
    assert 'ProjectSkills.md' in payload['context_pack_markdown']
    assert 'Task A IMPLEMENTS Spec B' in payload['context_pack']['graph_context_md']
    assert any('get_project_chat_context' in item for item in payload['refresh_policy'])


def test_agent_service_get_project_chat_context_by_name(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Context By Name Project'}).json()

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(
        svc_module,
        "build_graph_context_pack",
        lambda **_: {"markdown": "", "evidence": [], "summary": None},
    )

    service = AgentTaskService()
    payload = service.get_project_chat_context(
        project_ref=project['name'],
        workspace_id=ws_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert payload['project_id'] == project['id']
    assert payload['resolved_by'] == 'name'
    assert payload['project_name'] == project['name']


def test_agent_service_get_project_chat_context_rejects_ambiguous_name(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    user_id = bootstrap['current_user']['id']
    shared_name = 'Duplicate Context Project'
    first = client.post('/api/projects', json={'workspace_id': ws_id, 'name': shared_name}).json()

    from uuid import uuid4
    from shared.core import SessionLocal, Workspace, WorkspaceMember
    with SessionLocal() as db:
        second_workspace_id = str(uuid4())
        db.add(Workspace(id=second_workspace_id, name='Second Workspace', type='team'))
        db.add(WorkspaceMember(workspace_id=second_workspace_id, user_id=user_id, role='Owner'))
        db.commit()
    second = client.post('/api/projects', json={'workspace_id': second_workspace_id, 'name': shared_name}).json()
    assert first['id'] != second['id']

    from fastapi import HTTPException
    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id, second_workspace_id})
    service = AgentTaskService()
    try:
        service.get_project_chat_context(
            project_ref=shared_name,
            workspace_id=None,
            auth_token=svc_module.MCP_AUTH_TOKEN or None,
        )
        assert False, 'Expected HTTPException for ambiguous project name'
    except HTTPException as exc:
        assert exc.status_code == 409
        assert 'multiple projects match' in str(exc.detail).lower()


def test_workspace_activity_cursor_read_model_returns_new_rows(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    created = client.post('/api/tasks', json={'title': 'Activity SSE seed', 'workspace_id': ws_id, 'project_id': project_id})
    assert created.status_code == 200

    from shared.models import SessionLocal
    from features.notifications.read_models import list_workspace_activity_after_id_read_model

    with SessionLocal() as db:
        items = list_workspace_activity_after_id_read_model(db, ws_id, cursor=0, limit=200)
        assert any(item['task_id'] == created.json()['id'] for item in items)


def test_agents_chat_endpoint_returns_executor_response(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
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


def test_agents_chat_endpoint_returns_codex_session_id_when_available(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    monkeypatch.setattr(
        agents_api,
        'execute_task_automation',
        lambda **_: AutomationOutcome(
            action='comment',
            summary='ok',
            comment=None,
            usage=None,
            codex_session_id='thread-123',
        ),
    )

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Return session id',
            'session_id': 'test-session-2',
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload['ok'] is True
    assert payload['codex_session_id'] == 'thread-123'
    assert payload['resume_attempted'] is False
    assert payload['resume_succeeded'] is False
    assert payload['resume_fallback_used'] is False


def test_agents_chat_endpoint_links_created_resources_to_assistant_message(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome
    from features.agents.service import AgentTaskService

    def _fake_execute_task_automation(**_kwargs):
        service = AgentTaskService()
        service.create_task(
            workspace_id=ws_id,
            project_id=project_id,
            title='Chat-linked task',
        )
        service.create_note(
            workspace_id=ws_id,
            project_id=project_id,
            title='Chat-linked note',
            body='Created during chat run.',
        )
        return AutomationOutcome(action='comment', summary='Created resources', comment='linked', usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Create a task and a note',
            'session_id': 'chat-resource-linking-session',
            'history': [],
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload['ok'] is True

    from shared.models import ChatMessage, ChatMessageResourceLink, ChatSession, SessionLocal

    with SessionLocal() as db:
        session = (
            db.query(ChatSession)
            .filter(ChatSession.workspace_id == ws_id, ChatSession.session_key == 'chat-resource-linking-session')
            .first()
        )
        assert session is not None
        assistant = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session.id, ChatMessage.role == 'assistant')
            .order_by(ChatMessage.order_index.desc())
            .first()
        )
        assert assistant is not None
        links = (
            db.query(ChatMessageResourceLink)
            .filter(ChatMessageResourceLink.session_id == session.id, ChatMessageResourceLink.message_id == assistant.id)
            .all()
        )
        assert len(links) >= 2
        linked_types = {str(link.resource_type) for link in links}
        assert 'task' in linked_types
        assert 'note' in linked_types


def test_agents_chat_endpoint_normalizes_selected_mcp_servers(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents import mcp_registry
    from features.agents.executor import AutomationOutcome

    captured: dict[str, object] = {}

    def _fake_execute_task_automation(**kwargs):
        captured.update(kwargs)
        return AutomationOutcome(action='comment', summary='ok', comment=None, usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)
    monkeypatch.setattr(
        mcp_registry,
        '_get_rows',
        lambda force_refresh=False: [
            {
                'name': 'task-management-tools',
                'display_name': 'Task Management Tools',
                'enabled': True,
                'disabled_reason': None,
                'auth_status': None,
                'config': {'url': 'http://mcp-tools:8091/mcp'},
            },
            {
                'name': 'jira',
                'display_name': 'Jira',
                'enabled': True,
                'disabled_reason': None,
                'auth_status': None,
                'config': {'url': 'http://jira-mcp:9000/mcp'},
            },
            {
                'name': 'github',
                'display_name': 'GitHub',
                'enabled': True,
                'disabled_reason': None,
                'auth_status': None,
                'config': {'url': 'https://api.githubcopilot.com/mcp/'},
            },
        ],
    )

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Use selected MCP servers',
            'mcp_servers': ['jira', 'github', 'jira'],
        },
    )
    assert res.status_code == 200
    assert captured['mcp_servers'] == ['task-management-tools', 'jira', 'github']


def test_agents_chat_endpoint_skips_disabled_mcp_servers_from_defaults(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents import mcp_registry
    from features.agents.executor import AutomationOutcome

    captured: dict[str, object] = {}

    def _fake_execute_task_automation(**kwargs):
        captured.update(kwargs)
        return AutomationOutcome(action='comment', summary='ok', comment=None, usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)
    monkeypatch.setattr(
        mcp_registry,
        '_get_rows',
        lambda force_refresh=False: [
            {
                'name': 'task-management-tools',
                'display_name': 'Task Management Tools',
                'enabled': True,
                'disabled_reason': None,
                'auth_status': None,
                'config': {'url': 'http://mcp-tools:8091/mcp'},
            },
            {
                'name': 'jira',
                'display_name': 'Jira',
                'enabled': False,
                'disabled_reason': 'disabled in codex config',
                'auth_status': None,
                'config': {'url': 'http://jira-mcp:9000/mcp'},
            },
            {
                'name': 'github',
                'display_name': 'GitHub',
                'enabled': True,
                'disabled_reason': None,
                'auth_status': None,
                'config': {'url': 'https://api.githubcopilot.com/mcp/'},
            },
        ],
    )

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Use default MCP servers',
        },
    )
    assert res.status_code == 200
    assert captured['mcp_servers'] == ['task-management-tools', 'github']


def test_mcp_registry_honors_disabled_flag_from_config_when_runtime_list_unavailable(monkeypatch):
    from features.agents import mcp_registry

    monkeypatch.setattr(
        mcp_registry,
        "_load_mcp_servers_from_config",
        lambda: {
            "task-management-tools": {"url": "http://localhost:8091/mcp"},
            "github": {"url": "https://api.githubcopilot.com/mcp/", "enabled": False},
            "jira": {"url": "http://jira-mcp:9000/mcp", "enabled": False},
        },
    )
    monkeypatch.setattr(mcp_registry, "_run_codex_mcp_list_json", lambda: [])

    rows = mcp_registry._discover_rows_uncached()
    by_name = {str(row.get("name") or ""): row for row in rows}

    assert by_name["task-management-tools"]["enabled"] is True
    assert by_name["github"]["enabled"] is False
    assert by_name["jira"]["enabled"] is False


def test_agents_chat_endpoint_rejects_invalid_mcp_server(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    from features.agents import mcp_registry

    monkeypatch.setattr(
        mcp_registry,
        '_get_rows',
        lambda force_refresh=False: [
            {
                'name': 'jira',
                'display_name': 'Jira',
                'enabled': True,
                'disabled_reason': None,
                'auth_status': None,
                'config': {'url': 'http://jira-mcp:9000/mcp'},
            },
            {
                'name': 'github',
                'display_name': 'GitHub',
                'enabled': True,
                'disabled_reason': None,
                'auth_status': None,
                'config': {'url': 'https://api.githubcopilot.com/mcp/'},
            },
        ],
    )

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Invalid MCP server',
            'mcp_servers': ['invalid-server'],
        },
    )
    assert res.status_code == 400
    assert 'unsupported mcp server' in res.text.lower()


def test_agents_chat_endpoint_includes_text_attachment_context(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    uploaded = client.post(
        '/api/attachments/upload',
        data={'workspace_id': ws_id, 'project_id': project_id},
        files={'file': ('context.txt', BytesIO(b'hello from attachment file'), 'text/plain')},
    )
    assert uploaded.status_code == 200
    attachment_ref = uploaded.json()

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    captured = {}

    def _fake_execute_task_automation(**kwargs):
        captured.update(kwargs)
        return AutomationOutcome(action='comment', summary='ok', comment=None, usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Use attachment content',
            'session_id': 'chat-attachment-test',
            'history': [],
            'attachment_refs': [attachment_ref],
        },
    )
    assert res.status_code == 200
    assert 'Attached file context:' in captured['instruction']
    assert 'hello from attachment file' in captured['instruction']
    assert attachment_ref['path'] in captured['instruction']
    assert captured['actor_user_id'] == bootstrap['current_user']['id']

    from shared.models import ChatAttachment, SessionLocal

    with SessionLocal() as db:
        attachment = (
            db.query(ChatAttachment)
            .filter(ChatAttachment.workspace_id == ws_id, ChatAttachment.path == attachment_ref['path'])
            .order_by(ChatAttachment.created_at.desc())
            .first()
        )
        assert attachment is not None
        assert attachment.extraction_status in {'extracted', 'truncated'}
        assert 'hello from attachment file' in str(attachment.extracted_text or '')


def test_chat_session_context_patch_persists_session_attachments(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    session_id = 'chat-session-context-patch-test'

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    monkeypatch.setattr(
        agents_api,
        'execute_task_automation',
        lambda **_: AutomationOutcome(action='comment', summary='ok', comment=None, usage=None),
    )

    created = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Create session for context patch',
            'session_id': session_id,
            'history': [],
        },
    )
    assert created.status_code == 200

    uploaded = client.post(
        '/api/attachments/upload',
        data={'workspace_id': ws_id, 'project_id': project_id},
        files={'file': ('session-pin.txt', BytesIO(b'session pinned file body'), 'text/plain')},
    )
    assert uploaded.status_code == 200
    attachment_ref = uploaded.json()

    patched = client.patch(
        f'/api/chat/sessions/{session_id}',
        json={
            'workspace_id': ws_id,
            'session_attachment_refs': [attachment_ref],
        },
    )
    assert patched.status_code == 200
    patched_payload = patched.json()
    assert patched_payload['id'] == session_id
    assert patched_payload['session_attachment_refs'][0]['path'] == attachment_ref['path']

    listed = client.get(
        '/api/chat/sessions',
        params={'workspace_id': ws_id},
    )
    assert listed.status_code == 200
    sessions = listed.json()
    target = next((item for item in sessions if item.get('id') == session_id), None)
    assert target is not None
    assert target['session_attachment_refs'][0]['path'] == attachment_ref['path']


def test_chat_session_context_patch_updates_mcp_servers_without_clearing_attachments(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    session_id = 'chat-session-context-mcp-patch-test'

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    monkeypatch.setattr(
        agents_api,
        'execute_task_automation',
        lambda **_: AutomationOutcome(action='comment', summary='ok', comment=None, usage=None),
    )

    created = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Create session for MCP context patch',
            'session_id': session_id,
            'history': [],
        },
    )
    assert created.status_code == 200

    uploaded = client.post(
        '/api/attachments/upload',
        data={'workspace_id': ws_id, 'project_id': project_id},
        files={'file': ('session-mcp-pin.txt', BytesIO(b'session pinned mcp file body'), 'text/plain')},
    )
    assert uploaded.status_code == 200
    attachment_ref = uploaded.json()

    patched_attachments = client.patch(
        f'/api/chat/sessions/{session_id}',
        json={
            'workspace_id': ws_id,
            'session_attachment_refs': [attachment_ref],
        },
    )
    assert patched_attachments.status_code == 200
    assert patched_attachments.json()['session_attachment_refs'][0]['path'] == attachment_ref['path']

    patched_mcp = client.patch(
        f'/api/chat/sessions/{session_id}',
        json={
            'workspace_id': ws_id,
            'mcp_servers': ['task-management-tools'],
        },
    )
    assert patched_mcp.status_code == 200
    patched_payload = patched_mcp.json()
    assert patched_payload['mcp_servers'] == ['task-management-tools']
    assert patched_payload['session_attachment_refs'][0]['path'] == attachment_ref['path']

    listed = client.get(
        '/api/chat/sessions',
        params={'workspace_id': ws_id},
    )
    assert listed.status_code == 200
    sessions = listed.json()
    target = next((item for item in sessions if item.get('id') == session_id), None)
    assert target is not None
    assert target['mcp_servers'] == ['task-management-tools']
    assert target['session_attachment_refs'][0]['path'] == attachment_ref['path']


def test_chat_sessions_and_state_are_user_scoped(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    session_id = 'chat-user-scope-session'

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    monkeypatch.setattr(
        agents_api,
        'execute_task_automation',
        lambda **_: AutomationOutcome(action='comment', summary='ok', comment=None, usage=None),
    )

    owner_created = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Owner creates session',
            'session_id': session_id,
        },
    )
    assert owner_created.status_code == 200

    created_user = client.post(
        '/api/admin/users',
        json={
            'workspace_id': ws_id,
            'username': 'chat-member-user',
            'full_name': 'Chat Member User',
        },
    )
    assert created_user.status_code == 200
    member_id = created_user.json()['user']['id']
    temp_password = created_user.json()['temporary_password']

    assigned = client.post(
        f'/api/projects/{project_id}/members',
        json={'user_id': member_id, 'role': 'Contributor'},
    )
    assert assigned.status_code == 200

    logout = client.post('/api/auth/logout')
    assert logout.status_code == 200

    login_member = client.post(
        '/api/auth/login',
        json={'username': 'chat-member-user', 'password': temp_password},
    )
    assert login_member.status_code == 200
    assert login_member.json()['user']['must_change_password'] is True

    changed = client.post(
        '/api/auth/change-password',
        json={'current_password': temp_password, 'new_password': 'memberpass1'},
    )
    assert changed.status_code == 200
    assert changed.json()['user']['must_change_password'] is False

    listed = client.get('/api/chat/sessions', params={'workspace_id': ws_id})
    assert listed.status_code == 200
    assert all(item.get('id') != session_id for item in listed.json())

    reused = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Attempt to reuse owner session',
            'session_id': session_id,
        },
    )
    assert reused.status_code == 403
    assert 'belongs to another user' in reused.text.lower()


def test_agents_chat_endpoint_uses_persisted_session_attachment_context(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    session_id = 'chat-session-context-auto-load-test'

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    captured: dict[str, object] = {}

    def _fake_execute_task_automation(**kwargs):
        captured.update(kwargs)
        return AutomationOutcome(action='comment', summary='ok', comment=None, usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)

    created = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Create session for persisted attachment context',
            'session_id': session_id,
            'history': [],
        },
    )
    assert created.status_code == 200

    uploaded = client.post(
        '/api/attachments/upload',
        data={'workspace_id': ws_id, 'project_id': project_id},
        files={'file': ('session-auto.txt', BytesIO(b'autoloaded session attachment text'), 'text/plain')},
    )
    assert uploaded.status_code == 200
    attachment_ref = uploaded.json()

    patched = client.patch(
        f'/api/chat/sessions/{session_id}',
        json={
            'workspace_id': ws_id,
            'session_attachment_refs': [attachment_ref],
        },
    )
    assert patched.status_code == 200

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Use session-pinned file only',
            'session_id': session_id,
            'history': [],
        },
    )
    assert res.status_code == 200
    instruction = str(captured.get('instruction') or '')
    assert 'Attached file context:' in instruction
    assert 'autoloaded session attachment text' in instruction
    assert attachment_ref['path'] in instruction


def test_agents_chat_stream_endpoint_persists_attachment_without_fk_error(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    uploaded = client.post(
        '/api/attachments/upload',
        data={'workspace_id': ws_id, 'project_id': project_id},
        files={'file': ('stream-context.txt', BytesIO(b'attachment content for stream chat'), 'text/plain')},
    )
    assert uploaded.status_code == 200
    attachment_ref = uploaded.json()

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    def _fake_execute_task_automation_stream(**kwargs):
        on_event = kwargs.get('on_event')
        if callable(on_event):
            on_event({'type': 'assistant_text', 'delta': 'Streamed response with attachment.'})
        return AutomationOutcome(action='comment', summary='stream ok', comment=None, usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation_stream', _fake_execute_task_automation_stream)

    res = client.post(
        '/api/agents/chat/stream',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Use stream attachment',
            'session_id': 'chat-stream-attachment-test',
            'history': [],
            'attachment_refs': [attachment_ref],
        },
    )
    assert res.status_code == 200
    lines = [line for line in (res.text or '').splitlines() if line.strip()]
    assert any('"type": "final"' in line for line in lines)

    from shared.models import ChatAttachment, SessionLocal

    with SessionLocal() as db:
        stored = (
            db.query(ChatAttachment)
            .filter(ChatAttachment.workspace_id == ws_id, ChatAttachment.path == attachment_ref['path'])
            .order_by(ChatAttachment.created_at.desc())
            .first()
        )
        assert stored is not None


def test_agents_chat_endpoint_includes_docx_attachment_context(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    docx_buf = BytesIO()
    with zipfile.ZipFile(docx_buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body>"
                "<w:p><w:r><w:t>DOCX attachment content line one.</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>DOCX attachment content line two.</w:t></w:r></w:p>"
                "</w:body>"
                "</w:document>"
            ),
        )
    docx_buf.seek(0)
    uploaded = client.post(
        '/api/attachments/upload',
        data={'workspace_id': ws_id, 'project_id': project_id},
        files={'file': ('context.docx', docx_buf, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},
    )
    assert uploaded.status_code == 200
    attachment_ref = uploaded.json()

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    captured = {}

    def _fake_execute_task_automation(**kwargs):
        captured.update(kwargs)
        return AutomationOutcome(action='comment', summary='ok', comment=None, usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Use DOCX content',
            'history': [],
            'attachment_refs': [attachment_ref],
        },
    )
    assert res.status_code == 200
    assert 'DOCX attachment content line one.' in captured['instruction']
    assert 'DOCX attachment content line two.' in captured['instruction']


def test_agents_chat_endpoint_includes_pdf_attachment_context(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    uploaded = client.post(
        '/api/attachments/upload',
        data={'workspace_id': ws_id, 'project_id': project_id},
        files={'file': ('context.pdf', BytesIO(b'%PDF-1.4\\n%dummy\\n'), 'application/pdf')},
    )
    assert uploaded.status_code == 200
    attachment_ref = uploaded.json()

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    captured = {}

    def _fake_execute_task_automation(**kwargs):
        captured.update(kwargs)
        return AutomationOutcome(action='comment', summary='ok', comment=None, usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)
    monkeypatch.setattr(
        agents_api,
        '_extract_pdf_text',
        lambda _path, *, max_chars: ("PDF attachment extracted text.", False, None),
    )

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Use PDF content',
            'history': [],
            'attachment_refs': [attachment_ref],
        },
    )
    assert res.status_code == 200
    assert 'PDF attachment extracted text.' in captured['instruction']


def test_agents_chat_endpoint_rejects_attachment_outside_workspace(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Use attachment content',
            'history': [],
            'attachment_refs': [{'path': 'workspace/not-my-workspace/project/x/project/x/context.txt'}],
        },
    )
    assert res.status_code == 403
    assert 'workspace' in res.text.lower()


def test_agents_chat_endpoint_includes_usage_when_available(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    monkeypatch.setattr(
        agents_api,
        'execute_task_automation',
        lambda **_: AutomationOutcome(
            action='comment',
            summary='Usage captured',
            comment=None,
            usage={
                'input_tokens': 1234,
                'cached_input_tokens': 456,
                'output_tokens': 78,
                'context_limit_tokens': 128000,
            },
        ),
    )

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'usage check',
            'session_id': 'usage-session-1',
            'history': [],
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload['ok'] is True
    assert payload['usage']['input_tokens'] == 1234
    assert payload['usage']['cached_input_tokens'] == 456
    assert payload['usage']['output_tokens'] == 78
    assert payload['usage']['context_limit_tokens'] == 128000


def test_agents_chat_endpoint_auto_compacts_history_with_codex(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    calls = []

    def _fake_execute_task_automation(**kwargs):
        calls.append(kwargs)
        if "History Compaction" in str(kwargs.get("title")):
            return AutomationOutcome(action='comment', summary='Compacted context summary', comment=None)
        return AutomationOutcome(action='comment', summary='Main answer', comment='done', usage=None)

    monkeypatch.setattr(agents_api, 'AGENT_CHAT_HISTORY_COMPACT_THRESHOLD', 2)
    monkeypatch.setattr(agents_api, 'AGENT_CHAT_HISTORY_RECENT_TAIL', 1)
    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Do next step',
            'history': [
                {'role': 'user', 'content': 'First request'},
                {'role': 'assistant', 'content': 'First response'},
                {'role': 'user', 'content': 'Second request'},
            ],
        },
    )
    assert res.status_code == 200
    assert len(calls) == 2
    assert calls[0]['allow_mutations'] is False
    assert "Compact this conversation history" in calls[0]['instruction']
    assert calls[1]['allow_mutations'] is True
    assert "[Compacted conversation context]" in calls[1]['instruction']


def test_agents_chat_endpoint_uses_stored_codex_session_id_and_skips_history_stitching(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    calls = []

    def _fake_execute_task_automation(**kwargs):
        calls.append(kwargs)
        return AutomationOutcome(
            action='comment',
            summary='ok',
            comment='done',
            usage=None,
            codex_session_id='thread-resume-1',
        )

    monkeypatch.setattr(agents_api, 'AGENT_CHAT_HISTORY_COMPACT_THRESHOLD', 1)
    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)

    first = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'session_id': 'resume-session-1',
            'instruction': 'Initial request',
            'history': [],
        },
    )
    assert first.status_code == 200
    assert first.json()['codex_session_id'] == 'thread-resume-1'

    second = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'session_id': 'resume-session-1',
            'instruction': 'Follow-up request',
            'history': [
                {'role': 'user', 'content': 'First request'},
                {'role': 'assistant', 'content': 'First response'},
                {'role': 'user', 'content': 'Second request'},
            ],
        },
    )
    assert second.status_code == 200
    assert second.json()['codex_session_id'] == 'thread-resume-1'

    # Only one execute call per request: auto-compaction should be skipped for resumed sessions.
    assert len(calls) == 2
    assert calls[1]['chat_session_id'] == 'resume-session-1'
    assert calls[1]['codex_session_id'] == 'thread-resume-1'
    assert 'Conversation history:' not in calls[1]['instruction']


def test_agents_chat_endpoint_stitches_history_when_previous_resume_failed(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    calls = []

    def _fake_execute_task_automation(**kwargs):
        calls.append(kwargs)
        return AutomationOutcome(
            action='comment',
            summary='ok',
            comment='done',
            usage=None,
            codex_session_id='thread-resume-failed',
            resume_attempted=True,
            resume_succeeded=False,
            resume_fallback_used=True,
        )

    monkeypatch.setattr(agents_api, 'AGENT_CHAT_HISTORY_COMPACT_THRESHOLD', 100)
    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)

    first = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'session_id': 'resume-session-failed-1',
            'instruction': 'Initial request',
            'history': [],
        },
    )
    assert first.status_code == 200
    assert first.json()['codex_session_id'] == 'thread-resume-failed'
    assert first.json()['resume_attempted'] is True
    assert first.json()['resume_succeeded'] is False
    assert first.json()['resume_fallback_used'] is True

    second = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'session_id': 'resume-session-failed-1',
            'instruction': 'Follow-up request',
            'history': [
                {'role': 'user', 'content': 'First request'},
                {'role': 'assistant', 'content': 'First response'},
                {'role': 'user', 'content': 'Second request'},
            ],
        },
    )
    assert second.status_code == 200

    assert len(calls) == 2
    assert calls[1]['chat_session_id'] == 'resume-session-failed-1'
    assert calls[1]['codex_session_id'] == 'thread-resume-failed'
    assert 'Conversation history:' in calls[1]['instruction']


def test_agents_chat_endpoint_includes_cross_session_updates_for_resumed_threads(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    calls = []

    def _fake_execute_task_automation(**kwargs):
        calls.append(kwargs)
        return AutomationOutcome(
            action='comment',
            summary='ok',
            comment='done',
            usage=None,
            codex_session_id='thread-resume-cross-session-1',
        )

    monkeypatch.setattr(agents_api, 'AGENT_CHAT_HISTORY_COMPACT_THRESHOLD', 999)
    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)

    old_session_first = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'session_id': 'old-session-1',
            'instruction': 'Initial old-session request',
            'history': [],
        },
    )
    assert old_session_first.status_code == 200

    new_session_secret = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'session_id': 'new-session-1',
            'instruction': 'Tajni broj je 44',
            'history': [],
        },
    )
    assert new_session_secret.status_code == 200

    old_session_followup = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'session_id': 'old-session-1',
            'instruction': 'Koji je tajni broj?',
            'history': [],
        },
    )
    assert old_session_followup.status_code == 200

    assert len(calls) == 3
    assert calls[2]['chat_session_id'] == 'old-session-1'
    assert calls[2]['codex_session_id'] == 'thread-resume-cross-session-1'
    assert 'Recent updates from other project chat sessions' in calls[2]['instruction']
    assert 'Tajni broj je 44' in calls[2]['instruction']
    assert 'Conversation history:' not in calls[2]['instruction']


def test_agents_chat_endpoint_respects_allow_mutations_flag(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    captured = {}

    def _fake_execute_task_automation(**kwargs):
        captured.update(kwargs)
        return AutomationOutcome(action='comment', summary='Read-only answer', comment=None, usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Analyze only',
            'allow_mutations': False,
            'history': [],
        },
    )
    assert res.status_code == 200
    assert captured['allow_mutations'] is False


def test_agents_chat_endpoint_force_compacts_on_slash_command(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    calls = []

    def _fake_execute_task_automation(**kwargs):
        calls.append(kwargs)
        return AutomationOutcome(action='comment', summary='Forced compact summary', comment=None, usage=None)

    monkeypatch.setattr(agents_api, 'AGENT_CHAT_HISTORY_COMPACT_THRESHOLD', 999)
    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': '/compact',
            'history': [
                {'role': 'user', 'content': 'Old question'},
                {'role': 'assistant', 'content': 'Old answer'},
                {'role': 'user', 'content': '/compact'},
            ],
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload['ok'] is True
    assert payload['summary'] == 'Chat history compacted.'
    assert payload['comment'] is None
    assert payload['usage'] is None
    assert len(calls) == 1
    assert calls[0]['allow_mutations'] is False
    assert 'Compact this conversation history' in calls[0]['instruction']


def test_create_scheduled_task_requires_instruction_and_time(tmp_path):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']
    project_id = client.get('/api/bootstrap').json()['projects'][0]['id']

    res = client.post(
        '/api/tasks',
        json={
            'title': 'Scheduled invalid',
            'workspace_id': ws_id,
            'project_id': project_id,
            'task_type': 'scheduled_instruction',
        },
    )
    assert res.status_code == 422
    assert 'scheduled_instruction' in res.text or 'scheduled_at_utc' in res.text


def test_scheduled_instruction_task_is_queued_and_processed(tmp_path):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']
    project_id = client.get('/api/bootstrap').json()['projects'][0]['id']
    due_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Scheduled run',
            'workspace_id': ws_id,
            'project_id': project_id,
            'task_type': 'scheduled_instruction',
            'scheduled_instruction': 'Leave progress note',
            'scheduled_at_utc': due_at,
            'schedule_timezone': 'UTC',
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']
    moved = client.patch(f'/api/tasks/{task_id}', json={'status': 'In progress'})
    assert moved.status_code == 200

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
    project_id = client.get('/api/bootstrap').json()['projects'][0]['id']
    due_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Recurring scheduled run',
            'workspace_id': ws_id,
            'project_id': project_id,
            'task_type': 'scheduled_instruction',
            'scheduled_instruction': 'Leave progress note',
            'scheduled_at_utc': due_at,
            'schedule_timezone': 'UTC',
            'recurring_rule': 'every:5m',
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']
    moved = client.patch(f'/api/tasks/{task_id}', json={'status': 'In progress'})
    assert moved.status_code == 200

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


def test_scheduled_instruction_is_not_queued_outside_in_progress(tmp_path):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']
    project_id = client.get('/api/bootstrap').json()['projects'][0]['id']
    due_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Scheduled todo should not run',
            'workspace_id': ws_id,
            'project_id': project_id,
            'task_type': 'scheduled_instruction',
            'scheduled_instruction': 'Leave progress note',
            'scheduled_at_utc': due_at,
            'schedule_timezone': 'UTC',
            'recurring_rule': 'every:1m',
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    from features.agents.runner import queue_due_scheduled_tasks_once

    queued = queue_due_scheduled_tasks_once(limit=10)
    assert queued == 0

    status = client.get(f'/api/tasks/{task_id}/automation').json()
    assert status['automation_state'] == 'idle'
    assert status['schedule_state'] == 'idle'


def test_scheduled_instruction_can_queue_on_selected_statuses(tmp_path):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']
    project_id = client.get('/api/bootstrap').json()['projects'][0]['id']
    due_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Scheduled run on todo',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Leave progress note',
            'execution_triggers': [
                {
                    'kind': 'schedule',
                    'enabled': True,
                    'scheduled_at_utc': due_at,
                    'schedule_timezone': 'UTC',
                    'run_on_statuses': ['To do'],
                },
            ],
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']
    schedule_trigger = next(
        trigger for trigger in created.json()['execution_triggers'] if trigger.get('kind') == 'schedule'
    )
    assert schedule_trigger.get('run_on_statuses') == ['To do']

    from features.agents.runner import queue_due_scheduled_tasks_once

    queued = queue_due_scheduled_tasks_once(limit=10)
    assert queued >= 1

    status = client.get(f'/api/tasks/{task_id}/automation').json()
    assert status['automation_state'] in {'queued', 'running', 'completed'}


def test_recover_stale_recurring_scheduled_task_rearms_schedule(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    due_at = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Stale recurring recovery',
            'workspace_id': ws_id,
            'project_id': project_id,
            'task_type': 'scheduled_instruction',
            'scheduled_instruction': 'Leave progress note',
            'scheduled_at_utc': due_at,
            'schedule_timezone': 'UTC',
            'recurring_rule': 'every:1m',
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']
    moved = client.patch(f'/api/tasks/{task_id}', json={'status': 'In progress'})
    assert moved.status_code == 200

    from features.agents.runner import recover_stale_running_automation_once
    from shared.eventing import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    stale_started_at = datetime.now(timezone.utc) - timedelta(minutes=7)
    stale_started_iso = stale_started_at.isoformat()
    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=task_id,
            event_type='TaskAutomationStarted',
            payload={'started_at': stale_started_iso},
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': task_id},
        )
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=task_id,
            event_type='TaskScheduleStarted',
            payload={'started_at': stale_started_iso},
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': task_id},
        )
        db.commit()

    recovered = recover_stale_running_automation_once(limit=20)
    assert recovered >= 1

    status = client.get(f'/api/tasks/{task_id}/automation').json()
    assert status['automation_state'] == 'failed'
    assert status['schedule_state'] == 'idle'
    assert status['scheduled_at_utc'] is not None
    assert datetime.fromisoformat(status['scheduled_at_utc']) > datetime.now(timezone.utc)


def test_create_task_accepts_instruction_and_execution_triggers(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    due_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Trigger roundtrip',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Leave a progress note',
            'execution_triggers': [
                {'kind': 'manual', 'enabled': True},
                {
                    'kind': 'schedule',
                    'enabled': True,
                    'scheduled_at_utc': due_at,
                    'schedule_timezone': 'UTC',
                    'recurring_rule': 'every:1h',
                },
            ],
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload['instruction'] == 'Leave a progress note'
    assert payload['task_type'] == 'scheduled_instruction'
    assert any(trigger.get('kind') == 'schedule' for trigger in payload['execution_triggers'])


def test_status_change_trigger_self_queues_automation(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Self status trigger',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Run a completion checklist',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'enabled': True,
                    'scope': 'self',
                    'match_mode': 'any',
                    'to_statuses': ['Done'],
                },
            ],
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    completed = client.post(f'/api/tasks/{task_id}/complete')
    assert completed.status_code == 200

    automation = client.get(f'/api/tasks/{task_id}/automation')
    assert automation.status_code == 200
    payload = automation.json()
    assert payload['automation_state'] == 'queued'
    assert payload['last_requested_source'] == 'status_change'
    assert payload['last_requested_instruction'] == 'Run a completion checklist'


def test_runner_processes_status_change_trigger_when_task_is_done(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Self status trigger run',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Run after completion',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'enabled': True,
                    'scope': 'self',
                    'match_mode': 'any',
                    'to_statuses': ['Done'],
                },
            ],
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    completed = client.post(f'/api/tasks/{task_id}/complete')
    assert completed.status_code == 200

    queued = client.get(f'/api/tasks/{task_id}/automation')
    assert queued.status_code == 200
    assert queued.json()['automation_state'] == 'queued'
    assert queued.json()['last_requested_source'] == 'status_change'

    from features.agents.runner import run_queued_automation_once

    processed = run_queued_automation_once(limit=5)
    assert processed >= 1

    final = client.get(f'/api/tasks/{task_id}/automation')
    assert final.status_code == 200
    payload = final.json()
    assert payload['automation_state'] == 'completed'
    assert payload['last_requested_source'] == 'status_change'


def test_status_change_trigger_external_any_queues_target(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    source = client.post(
        '/api/tasks',
        json={
            'title': 'External any source',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    assert source.status_code == 200
    source_id = source.json()['id']

    target = client.post(
        '/api/tasks',
        json={
            'title': 'External any target',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'React to source completion',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'enabled': True,
                    'scope': 'external',
                    'match_mode': 'any',
                    'selector': {'task_ids': [source_id]},
                    'to_statuses': ['Done'],
                },
            ],
        },
    )
    assert target.status_code == 200
    target_id = target.json()['id']

    completed = client.post(f'/api/tasks/{source_id}/complete')
    assert completed.status_code == 200

    automation = client.get(f'/api/tasks/{target_id}/automation')
    assert automation.status_code == 200
    payload = automation.json()
    assert payload['automation_state'] == 'queued'
    assert payload['last_requested_source'] == 'status_change'
    assert payload['last_requested_instruction'] == 'React to source completion'


def test_status_change_trigger_external_without_selector_matches_any_workspace_source(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    source = client.post(
        '/api/tasks',
        json={
            'title': 'External global source',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    assert source.status_code == 200
    source_id = source.json()['id']

    target = client.post(
        '/api/tasks',
        json={
            'title': 'External global target',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'React to any workspace task completion',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'enabled': True,
                    'scope': 'external',
                    'match_mode': 'any',
                    'to_statuses': ['Done'],
                },
            ],
        },
    )
    assert target.status_code == 200
    target_id = target.json()['id']

    completed = client.post(f'/api/tasks/{source_id}/complete')
    assert completed.status_code == 200

    automation = client.get(f'/api/tasks/{target_id}/automation')
    assert automation.status_code == 200
    payload = automation.json()
    assert payload['automation_state'] == 'queued'
    assert payload['last_requested_source'] == 'status_change'
    assert payload['last_requested_instruction'] == 'React to any workspace task completion'


def test_status_change_trigger_external_project_selector_filters_sources(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_a_id = bootstrap['projects'][0]['id']

    project_b = client.post(
        '/api/projects',
        json={'workspace_id': ws_id, 'name': 'External watcher project B'},
    )
    assert project_b.status_code == 200
    project_b_id = project_b.json()['id']

    source_a = client.post(
        '/api/tasks',
        json={
            'title': 'Project A source',
            'workspace_id': ws_id,
            'project_id': project_a_id,
        },
    )
    source_b = client.post(
        '/api/tasks',
        json={
            'title': 'Project B source',
            'workspace_id': ws_id,
            'project_id': project_b_id,
        },
    )
    assert source_a.status_code == 200
    assert source_b.status_code == 200
    source_a_id = source_a.json()['id']
    source_b_id = source_b.json()['id']

    target = client.post(
        '/api/tasks',
        json={
            'title': 'Project-filtered watcher target',
            'workspace_id': ws_id,
            'project_id': project_a_id,
            'instruction': 'React only to project A status changes',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'enabled': True,
                    'scope': 'external',
                    'match_mode': 'any',
                    'selector': {'project_id': project_a_id},
                    'to_statuses': ['Done'],
                },
            ],
        },
    )
    assert target.status_code == 200
    target_id = target.json()['id']

    complete_b = client.post(f'/api/tasks/{source_b_id}/complete')
    assert complete_b.status_code == 200
    after_b = client.get(f'/api/tasks/{target_id}/automation')
    assert after_b.status_code == 200
    assert after_b.json()['automation_state'] == 'idle'

    complete_a = client.post(f'/api/tasks/{source_a_id}/complete')
    assert complete_a.status_code == 200
    after_a = client.get(f'/api/tasks/{target_id}/automation')
    assert after_a.status_code == 200
    payload = after_a.json()
    assert payload['automation_state'] == 'queued'
    assert payload['last_requested_source'] == 'status_change'
    assert payload['last_requested_instruction'] == 'React only to project A status changes'


def test_status_change_trigger_direct_target_mapping_queues_target_only(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    target = client.post(
        '/api/tasks',
        json={
            'title': 'Direct mapping target',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Handle source completion',
        },
    )
    assert target.status_code == 200
    target_id = target.json()['id']

    source = client.post(
        '/api/tasks',
        json={
            'title': 'Direct mapping source',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Observe source completion',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'enabled': True,
                    'scope': 'self',
                    'match_mode': 'any',
                    'to_statuses': ['Done'],
                    'action': 'run_automation',
                    'target_task_id': target_id,
                },
            ],
        },
    )
    assert source.status_code == 200
    source_id = source.json()['id']

    completed = client.post(f'/api/tasks/{source_id}/complete')
    assert completed.status_code == 200

    source_automation = client.get(f'/api/tasks/{source_id}/automation')
    assert source_automation.status_code == 200
    assert source_automation.json()['automation_state'] == 'idle'

    target_automation = client.get(f'/api/tasks/{target_id}/automation')
    assert target_automation.status_code == 200
    payload = target_automation.json()
    assert payload['automation_state'] == 'queued'
    assert payload['last_requested_source'] == 'status_change'
    assert payload['last_requested_instruction'] == 'Handle source completion'


def test_status_change_trigger_direct_target_mapping_accepts_run_task_instruction_action(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    target = client.post(
        '/api/tasks',
        json={
            'title': 'Direct mapping target action alias',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Handle source completion via alias action',
        },
    )
    assert target.status_code == 200
    target_id = target.json()['id']

    source = client.post(
        '/api/tasks',
        json={
            'title': 'Direct mapping source action alias',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Observe source completion',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'enabled': True,
                    'scope': 'self',
                    'match_mode': 'any',
                    'to_statuses': ['Done'],
                    'action': 'run_task_instruction',
                    'target_task_id': target_id,
                },
            ],
        },
    )
    assert source.status_code == 200
    source_id = source.json()['id']

    completed = client.post(f'/api/tasks/{source_id}/complete')
    assert completed.status_code == 200

    target_automation = client.get(f'/api/tasks/{target_id}/automation')
    assert target_automation.status_code == 200
    payload = target_automation.json()
    assert payload['automation_state'] == 'queued'
    assert payload['last_requested_source'] == 'status_change'
    assert payload['last_requested_instruction'] == 'Handle source completion via alias action'


def test_status_change_trigger_external_target_mapping_on_target_task_queues_target(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    source = client.post(
        '/api/tasks',
        json={
            'title': 'External target mapping source',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    assert source.status_code == 200
    source_id = source.json()['id']

    target = client.post(
        '/api/tasks',
        json={
            'title': 'External target mapping target',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Run from external watcher with explicit target mapping',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'enabled': True,
                    'scope': 'external',
                    'match_mode': 'any',
                    'selector': {'task_ids': [source_id]},
                    'to_statuses': ['Done'],
                    'action': 'run_task_instruction',
                    'target_task_id': None,  # filled below with created id
                },
            ],
        },
    )
    assert target.status_code == 200
    target_id = target.json()['id']

    # Reconfigure trigger with explicit target_task_id equal to target task itself.
    configured = client.patch(
        f'/api/tasks/{target_id}',
        json={
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'enabled': True,
                    'scope': 'external',
                    'match_mode': 'any',
                    'selector': {'task_ids': [source_id]},
                    'to_statuses': ['Done'],
                    'action': 'run_task_instruction',
                    'target_task_id': target_id,
                },
            ],
        },
    )
    assert configured.status_code == 200

    completed = client.post(f'/api/tasks/{source_id}/complete')
    assert completed.status_code == 200

    automation = client.get(f'/api/tasks/{target_id}/automation')
    assert automation.status_code == 200
    payload = automation.json()
    assert payload['automation_state'] == 'queued'
    assert payload['last_requested_source'] == 'status_change'
    assert payload['last_requested_instruction'] == 'Run from external watcher with explicit target mapping'


def test_status_change_trigger_scope_other_with_source_task_ids_queues_target(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    source = client.post(
        '/api/tasks',
        json={
            'title': 'Scope other source',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    assert source.status_code == 200
    source_id = source.json()['id']

    target = client.post(
        '/api/tasks',
        json={
            'title': 'Scope other target',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'React to source completion via alias',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'enabled': True,
                    'scope': 'other',
                    'match_mode': 'any',
                    'source_task_ids': [source_id],
                    'to_statuses': ['Done'],
                },
            ],
        },
    )
    assert target.status_code == 200
    target_trigger = [trigger for trigger in target.json()['execution_triggers'] if trigger.get('kind') == 'status_change']
    assert len(target_trigger) == 1
    assert target_trigger[0].get('scope') == 'external'
    assert target_trigger[0].get('selector', {}).get('task_ids') == [source_id]
    target_id = target.json()['id']

    completed = client.post(f'/api/tasks/{source_id}/complete')
    assert completed.status_code == 200

    automation = client.get(f'/api/tasks/{target_id}/automation')
    assert automation.status_code == 200
    payload = automation.json()
    assert payload['automation_state'] == 'queued'
    assert payload['last_requested_source'] == 'status_change'
    assert payload['last_requested_instruction'] == 'React to source completion via alias'


def test_status_change_trigger_external_all_waits_for_all_selected_tasks(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    source_a = client.post(
        '/api/tasks',
        json={
            'title': 'External all source A',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    source_b = client.post(
        '/api/tasks',
        json={
            'title': 'External all source B',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    assert source_a.status_code == 200
    assert source_b.status_code == 200
    source_a_id = source_a.json()['id']
    source_b_id = source_b.json()['id']

    target = client.post(
        '/api/tasks',
        json={
            'title': 'External all target',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Run after both dependencies are done',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'enabled': True,
                    'scope': 'external',
                    'match_mode': 'all',
                    'selector': {'task_ids': [source_a_id, source_b_id]},
                    'to_statuses': ['Done'],
                },
            ],
        },
    )
    assert target.status_code == 200
    target_id = target.json()['id']

    complete_a = client.post(f'/api/tasks/{source_a_id}/complete')
    assert complete_a.status_code == 200
    after_a = client.get(f'/api/tasks/{target_id}/automation')
    assert after_a.status_code == 200
    assert after_a.json()['automation_state'] == 'idle'

    complete_b = client.post(f'/api/tasks/{source_b_id}/complete')
    assert complete_b.status_code == 200
    after_b = client.get(f'/api/tasks/{target_id}/automation')
    assert after_b.status_code == 200
    payload = after_b.json()
    assert payload['automation_state'] == 'queued'
    assert payload['last_requested_source'] == 'status_change'
    assert payload['last_requested_instruction'] == 'Run after both dependencies are done'


def test_create_task_requires_project_id(tmp_path):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']
    res = client.post('/api/tasks', json={'title': 'No project', 'workspace_id': ws_id})
    assert res.status_code == 422


def test_task_tags_are_normalized_and_filterable(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created_both = client.post(
        '/api/tasks',
        json={'title': 'Tag task', 'workspace_id': ws_id, 'project_id': project_id, 'labels': ['Critical', 'critical', ' UI ']},
    )
    assert created_both.status_code == 200
    payload_both = created_both.json()
    assert payload_both['labels'] == ['critical', 'ui']

    created_single = client.post(
        '/api/tasks',
        json={'title': 'Critical only task', 'workspace_id': ws_id, 'project_id': project_id, 'labels': ['critical']},
    )
    assert created_single.status_code == 200
    payload_single = created_single.json()
    assert payload_single['labels'] == ['critical']

    filtered = client.get(f'/api/tasks?workspace_id={ws_id}&project_id={project_id}&tags=critical,ui')
    assert filtered.status_code == 200
    filtered_ids = {item['id'] for item in filtered.json()['items']}
    assert payload_both['id'] in filtered_ids
    assert payload_single['id'] in filtered_ids


def test_saved_view_projection_is_idempotent(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post(
        '/api/saved-views',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'name': 'Mine',
            'shared': False,
            'filters': {'q': 'x'},
        },
    )
    assert created.status_code == 200
    sid = created.json()['id']

    from shared.eventing_rebuild import project_event
    from shared.models import SessionLocal
    from shared.core import EventEnvelope

    ev = EventEnvelope(
        aggregate_type='SavedView',
        aggregate_id=sid,
        version=1,
        event_type='SavedViewCreated',
        payload={
            'workspace_id': ws_id,
            'project_id': project_id,
            'user_id': bootstrap['current_user']['id'],
            'name': 'Mine',
            'shared': False,
            'filters': {'q': 'x'},
        },
        metadata={'actor_id': bootstrap['current_user']['id'], 'workspace_id': ws_id, 'project_id': project_id},
    )

    with SessionLocal() as db:
        project_event(db, ev)
        project_event(db, ev)
        db.commit()


def test_append_event_write_through_ignores_duplicate_projection_race(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from shared import eventing
    from shared.core import append_event
    from shared.models import SessionLocal
    from sqlalchemy.exc import IntegrityError

    class _FakeKurrentClient:
        def append_to_stream(self, **_kwargs):
            return None

    def _raise_duplicate(_db, _env):
        raise IntegrityError(
            statement="insert into projects (...) values (...)",
            params=None,
            orig=Exception('duplicate key value violates unique constraint "projects_pkey"'),
        )

    monkeypatch.setattr(eventing, "get_kurrent_client", lambda: _FakeKurrentClient())
    monkeypatch.setattr(eventing, "current_version", lambda _db, _aggregate_type, _aggregate_id: 0)
    monkeypatch.setattr(eventing, "project_event", _raise_duplicate)

    with SessionLocal() as db:
        env = append_event(
            db,
            aggregate_type='Project',
            aggregate_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            event_type='ProjectCreated',
            payload={'workspace_id': ws_id, 'name': 'Duplicate projection race'},
            metadata={'actor_id': bootstrap['current_user']['id'], 'workspace_id': ws_id},
            expected_version=0,
        )
        db.commit()

    assert env.aggregate_type == 'Project'
    assert env.version == 1


def test_task_comment_projection_is_idempotent(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    task = client.post('/api/tasks', json={'title': 'Comment idempotency', 'workspace_id': ws_id, 'project_id': project_id}).json()

    from shared.eventing_rebuild import project_event
    from shared.models import SessionLocal, TaskComment
    from shared.core import EventEnvelope

    ev = EventEnvelope(
        aggregate_type='Task',
        aggregate_id=task['id'],
        version=2,
        event_type='TaskCommentAdded',
        payload={'task_id': task['id'], 'user_id': bootstrap['current_user']['id'], 'body': 'same'},
        metadata={'actor_id': bootstrap['current_user']['id'], 'workspace_id': ws_id, 'project_id': project_id, 'task_id': task['id']},
    )

    with SessionLocal() as db:
        project_event(db, ev)
        project_event(db, ev)
        db.commit()
        rows = db.query(TaskComment).filter(TaskComment.task_id == task['id']).all()
        same_rows = [r for r in rows if r.body == 'same']
        assert len(same_rows) == 1


def test_task_comment_projection_replay_does_not_create_duplicate_mentions(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    current_user = bootstrap['current_user']

    task = client.post('/api/tasks', json={'title': 'Mention replay guard', 'workspace_id': ws_id, 'project_id': project_id}).json()
    comment = client.post(f"/api/tasks/{task['id']}/comments", json={'body': f"Ping @{current_user['username']}"})
    assert comment.status_code == 200

    before = client.get('/api/notifications')
    assert before.status_code == 200
    before_mentions = [
        n for n in before.json()
        if 'mentioned you on task' in n['message'] and n.get('task_id') == task['id']
    ]
    assert len(before_mentions) == 1

    from shared.core import EventEnvelope
    from shared.eventing_rebuild import project_event
    from shared.models import SessionLocal

    ev = EventEnvelope(
        aggregate_type='Task',
        aggregate_id=task['id'],
        version=2,
        event_type='TaskCommentAdded',
        payload={'task_id': task['id'], 'user_id': current_user['id'], 'body': f"Ping @{current_user['username']}"},
        metadata={'actor_id': current_user['id'], 'workspace_id': ws_id, 'project_id': project_id, 'task_id': task['id']},
    )

    with SessionLocal() as db:
        project_event(db, ev)
        project_event(db, ev)
        db.commit()

    after = client.get('/api/notifications')
    assert after.status_code == 200
    after_mentions = [
        n for n in after.json()
        if 'mentioned you on task' in n['message'] and n.get('task_id') == task['id']
    ]
    assert len(after_mentions) == len(before_mentions)


def test_task_watch_projection_is_idempotent_and_dedupes(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    user_id = bootstrap['current_user']['id']

    task = client.post('/api/tasks', json={'title': 'Watch idempotency', 'workspace_id': ws_id, 'project_id': project_id}).json()

    from shared.eventing_rebuild import project_event
    from shared.models import SessionLocal, TaskWatcher
    from shared.core import EventEnvelope

    with SessionLocal() as db:
        ev_watch_on = EventEnvelope(
            aggregate_type='Task',
            aggregate_id=task['id'],
            version=2,
            event_type='TaskWatchToggled',
            payload={'task_id': task['id'], 'user_id': user_id, 'watched': True},
            metadata={'actor_id': user_id, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': task['id']},
        )
        project_event(db, ev_watch_on)
        project_event(db, ev_watch_on)
        db.commit()

        after_on = db.query(TaskWatcher).filter(TaskWatcher.task_id == task['id'], TaskWatcher.user_id == user_id).all()
        assert len(after_on) == 1

        ev_watch_off = EventEnvelope(
            aggregate_type='Task',
            aggregate_id=task['id'],
            version=3,
            event_type='TaskWatchToggled',
            payload={'task_id': task['id'], 'user_id': user_id, 'watched': False},
            metadata={'actor_id': user_id, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': task['id']},
        )
        project_event(db, ev_watch_off)
        project_event(db, ev_watch_off)
        db.commit()

        after_off = db.query(TaskWatcher).filter(TaskWatcher.task_id == task['id'], TaskWatcher.user_id == user_id).all()
        assert len(after_off) == 0


def test_chat_attachment_projection_handles_attachment_before_message(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    user_id = bootstrap['current_user']['id']

    from shared.core import EventEnvelope
    from shared.eventing_rebuild import project_event
    from shared.models import ChatAttachment, ChatMessage, ChatSession, SessionLocal

    aggregate_id = '44444444-4444-4444-4444-444444444444'
    message_id = '55555555-5555-4555-8555-555555555555'
    attachment_id = '66666666-6666-4666-8666-666666666666'
    session_key = 'chat-attachment-ordering-test'

    attachment_event = EventEnvelope(
        aggregate_type='ChatSession',
        aggregate_id=aggregate_id,
        version=1,
        event_type='ChatSessionAttachmentLinked',
        payload={
            'workspace_id': ws_id,
            'project_id': project_id,
            'session_key': session_key,
            'attachment_id': attachment_id,
            'message_id': message_id,
            'path': 'workspace/test/path.txt',
            'name': 'path.txt',
            'mime_type': 'text/plain',
            'size_bytes': 10,
            'extraction_status': 'pending',
        },
        metadata={'actor_id': user_id, 'workspace_id': ws_id, 'project_id': project_id, 'session_id': session_key},
    )
    message_event = EventEnvelope(
        aggregate_type='ChatSession',
        aggregate_id=aggregate_id,
        version=2,
        event_type='ChatSessionUserMessageAppended',
        payload={
            'workspace_id': ws_id,
            'project_id': project_id,
            'session_key': session_key,
            'message_id': message_id,
            'content': 'Message with attachment',
            'order_index': 1,
            'created_at': '2026-02-23T21:00:00+00:00',
            'attachment_refs': [{'path': 'workspace/test/path.txt', 'name': 'path.txt'}],
        },
        metadata={'actor_id': user_id, 'workspace_id': ws_id, 'project_id': project_id, 'session_id': session_key},
    )

    with SessionLocal() as db:
        project_event(db, attachment_event)
        project_event(db, message_event)
        db.commit()

        session = db.get(ChatSession, aggregate_id)
        assert session is not None
        assert session.session_key == session_key

        message = db.get(ChatMessage, message_id)
        assert message is not None
        assert message.session_id == aggregate_id
        assert message.content == 'Message with attachment'
        assert message.order_index == 1

        attachment = db.get(ChatAttachment, attachment_id)
        assert attachment is not None
        assert attachment.message_id == message_id
        assert attachment.session_id == aggregate_id
