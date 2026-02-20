import os
from importlib import reload
from pathlib import Path
from zoneinfo import ZoneInfo

from datetime import datetime, timedelta, timezone
from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy import select


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
    login = client.post('/api/auth/login', json={'username': 'm4tr1x', 'password': 'testtest'})
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


def test_create_project(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    res = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Mobile Redesign'})
    assert res.status_code == 200
    payload = res.json()
    assert payload['name'] == 'Mobile Redesign'
    assert payload['workspace_id'] == ws_id


def test_bootstrap_exposes_embedding_runtime_config(tmp_path):
    client = build_client(tmp_path)
    payload = client.get('/api/bootstrap').json()

    assert isinstance(payload.get('embedding_allowed_models'), list)
    assert len(payload['embedding_allowed_models']) >= 1
    assert isinstance(payload.get('embedding_default_model'), str)
    assert payload['embedding_default_model'] in payload['embedding_allowed_models']
    assert isinstance(payload.get('vector_store_enabled'), bool)
    assert isinstance(payload.get('context_pack_evidence_top_k_default'), int)


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

    from features.projects import api as projects_api

    monkeypatch.setattr(projects_api, 'require_graph_available', lambda: None)
    monkeypatch.setattr(
        projects_api,
        'graph_get_project_overview',
        lambda project_id, top_limit=8: {
            'project_id': project_id,
            'project_name': 'Stub Project',
            'counts': {'tasks': 2, 'notes': 1, 'specifications': 1, 'project_rules': 1},
            'top_tags': [{'tag': 'shared', 'usage': 3}],
            'top_relationships': [{'relationship': 'IN_PROJECT', 'count': 10}],
        },
    )
    monkeypatch.setattr(
        projects_api,
        'graph_context_pack',
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

    from features.projects import api as projects_api

    monkeypatch.setattr(
        projects_api,
        'search_project_knowledge',
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

    from features.projects import api as projects_api

    def _raise_unavailable():
        raise RuntimeError('disabled')

    monkeypatch.setattr(projects_api, 'require_graph_available', _raise_unavailable)
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

    admin_login = client.post('/api/auth/login', json={'username': 'm4tr1x', 'password': 'testtest'})
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
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    due_utc = datetime.now(timezone.utc) + timedelta(minutes=30)

    created = client.post(
        '/api/tasks',
        json={'title': 'Soon deadline', 'workspace_id': ws_id, 'project_id': project_id, 'due_date': due_utc.isoformat()},
    )
    assert created.status_code == 200

    notes = client.get('/api/notifications')
    assert notes.status_code == 200
    due_soon = [n for n in notes.json() if 'due within 1 hour' in n['message']]
    assert due_soon
    assert any(n.get('task_id') == created.json()['id'] for n in due_soon)
    assert any(n.get('project_id') == project_id for n in due_soon)


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
