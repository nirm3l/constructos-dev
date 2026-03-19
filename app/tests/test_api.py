import asyncio
import json
import os
import threading
import uuid
from importlib import reload
from pathlib import Path
import zipfile
from zoneinfo import ZoneInfo

from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, text


def build_client(tmp_path: Path):
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
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


def build_anonymous_client(tmp_path: Path):
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ["AGENT_RUNNER_ENABLED"] = "false"
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    import main

    main = reload(main)
    main.bootstrap_data()
    return TestClient(main.app)


def _login_as_user(client: TestClient, *, username: str, password: str):
    response = client.post('/api/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200
    return response


def _activate_user_password(client: TestClient, *, username: str, temporary_password: str, new_password: str) -> None:
    _login_as_user(client, username=username, password=temporary_password)
    changed = client.post(
        '/api/auth/change-password',
        json={'current_password': temporary_password, 'new_password': new_password},
    )
    assert changed.status_code == 200


def trigger_system_notifications_for_user(user_id: str) -> int:
    from shared.core import emit_system_notifications
    from shared.models import SessionLocal, User

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        return emit_system_notifications(db, user)


def _ensure_team_mode_member_roles(*, workspace_id: str, project_id: str) -> dict[str, str]:
    from shared.models import ProjectMember, SessionLocal, User, WorkspaceMember

    role_order = [
        ("DeveloperAgent", "dev1"),
        ("DeveloperAgent", "dev2"),
        ("QAAgent", "qa"),
        ("TeamLeadAgent", "lead"),
    ]
    with SessionLocal() as db:
        members = db.execute(
            select(ProjectMember).where(ProjectMember.project_id == project_id)
        ).scalars().all()
        user_ids = [str(member.user_id) for member in members if str(member.user_id or "").strip()]
        while len(user_ids) < len(role_order):
            suffix = str(uuid.uuid4())[:8]
            user = User(
                id=str(uuid.uuid4()),
                username=f"tm-test-{suffix}",
                full_name=f"Team Test {suffix}",
                user_type="agent",
                password_hash=None,
                must_change_password=False,
                is_active=True,
            )
            db.add(user)
            db.flush()
            db.add(WorkspaceMember(workspace_id=workspace_id, user_id=str(user.id), role="Member"))
            db.add(
                ProjectMember(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    user_id=str(user.id),
                    role="Contributor",
                )
            )
            db.flush()
            user_ids.append(str(user.id))
        selected = user_ids[: len(role_order)]
        result: dict[str, str] = {}
        for idx, (role, key) in enumerate(role_order):
            user_id = selected[idx]
            row = db.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == user_id,
                )
            ).scalars().first()
            if row is None:
                row = ProjectMember(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    user_id=user_id,
                    role=role,
                )
                db.add(row)
            else:
                row.role = role
            result[key] = user_id
        db.commit()
    return result


def _enable_team_mode_for_project(client: TestClient, *, ws_id: str, project_id: str) -> dict[str, str]:
    enabled = client.post(
        f"/api/projects/{project_id}/plugins/team_mode/enabled",
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    git_enabled = client.get(f"/api/projects/{project_id}/plugins/git_delivery")
    assert git_enabled.status_code == 200
    assert bool(git_enabled.json().get("enabled")) is True
    return _ensure_team_mode_member_roles(workspace_id=ws_id, project_id=project_id)


def _configure_team_mode_for_project(client: TestClient, *, ws_id: str, project_id: str) -> dict[str, str]:
    from plugins.team_mode.semantics import default_team_mode_config
    from shared.settings import DEFAULT_USER_ID

    team = _enable_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    status_patch = client.patch(
        f"/api/projects/{project_id}",
        json={
            "custom_statuses": [
                "To Do",
                "In Progress",
                "In Review",
                "Awaiting Decision",
                "Blocked",
                "Completed",
            ]
        },
    )
    assert status_patch.status_code == 200
    config = default_team_mode_config()
    config["oversight"]["human_owner_user_id"] = DEFAULT_USER_ID
    config["team"]["agents"] = [
        {
            "id": "dev-a",
            "name": "Developer A",
            "authority_role": "Developer",
            "executor_user_id": team["dev1"],
        },
        {
            "id": "dev-b",
            "name": "Developer B",
            "authority_role": "Developer",
            "executor_user_id": team["dev2"],
        },
        {
            "id": "qa-a",
            "name": "QA A",
            "authority_role": "QA",
            "executor_user_id": team["qa"],
        },
        {
            "id": "lead-a",
            "name": "Lead",
            "authority_role": "Lead",
            "executor_user_id": team["lead"],
        },
    ]
    applied = client.post(
        f"/api/projects/{project_id}/plugins/team_mode/apply",
        json={"config": config, "enabled": True},
    )
    assert applied.status_code == 200
    return team


def _set_project_repository_context(client: TestClient, *, project_id: str) -> None:
    updated = client.patch(
        f"/api/projects/{project_id}",
        json={
            "external_refs": [
                {
                    "url": f"file:///home/app/workspace/{project_id}",
                    "title": "Repository context",
                    "label": "Local workspace repository path",
                }
            ]
        },
    )
    assert updated.status_code == 200


def test_health(tmp_path):
    client = build_client(tmp_path)
    res = client.get('/api/health')
    assert res.status_code == 200
    payload = res.json()
    assert payload['ok'] is True
    assert isinstance(payload.get('vector'), dict)
    assert payload['vector']['status'] in {'disabled', 'unsupported_database', 'not_ready', 'ready', 'error'}


def test_bootstrap_demo_project_has_embedding_enabled_by_default(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap')
    assert bootstrap.status_code == 200
    projects = bootstrap.json().get("projects") or []
    demo = next((p for p in projects if str(p.get("name") or "").strip().lower() == "demo"), None)
    assert demo is not None
    assert bool(demo.get("embedding_enabled")) is True


def test_event_storming_endpoints_exist_and_return_503_when_graph_disabled(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    project_id = bootstrap['projects'][0]['id']

    overview = client.get(f'/api/projects/{project_id}/event-storming/overview')
    assert overview.status_code == 503
    assert 'Event storming projection is unavailable' in str(overview.json().get('detail', ''))

    subgraph = client.get(f'/api/projects/{project_id}/event-storming/subgraph')
    assert subgraph.status_code == 503
    assert 'Event storming projection is unavailable' in str(subgraph.json().get('detail', ''))

    review = client.post(
        f'/api/projects/{project_id}/event-storming/review-link',
        json={
            'entity_type': 'task',
            'entity_id': 'x',
            'component_id': 'y',
            'review_status': 'approved',
        },
    )
    assert review.status_code == 503
    assert 'Event storming projection is unavailable' in str(review.json().get('detail', ''))


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
    project_resp = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Lead handoff queue QA test',
            'custom_statuses': ['To do', 'Dev', 'Lead', 'QA', 'Done', 'Blocked'],
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()['id']

    created = client.post('/api/tasks', json={'title': 'Write tests', 'workspace_id': ws_id, 'project_id': project_id})
    assert created.status_code == 200
    task = created.json()
    assert task['title'] == 'Write tests'

    done = client.post(f"/api/tasks/{task['id']}/complete")
    assert done.status_code == 200
    assert done.json()['status'] == 'Done'


def test_task_activity_deduplicates_by_event_key(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    actor_id = bootstrap['current_user']['id']

    created = client.post('/api/tasks', json={'title': 'Activity dedupe task', 'workspace_id': ws_id, 'project_id': project_id})
    assert created.status_code == 200
    task_id = created.json()['id']

    from shared.models import ActivityLog, SessionLocal

    details = {
        "_event_key": f"Task:{task_id}:2:TaskAutomationRequested",
        "requested_at": "2026-03-03T13:17:26.275842+00:00",
        "instruction": "Same instruction payload",
        "source": "manual",
    }
    details_json = json.dumps(details, sort_keys=True)
    with SessionLocal() as db:
        db.add(
            ActivityLog(
                workspace_id=ws_id,
                project_id=project_id,
                task_id=task_id,
                actor_id=actor_id,
                action="TaskAutomationRequested",
                details=details_json,
            )
        )
        db.add(
            ActivityLog(
                workspace_id=ws_id,
                project_id=project_id,
                task_id=task_id,
                actor_id=actor_id,
                action="TaskAutomationRequested",
                details=details_json,
            )
        )
        db.commit()

    activity = client.get(f"/api/tasks/{task_id}/activity")
    assert activity.status_code == 200
    payload = activity.json()
    requested = [item for item in payload if item.get("action") == "TaskAutomationRequested"]
    assert len(requested) == 1


def test_task_complete_is_idempotent(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post('/api/tasks', json={'title': 'Complete idempotent', 'workspace_id': ws_id, 'project_id': project_id})
    assert created.status_code == 200
    task_id = created.json()['id']

    first = client.post(f"/api/tasks/{task_id}/complete")
    second = client.post(f"/api/tasks/{task_id}/complete")
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()['id'] == task_id
    assert second.json()['status'] == 'Done'


def test_patch_task_invokes_plugin_worktree_cleanup_hook(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post(
        '/api/tasks',
        json={'title': 'Worktree cleanup hook', 'workspace_id': ws_id, 'project_id': project_id},
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    from features.tasks import command_handlers as task_command_handlers

    calls: list[dict[str, str | None]] = []

    def _fake_cleanup(**kwargs):
        calls.append(
            {
                "task_id": str(kwargs.get("task_id") or ""),
                "project_id": str(kwargs.get("project_id") or "") or None,
                "status": str(kwargs.get("status") or ""),
            }
        )

    monkeypatch.setattr(task_command_handlers, "_maybe_cleanup_plugin_worktree", _fake_cleanup)

    patched = client.patch(f"/api/tasks/{task_id}", json={"status": "In Review"})
    assert patched.status_code == 200
    assert patched.json()['status'] == 'In Review'
    assert calls, "Expected worktree cleanup hook to be invoked after task patch."
    assert calls[-1]["task_id"] == task_id
    assert calls[-1]["project_id"] == project_id
    assert calls[-1]["status"] == "In Review"


def test_task_archive_restore_are_idempotent(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post('/api/tasks', json={'title': 'Archive restore idempotent', 'workspace_id': ws_id, 'project_id': project_id})
    assert created.status_code == 200
    task_id = created.json()['id']

    first_archive = client.post(f"/api/tasks/{task_id}/archive")
    second_archive = client.post(f"/api/tasks/{task_id}/archive")
    assert first_archive.status_code == 200
    assert second_archive.status_code == 200
    assert first_archive.json()['ok'] is True
    assert second_archive.json()['ok'] is True

    first_restore = client.post(f"/api/tasks/{task_id}/restore")
    second_restore = client.post(f"/api/tasks/{task_id}/restore")
    assert first_restore.status_code == 200
    assert second_restore.status_code == 200
    assert first_restore.json()['ok'] is True
    assert second_restore.json()['ok'] is True


def test_task_reopen_is_idempotent(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post('/api/tasks', json={'title': 'Reopen idempotent', 'workspace_id': ws_id, 'project_id': project_id})
    assert created.status_code == 200
    task_id = created.json()['id']

    first = client.post(f"/api/tasks/{task_id}/reopen")
    assert first.status_code == 200
    assert first.json()['id'] == task_id
    assert first.json()['status'] == 'To Do'

    completed = client.post(f"/api/tasks/{task_id}/complete")
    assert completed.status_code == 200
    assert completed.json()['status'] == 'Done'

    second = client.post(f"/api/tasks/{task_id}/reopen")
    assert second.status_code == 200
    assert second.json()['id'] == task_id
    assert second.json()['status'] == 'To Do'


def test_get_task_by_id_returns_task(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post('/api/tasks', json={'title': 'Lookup by id', 'workspace_id': ws_id, 'project_id': project_id})
    assert created.status_code == 200
    task = created.json()

    fetched = client.get(f"/api/tasks/{task['id']}")
    assert fetched.status_code == 200
    assert fetched.json()['id'] == task['id']
    assert fetched.json()['title'] == 'Lookup by id'


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


def test_task_external_refs_normalization_deduplicates_and_drops_whitespace_urls(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    task = client.post(
        '/api/tasks',
        json={
            'title': 'Normalized refs',
            'workspace_id': ws_id,
            'project_id': project_id,
            'external_refs': [
                {'url': ' https://example.com/deploy ', 'title': 'Deploy report'},
                {'url': 'https://example.com/deploy', 'title': 'Deploy report'},
                {'url': 'branch:task/abc123-implementation', 'title': 'Task branch'},
                {'url': 'deploy:health:http://gateway:6768/health:http_200', 'title': 'Health'},
                {'url': 'https://bad url.example.com/with-space', 'title': 'Bad'},
            ],
        },
    )
    assert task.status_code == 200
    refs = task.json().get('external_refs') or []
    urls = [str(item.get('url') or '') for item in refs if isinstance(item, dict)]

    assert urls.count('https://example.com/deploy') == 1
    assert 'branch:task/abc123-implementation' in urls
    assert 'deploy:health:http://gateway:6768/health:http_200' in urls
    assert 'https://bad url.example.com/with-space' not in urls


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


def test_create_project_returns_aggregate_fallback_when_view_unavailable(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']

    import features.projects.command_handlers as project_handlers

    monkeypatch.setattr(project_handlers, "load_project_view", lambda db, project_id: None)

    created = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Fallback Project'})
    assert created.status_code == 200
    payload = created.json()
    assert payload['name'] == 'Fallback Project'
    assert payload['workspace_id'] == ws_id
    assert payload['embedding_index_status'] == 'not_indexed'


def test_bootstrap_exposes_embedding_runtime_config(tmp_path, monkeypatch):
    from features.agents import mcp_registry

    monkeypatch_rows = [
        {
            'name': 'constructos-tools',
            'display_name': 'Constructos Tools',
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
            'name': 'constructos-tools',
            'display_name': 'Constructos Tools',
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
        json={'name': 'Docs updated', 'description': '## Overview\n\nUpdated project description.'},
    )
    assert patched.status_code == 200
    payload = patched.json()
    assert payload['id'] == project['id']
    assert payload['name'] == 'Docs updated'
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
    assert project['custom_statuses'] == ['Backlog', 'In Progress', 'Blocked', 'Done']

    board = client.get(f"/api/projects/{project['id']}/board")
    assert board.status_code == 200
    assert board.json()['statuses'] == ['Backlog', 'In Progress', 'Blocked', 'Done']

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
    assert patched_payload['custom_statuses'] == ['Backlog', 'In Progress', 'Ready for QA', 'Done']

    board_after = client.get(f"/api/projects/{project['id']}/board")
    assert board_after.status_code == 200
    assert board_after.json()['statuses'] == ['Backlog', 'In Progress', 'Ready for QA', 'Done']


def test_project_status_patch_does_not_reset_embedding_or_description(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    created = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'No reset patch project',
            'description': 'keep-me',
            'embedding_enabled': True,
            'chat_index_mode': 'KG_AND_VECTOR',
            'embedding_model': 'nomic-embed-text',
            'custom_statuses': ['To do', 'In progress', 'Done'],
        },
    )
    assert created.status_code == 200
    project = created.json()
    assert project['description'] == 'keep-me'
    assert project['embedding_enabled'] is True
    assert project['chat_index_mode'] == 'KG_AND_VECTOR'
    assert project['embedding_model'] == 'nomic-embed-text'

    patched = client.patch(
        f"/api/projects/{project['id']}",
        json={'custom_statuses': ['To do', 'Dev', 'QA', 'Lead', 'Done', 'Blocked']},
    )
    assert patched.status_code == 200
    payload = patched.json()
    assert payload['custom_statuses'] == ['To Do', 'Dev', 'QA', 'Lead', 'Done', 'Blocked']
    assert payload['description'] == 'keep-me'
    assert payload['embedding_enabled'] is True
    assert payload['chat_index_mode'] == 'KG_AND_VECTOR'
    assert payload['embedding_model'] == 'nomic-embed-text'

    refreshed = client.get('/api/bootstrap').json()
    refreshed_project = next(p for p in refreshed['projects'] if p['id'] == project['id'])
    assert refreshed_project['description'] == 'keep-me'
    assert refreshed_project['embedding_enabled'] is True
    assert refreshed_project['chat_index_mode'] == 'KG_AND_VECTOR'
    assert refreshed_project['embedding_model'] == 'nomic-embed-text'


def test_project_patch_can_explicitly_clear_nullable_field(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    created = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Nullable clear project',
            'context_pack_evidence_top_k': 12,
        },
    )
    assert created.status_code == 200
    project = created.json()
    assert project['context_pack_evidence_top_k'] == 12

    cleared = client.patch(
        f"/api/projects/{project['id']}",
        json={'context_pack_evidence_top_k': None},
    )
    assert cleared.status_code == 200
    payload = cleared.json()
    assert payload['context_pack_evidence_top_k'] is None

    refreshed = client.get('/api/bootstrap').json()
    refreshed_project = next(p for p in refreshed['projects'] if p['id'] == project['id'])
    assert refreshed_project['context_pack_evidence_top_k'] is None


def test_project_vector_index_distill_setting_defaults_and_can_be_patched(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    created = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Vector distill project',
        },
    )
    assert created.status_code == 200
    project = created.json()
    assert project['vector_index_distill_enabled'] is False

    patched = client.patch(
        f"/api/projects/{project['id']}",
        json={'vector_index_distill_enabled': True},
    )
    assert patched.status_code == 200
    payload = patched.json()
    assert payload['vector_index_distill_enabled'] is True

    refreshed = client.get('/api/bootstrap').json()
    refreshed_project = next(p for p in refreshed['projects'] if p['id'] == project['id'])
    assert refreshed_project['vector_index_distill_enabled'] is True


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


def test_project_board_exposes_live_automation_state(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    project = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Board automation state'}).json()
    task = client.post(
        '/api/tasks',
        json={
            'title': 'Automation task',
            'workspace_id': ws_id,
            'project_id': project['id'],
            'instruction': 'Do automation work',
        },
    )
    assert task.status_code == 200
    task_id = task.json()['id']

    queued = client.post(
        f'/api/tasks/{task_id}/automation/run',
        json={'instruction': 'Run now'},
    )
    assert queued.status_code == 200
    assert queued.json().get('automation_state') == 'queued'

    board = client.get(f"/api/projects/{project['id']}/board")
    assert board.status_code == 200
    lane_tasks = [item for lane in board.json()['lanes'].values() for item in lane]
    board_task = next(item for item in lane_tasks if item['id'] == task_id)
    assert board_task.get('automation_state') == 'queued'

    listed = client.get(f"/api/tasks?workspace_id={ws_id}&project_id={project['id']}")
    assert listed.status_code == 200
    listed_task = next(item for item in listed.json()['items'] if item['id'] == task_id)
    assert listed_task.get('automation_state') == 'queued'


def test_effective_runtime_deploy_target_requires_runtime_for_deployable_slice_on_docker_project(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService

    service = AgentTaskService(actor_user_id=bootstrap['current_user']['id'])
    docker_configured = service.apply_project_plugin_config(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key='docker_compose',
        enabled=True,
        config={
            'runtime_deploy_health': {
                'required': False,
                'stack': 'constructos-ws-default',
                'host': 'gateway',
                'port': 6768,
                'health_path': '/health',
                'require_http_200': True,
            },
        },
    )
    assert docker_configured['enabled'] is True

    from features.agents.runner import _effective_runtime_deploy_target_for_task
    from shared.models import SessionLocal

    with SessionLocal() as db:
        stack, host, port, health_path, runtime_required = _effective_runtime_deploy_target_for_task(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            delivery_mode='deployable_slice',
        )
        assert stack == 'constructos-ws-default'
        assert host == 'gateway'
        assert port == 6768
        assert health_path == '/health'
        assert runtime_required is True

        _stack, _host, _port, _health_path, merged_increment_runtime_required = _effective_runtime_deploy_target_for_task(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            delivery_mode='merged_increment',
        )
        assert merged_increment_runtime_required is False


def test_queue_qa_handoff_requests_requires_strict_deploy_evidence(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead deploy',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Deploy current slice.',
            'delivery_mode': 'deployable_slice',
        },
    )
    assert lead_task.status_code == 200

    from features.agents.runner import _queue_qa_handoff_requests
    from shared.models import SessionLocal

    with SessionLocal() as db:
        queued = _queue_qa_handoff_requests(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            lead_task_id=lead_task.json()['id'],
            actor_user_id=bootstrap['current_user']['id'],
            lead_handoff_token=f"lead:{lead_task.json()['id']}:test",
            lead_handoff_at=datetime.now(timezone.utc).isoformat(),
            lead_handoff_refs=[],
        )
        assert queued == 0


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


def test_tour_preference_patch_preserves_chat_execution_preferences(tmp_path):
    client = build_client(tmp_path)

    set_chat = client.patch(
        '/api/me/preferences',
        json={'agent_chat_model': 'claude:sonnet', 'agent_chat_reasoning_effort': 'medium'},
    )
    assert set_chat.status_code == 200
    assert set_chat.json()['agent_chat_model'] == 'claude:sonnet'

    updated = client.patch('/api/me/preferences', json={'onboarding_quick_tour_completed': True})
    assert updated.status_code == 200
    assert updated.json()['agent_chat_model'] == 'claude:sonnet'
    assert updated.json()['onboarding_quick_tour_completed'] is True

    bootstrap = client.get('/api/bootstrap')
    assert bootstrap.status_code == 200
    assert bootstrap.json()['current_user']['agent_chat_model'] == 'claude:sonnet'
    assert bootstrap.json()['current_user']['onboarding_quick_tour_completed'] is True


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


def test_default_admin_allows_blank_password_login_until_password_changes(tmp_path):
    client = build_client(tmp_path)

    client.post('/api/auth/logout')
    blank_login = client.post('/api/auth/login', json={'username': 'admin', 'password': ''})
    assert blank_login.status_code == 200
    assert blank_login.json()['user']['username'] == 'admin'


def test_blank_password_login_rejected_after_admin_password_change(tmp_path):
    client = build_client(tmp_path)

    changed = client.post(
        '/api/auth/change-password',
        json={'current_password': 'admin', 'new_password': 'admin-new-pass-123'},
    )
    assert changed.status_code == 200

    client.post('/api/auth/logout')
    blank_login = client.post('/api/auth/login', json={'username': 'admin', 'password': ''})
    assert blank_login.status_code == 401


def test_owner_can_create_user_with_admin_role(tmp_path):
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


def test_owner_can_update_workspace_user_role(tmp_path):
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


def test_owner_can_deactivate_workspace_user(tmp_path):
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


def test_admin_can_create_member_user_but_not_admin_role(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    admin_created = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'workspace-admin', 'role': 'Admin'},
    )
    assert admin_created.status_code == 200
    admin_temp_password = admin_created.json()['temporary_password']

    client.post('/api/auth/logout')
    _activate_user_password(
        client,
        username='workspace-admin',
        temporary_password=admin_temp_password,
        new_password='workspace-admin-pass-123',
    )

    member_created = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'member-created-by-admin', 'role': 'Member'},
    )
    assert member_created.status_code == 200
    assert member_created.json()['user']['role'] == 'Member'

    blocked = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'admin-created-by-admin', 'role': 'Admin'},
    )
    assert blocked.status_code == 403
    assert blocked.json()['detail'] == 'Only workspace owners can manage Owner/Admin roles'


def test_admin_cannot_manage_admin_tier_users(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    owner_user_id = bootstrap['current_user']['id']

    admin_created = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'workspace-admin', 'role': 'Admin'},
    )
    assert admin_created.status_code == 200
    admin_temp_password = admin_created.json()['temporary_password']

    member_created = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'member-target', 'role': 'Member'},
    )
    assert member_created.status_code == 200
    member_user_id = member_created.json()['user']['id']

    client.post('/api/auth/logout')
    _activate_user_password(
        client,
        username='workspace-admin',
        temporary_password=admin_temp_password,
        new_password='workspace-admin-pass-456',
    )

    promote_blocked = client.post(
        f'/api/admin/users/{member_user_id}/set-role',
        json={'workspace_id': ws_id, 'role': 'Admin'},
    )
    assert promote_blocked.status_code == 403
    assert promote_blocked.json()['detail'] == 'Only workspace owners can manage Owner/Admin roles'

    reset_blocked = client.post(
        f'/api/admin/users/{owner_user_id}/reset-password',
        json={'workspace_id': ws_id},
    )
    assert reset_blocked.status_code == 403
    assert reset_blocked.json()['detail'] == 'Only workspace owners can manage Owner/Admin roles'

    deactivate_blocked = client.post(
        f'/api/admin/users/{owner_user_id}/deactivate',
        json={'workspace_id': ws_id},
    )
    assert deactivate_blocked.status_code == 403
    assert deactivate_blocked.json()['detail'] == 'Only workspace owners can manage Owner/Admin roles'


def test_owner_cannot_demote_last_owner(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    owner_user_id = bootstrap['current_user']['id']

    blocked = client.post(
        f'/api/admin/users/{owner_user_id}/set-role',
        json={'workspace_id': ws_id, 'role': 'Admin'},
    )
    assert blocked.status_code == 409
    assert blocked.json()['detail'] == 'Workspace must have at least one owner'


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


def test_workspace_users_list_includes_background_runtime_for_bot_users(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DEFAULT_EXECUTION_PROVIDER", "codex")
    monkeypatch.setenv("AGENT_CODEX_MODEL", "gpt-5-runtime")
    monkeypatch.setenv("AGENT_CLAUDE_MODEL", "sonnet")
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    users_page = client.get(f'/api/admin/users?workspace_id={ws_id}')

    assert users_page.status_code == 200
    items = {str(item["username"]): item for item in users_page.json()["items"]}
    codex_bot = items["codex-bot"]
    claude_bot = items["claude-bot"]
    assert codex_bot["can_configure_background_execution"] is True
    assert codex_bot["is_background_execution_selected"] is True
    assert codex_bot["background_agent_provider"] == "codex"
    assert claude_bot["can_configure_background_execution"] is True
    assert claude_bot["is_background_execution_selected"] is False
    assert claude_bot["background_agent_provider"] == "claude"


def test_admin_can_switch_workspace_background_runtime_to_claude_bot(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DEFAULT_EXECUTION_PROVIDER", "codex")
    monkeypatch.setenv("AGENT_CODEX_MODEL", "gpt-5-runtime")
    monkeypatch.setenv("AGENT_CLAUDE_MODEL", "sonnet")
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    users_page = client.get(f'/api/admin/users?workspace_id={ws_id}')
    assert users_page.status_code == 200
    claude_bot = next((item for item in users_page.json()["items"] if item["username"] == "claude-bot"), None)
    assert claude_bot is not None

    updated = client.post(
        f'/api/admin/users/{claude_bot["id"]}/agent-runtime',
        json={
            'workspace_id': ws_id,
            'model': 'claude:opus',
            'use_for_background_processing': True,
        },
    )

    assert updated.status_code == 200
    payload = updated.json()
    assert payload["provider"] == "claude"
    assert payload["model"] == "claude:opus"
    assert payload["is_background_execution_selected"] is True

    users_page = client.get(f'/api/admin/users?workspace_id={ws_id}')
    assert users_page.status_code == 200
    items = {str(item["username"]): item for item in users_page.json()["items"]}
    assert items["claude-bot"]["is_background_execution_selected"] is True
    assert items["claude-bot"]["background_agent_model"] == "claude:opus"
    assert items["codex-bot"]["is_background_execution_selected"] is False


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

    from shared.models import Notification, Project, SessionLocal

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

    from shared.models import Notification, Project, SessionLocal

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

    from shared.models import Project, SessionLocal

    with SessionLocal() as db:
        rows = db.execute(text("PRAGMA index_list('notifications')")).all()
    names = {str(row[1]) for row in rows}
    assert 'ix_notifications_user_created_at' in names


def test_notifications_table_has_typed_columns_and_dedupe_index(tmp_path):
    build_client(tmp_path)

    from shared.models import Project, SessionLocal

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
    assert row.dedupe_key == f"task-assigned:{task_id}:none:{assignee_id}"
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


def test_team_mode_routed_task_clears_human_assignee_and_keeps_agent_slot(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    actor_id = bootstrap['current_user']['id']
    from shared.settings import CODEX_SYSTEM_USER_ID

    _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Team mode routed developer task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'assignee_id': actor_id,
            'assigned_agent_code': 'dev-a',
            'status': 'To Do',
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload['assigned_agent_code'] == 'dev-a'
    assert payload['assignee_id'] == CODEX_SYSTEM_USER_ID


def test_team_mode_routed_task_skips_human_assignment_notification(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    actor_id = bootstrap['current_user']['id']

    _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Team mode routed task skips assignment notification',
            'workspace_id': ws_id,
            'project_id': project_id,
            'assignee_id': actor_id,
            'assigned_agent_code': 'dev-a',
            'status': 'To Do',
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


def test_patch_task_preserves_event_state_assigned_agent_code_when_row_is_stale(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Preserve routed agent slot on patch',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    from shared.eventing import append_event
    from shared.models import Project, SessionLocal

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=task_id,
            event_type='TaskUpdated',
            payload={
                'assigned_agent_code': 'lead-a',
                'assignee_id': None,
                'status': 'In Progress',
            },
            metadata={
                'actor_id': bootstrap['current_user']['id'],
                'workspace_id': ws_id,
                'project_id': project_id,
                'task_id': task_id,
            },
        )
        db.commit()

    patched = client.patch(
        f'/api/tasks/{task_id}',
        json={
            'external_refs': [
                {'url': 'file:docker-compose.yml', 'title': 'compose manifest'},
            ],
        },
    )
    assert patched.status_code == 200
    payload = patched.json()
    assert payload['assigned_agent_code'] == 'lead-a'


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

    patched = client.patch(f'/api/tasks/{task_id}', json={'status': 'In Progress'})
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
    assert row.dedupe_key == f"watch-status:{task_id}:{watcher_id}:In Progress:3"
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


def test_project_membership_changed_notification_skips_self_upsert(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    current_user_id = bootstrap['current_user']['id']

    created = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'No self membership ping',
        },
    )
    assert created.status_code == 200
    project_id = created.json()['id']

    from shared.models import Notification, SessionLocal
    from shared.typed_notifications import NOTIFICATION_TYPE_PROJECT_MEMBERSHIP_CHANGED

    with SessionLocal() as db:
        rows = db.execute(
            select(Notification).where(
                Notification.user_id == current_user_id,
                Notification.project_id == project_id,
                Notification.notification_type == NOTIFICATION_TYPE_PROJECT_MEMBERSHIP_CHANGED,
            )
        ).scalars().all()
    assert rows == []


def test_agent_created_project_emits_initial_membership_notification_for_default_human_member(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    from shared.models import Notification, SessionLocal
    from shared.settings import DEFAULT_USER_ID
    from shared.typed_notifications import NOTIFICATION_TYPE_PROJECT_MEMBERSHIP_CHANGED

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})

    service = AgentTaskService()
    created = service.create_project(name='Agent created project notification suppression')

    with SessionLocal() as db:
        rows = db.execute(
            select(Notification).where(
                Notification.user_id == DEFAULT_USER_ID,
                Notification.project_id == created['id'],
                Notification.notification_type == NOTIFICATION_TYPE_PROJECT_MEMBERSHIP_CHANGED,
            ).order_by(Notification.created_at.asc(), Notification.id.asc())
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].source_event == "ProjectMemberUpserted"


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
    assert status.json()['automation_state'] in {'queued', 'running', 'completed'}
    assert status.json()['last_agent_error'] is None


def test_task_automation_status_404_for_missing_task(tmp_path):
    client = build_client(tmp_path)
    res = client.get('/api/tasks/missing-task-id/automation')
    assert res.status_code == 404


def test_agent_service_can_request_automation_run(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    created = client.post('/api/tasks', json={'title': 'Agent task', 'workspace_id': ws_id, 'project_id': project_id}).json()

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    monkeypatch.setattr(
        svc_module,
        "classify_instruction_intent",
        lambda **_: {
            "execution_intent": False,
            "execution_kickoff_intent": False,
            "project_creation_intent": False,
            "workflow_scope": "unknown",
            "execution_mode": "unknown",
            "task_completion_requested": False,
            "reason": "generic",
        },
    )

    service = AgentTaskService()
    run = service.request_task_automation_run(
        task_id=created['id'],
        instruction='Agent instruction',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert run['automation_state'] == 'queued'

    status = service.get_task_automation_status(task_id=created['id'], auth_token=svc_module.MCP_AUTH_TOKEN or None)
    assert status['automation_state'] == 'queued'


def test_instruction_intent_classifier_uses_application_cache(monkeypatch):
    import features.agents.intent_classifier as intent_classifier_module

    intent_classifier_module.clear_instruction_intent_cache()
    intent_classifier_module.reset_instruction_intent_stats()
    calls = {"count": 0}

    def _fake_prompt(**_kwargs):
        calls["count"] += 1
        return {
            "execution_intent": True,
            "execution_kickoff_intent": False,
            "project_creation_intent": False,
            "workflow_scope": "unknown",
            "execution_mode": "resume_execution",
            "deploy_requested": False,
            "docker_compose_requested": False,
            "requested_port": None,
            "project_name_provided": False,
            "task_completion_requested": False,
            "reason": "cached",
        }

    monkeypatch.setattr(intent_classifier_module, "run_structured_codex_prompt", _fake_prompt)

    first = intent_classifier_module.classify_instruction_intent(
        instruction="Implement task automation now.",
        workspace_id="ws-1",
        project_id="project-1",
        session_id="session-1",
    )
    second = intent_classifier_module.classify_instruction_intent(
        instruction="Implement task automation now.",
        workspace_id="ws-1",
        project_id="project-1",
        session_id="session-1",
    )

    assert first == second
    assert calls["count"] == 1
    stats = intent_classifier_module.get_instruction_intent_stats()
    assert stats["classify_calls"] == 2
    assert stats["cache_hits"] == 1
    assert stats["cache_misses"] == 1


def test_agent_service_request_automation_run_classifies_once_for_manual_request(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    created = client.post('/api/tasks', json={'title': 'Single classification task', 'workspace_id': ws_id, 'project_id': project_id}).json()

    from features.agents.service import AgentTaskService
    import features.agents.intent_classifier as intent_classifier_module
    import features.agents.service as svc_module

    intent_classifier_module.clear_instruction_intent_cache()
    intent_classifier_module.reset_instruction_intent_stats()
    calls = {"count": 0}

    def _fake_prompt(**_kwargs):
        calls["count"] += 1
        return {
            "execution_intent": True,
            "execution_kickoff_intent": False,
            "project_creation_intent": False,
            "workflow_scope": "unknown",
            "execution_mode": "resume_execution",
            "deploy_requested": False,
            "docker_compose_requested": False,
            "requested_port": None,
            "project_name_provided": False,
            "task_completion_requested": False,
            "reason": "single-call",
        }

    monkeypatch.setattr(intent_classifier_module, "run_structured_codex_prompt", _fake_prompt)

    service = AgentTaskService()
    run = service.request_task_automation_run(
        task_id=created['id'],
        instruction='Please implement the requested change.',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )

    assert run['automation_state'] == 'queued'
    assert calls["count"] == 1
    stats = intent_classifier_module.get_instruction_intent_stats()
    assert stats["cache_misses"] == 1
    assert stats["resolve_reused_envelope"] >= 1


def test_task_automation_run_prefers_provided_intent_envelope_without_reclassification(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    created = client.post('/api/tasks', json={'title': 'Preclassified task', 'workspace_id': ws_id, 'project_id': project_id}).json()

    import features.agents.intent_classifier as intent_classifier_module

    intent_classifier_module.clear_instruction_intent_cache()
    intent_classifier_module.reset_instruction_intent_stats()

    def _should_not_run(**_kwargs):
        raise AssertionError("classifier should not run when the full intent envelope is provided")

    monkeypatch.setattr(intent_classifier_module, "run_structured_codex_prompt", _should_not_run)

    run = client.post(
        f"/api/tasks/{created['id']}/automation/run",
        json={
            'instruction': 'Continue the existing execution.',
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
            'workflow_scope': 'unknown',
            'execution_mode': 'resume_execution',
            'task_completion_requested': False,
            'classifier_reason': 'provided-upstream',
        },
    )
    assert run.status_code == 200
    assert run.json()['automation_state'] == 'queued'
    stats = intent_classifier_module.get_instruction_intent_stats()
    assert stats["cache_hits"] == 0
    assert stats["cache_misses"] == 0
    assert stats["resolve_reused_envelope"] >= 1


def test_task_automation_stream_classifies_once_and_persists_intent_envelope(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    created = client.post('/api/tasks', json={'title': 'Stream classify once', 'workspace_id': ws_id, 'project_id': project_id}).json()
    task_id = created['id']

    import features.agents.intent_classifier as intent_classifier_module
    from features.tasks import api as tasks_api
    from features.agents.executor import AutomationOutcome

    intent_classifier_module.clear_instruction_intent_cache()
    intent_classifier_module.reset_instruction_intent_stats()
    calls = {"count": 0}
    captured: dict[str, object] = {}

    def _fake_prompt(**_kwargs):
        calls["count"] += 1
        return {
            "execution_intent": True,
            "execution_kickoff_intent": False,
            "project_creation_intent": False,
            "workflow_scope": "unknown",
            "execution_mode": "resume_execution",
            "deploy_requested": False,
            "docker_compose_requested": False,
            "requested_port": None,
            "project_name_provided": False,
            "task_completion_requested": False,
            "reason": "stream-classified",
        }

    def _fake_execute_task_automation_stream(**kwargs):
        captured.update(kwargs)
        return AutomationOutcome(action='comment', summary='ok', comment='done', usage={})

    monkeypatch.setattr(intent_classifier_module, "run_structured_codex_prompt", _fake_prompt)
    monkeypatch.setattr(tasks_api, "execute_task_automation_stream", _fake_execute_task_automation_stream)

    run = client.post(
        f'/api/tasks/{task_id}/automation/stream',
        json={'instruction': 'Stream execution should classify once.'},
    )
    assert run.status_code == 200
    assert calls["count"] == 1
    assert captured["execution_kickoff_intent"] is False
    assert captured["workflow_scope"] == "unknown"
    assert captured["execution_mode"] == "resume_execution"
    assert captured["task_completion_requested"] is False

    status = client.get(f"/api/tasks/{task_id}/automation")
    assert status.status_code == 200
    payload = status.json()
    assert payload["last_requested_execution_intent"] is True
    assert payload["last_requested_execution_mode"] == "resume_execution"
    stats = intent_classifier_module.get_instruction_intent_stats()
    assert stats["cache_misses"] == 1


def test_task_automation_stream_prefers_provided_intent_envelope_without_reclassification(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    created = client.post('/api/tasks', json={'title': 'Stream preclassified', 'workspace_id': ws_id, 'project_id': project_id}).json()
    task_id = created['id']

    import features.agents.intent_classifier as intent_classifier_module
    from features.tasks import api as tasks_api
    from features.agents.executor import AutomationOutcome

    intent_classifier_module.clear_instruction_intent_cache()
    intent_classifier_module.reset_instruction_intent_stats()
    captured: dict[str, object] = {}

    def _should_not_run(**_kwargs):
        raise AssertionError("classifier should not run when the stream request already includes the full intent envelope")

    def _fake_execute_task_automation_stream(**kwargs):
        captured.update(kwargs)
        return AutomationOutcome(action='comment', summary='ok', comment='done', usage={})

    monkeypatch.setattr(intent_classifier_module, "run_structured_codex_prompt", _should_not_run)
    monkeypatch.setattr(tasks_api, "execute_task_automation_stream", _fake_execute_task_automation_stream)

    run = client.post(
        f'/api/tasks/{task_id}/automation/stream',
        json={
            'instruction': 'Continue the existing stream execution.',
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
            'workflow_scope': 'unknown',
            'execution_mode': 'resume_execution',
            'task_completion_requested': False,
            'classifier_reason': 'provided-upstream',
        },
    )
    assert run.status_code == 200
    assert captured["execution_mode"] == "resume_execution"
    assert captured["workflow_scope"] == "unknown"
    stats = intent_classifier_module.get_instruction_intent_stats()
    assert stats["cache_hits"] == 0
    assert stats["cache_misses"] == 0
    assert stats["resolve_reused_envelope"] >= 1


def test_agent_service_request_automation_run_classifies_team_mode_kickoff(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_resp = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Lead kickoff guard project',
            'custom_statuses': ['To do', 'In Progress', 'In Review', 'Awaiting decision', 'Blocked', 'Completed'],
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    created = client.post(
        '/api/tasks',
        json={
            'title': 'Lead kickoff task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'To do',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Lead coordination task.',
        },
    ).json()

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    monkeypatch.setattr(
        svc_module,
        "classify_instruction_intent",
        lambda **_: {
            "execution_intent": True,
            "execution_kickoff_intent": True,
            "project_creation_intent": False,
            "workflow_scope": "team_mode",
            "execution_mode": "kickoff_only",
            "task_completion_requested": False,
            "reason": "kickoff",
        },
    )

    service = AgentTaskService()
    result = service.request_task_automation_run(
        task_id=created['id'],
        instruction='Kickoff execution for the Tetris project in lead-first mode. Dispatch only.',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert result["ok"] is True
    assert result["automation_state"] == "queued"

    status = client.get(f"/api/tasks/{created['id']}/automation")
    assert status.status_code == 200
    payload = status.json()
    assert payload["last_requested_workflow_scope"] == "team_mode"
    assert payload["last_requested_execution_mode"] == "kickoff_only"


def test_agent_service_request_automation_run_defaults_fresh_lead_task_to_kickoff(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_resp = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Fresh lead kickoff project',
            'custom_statuses': ['To do', 'In Progress', 'In Review', 'Awaiting decision', 'Blocked', 'Completed'],
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    dev_task = client.post(
        '/api/tasks',
        json={
            'title': 'Build gameplay foundation',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'To do',
            'assignee_id': team['dev1'],
            'assigned_agent_code': 'dev-a',
            'instruction': 'Implement gameplay foundation.',
        },
    ).json()
    qa_task = client.post(
        '/api/tasks',
        json={
            'title': 'Verify gameplay quality',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'To do',
            'assignee_id': team['qa'],
            'assigned_agent_code': 'qa-a',
            'instruction': 'Verify gameplay quality.',
        },
    ).json()
    lead_task = client.post(
        '/api/tasks',
        json={
            'title': 'Coordinate integration and deployment',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'To do',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Review active Dev and QA tasks, drive handoffs, and keep delivery moving.',
        },
    ).json()

    assert client.patch(
        f"/api/tasks/{dev_task['id']}",
        json={"task_relationships": [{"kind": "delivers_to", "task_ids": [lead_task['id']], "statuses": ["Awaiting decision"]}]},
    ).status_code == 200
    assert client.patch(
        f"/api/tasks/{qa_task['id']}",
        json={"task_relationships": [
            {"kind": "hands_off_to", "task_ids": [lead_task['id']], "statuses": ["In Progress"]},
            {"kind": "escalates_to", "task_ids": [lead_task['id']], "statuses": ["Awaiting decision", "Blocked"]},
        ]},
    ).status_code == 200
    assert client.patch(
        f"/api/tasks/{lead_task['id']}",
        json={"task_relationships": [
            {"kind": "depends_on", "task_ids": [dev_task['id']], "statuses": ["Awaiting decision"]},
            {"kind": "depends_on", "task_ids": [dev_task['id'], qa_task['id']], "statuses": ["Blocked"]},
        ]},
    ).status_code == 200

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    import features.tasks.command_handlers as task_handlers_module

    kickoff_classification = {
        "execution_intent": True,
        "execution_kickoff_intent": True,
        "project_creation_intent": False,
        "workflow_scope": "team_mode",
        "execution_mode": "kickoff_only",
        "task_completion_requested": False,
        "reason": "kickoff",
    }
    monkeypatch.setattr(svc_module, "classify_instruction_intent", lambda **_: kickoff_classification)
    monkeypatch.setattr(task_handlers_module, "classify_instruction_intent", lambda **_: kickoff_classification)

    service = AgentTaskService()
    run = service.request_task_automation_run(
        task_id=lead_task['id'],
        instruction=None,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert run['automation_state'] == 'queued'

    status = service.get_task_automation_status(task_id=lead_task['id'], auth_token=svc_module.MCP_AUTH_TOKEN or None)
    assert status['last_requested_execution_intent'] is True
    assert status['last_requested_execution_kickoff_intent'] is True
    assert status['last_requested_workflow_scope'] == 'team_mode'
    assert status['last_requested_execution_mode'] == 'kickoff_only'


def test_agent_service_skips_self_requeue_for_running_task_with_same_instruction(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    created = client.post('/api/tasks', json={'title': 'Agent self requeue guard', 'workspace_id': ws_id, 'project_id': project_id}).json()
    task_id = created['id']

    from shared.settings import AGENT_SYSTEM_USER_ID
    from features.agents.service import AgentTaskService
    import features.agents.runner as runner_module
    import features.agents.service as svc_module

    monkeypatch.setattr(runner_module, "start_automation_runner", lambda: None)
    monkeypatch.setattr(runner_module, "wake_automation_runner", lambda: None)

    service = AgentTaskService(require_token=False, actor_user_id=AGENT_SYSTEM_USER_ID)
    first = service.request_task_automation_run(
        task_id=task_id,
        instruction='Same instruction',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id='test-run-first',
    )
    assert first['ok'] is True
    assert first['automation_state'] == 'queued'

    run = service.request_task_automation_run(
        task_id=task_id,
        instruction='Same instruction',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id='test-run-second',
    )
    assert run['ok'] is True
    assert run['automation_state'] == 'queued'
    assert run.get('skipped') is True

    status = service.get_task_automation_status(task_id=task_id, auth_token=svc_module.MCP_AUTH_TOKEN or None)
    assert status['automation_state'] == 'queued'


def test_task_automation_requested_event_wakes_runner(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    created = client.post('/api/tasks', json={'title': 'Wake runner task', 'workspace_id': ws_id, 'project_id': project_id}).json()

    import features.agents.runner as runner_module

    calls = {"wake": 0, "start": 0}

    def fake_wake():
        calls["wake"] += 1

    def fake_start():
        calls["start"] += 1

    monkeypatch.setattr(runner_module, "start_automation_runner", fake_start)
    monkeypatch.setattr(runner_module, "wake_automation_runner", fake_wake)

    queued = client.post(f"/api/tasks/{created['id']}/automation/run", json={'instruction': 'wake check'})
    assert queued.status_code == 200
    assert calls["start"] >= 1
    assert calls["wake"] >= 1


def test_runner_processes_queued_automation(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    created_project = client.post(
        '/api/projects',
        json={'workspace_id': ws_id, 'name': 'Runner Generic Project'},
    )
    assert created_project.status_code == 200
    project_id = created_project.json()['id']
    task = client.post(
        '/api/tasks',
        json={
            'title': 'Runner task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'To do',
        },
    )
    assert task.status_code == 200
    task = task.json()

    from features.agents import runner as runner_module
    from features.agents.executor import AutomationOutcome

    def _fake_execute_task_automation(**_kwargs):
        return AutomationOutcome(
            action='comment',
            summary='Runner completed task automation.',
            comment='Runner completed task automation.',
            usage={
                'input_tokens': 900,
                'cached_input_tokens': 450,
                'output_tokens': 120,
                'prompt_mode': 'resume',
                'prompt_segment_chars': {
                    'instruction': 900,
                    'graph_context': 450,
                },
            },
            codex_session_id='task-thread-001',
            resume_attempted=True,
            resume_succeeded=True,
            resume_fallback_used=False,
        )

    monkeypatch.setattr(runner_module, "execute_task_automation", _fake_execute_task_automation)

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
    assert payload['last_agent_prompt_mode'] == 'resume'
    assert payload['last_agent_prompt_segment_chars']['instruction'] == 900
    assert payload['last_agent_codex_session_id'] == 'task-thread-001'
    assert payload['last_agent_codex_resume_attempted'] is True
    assert payload['last_agent_codex_resume_succeeded'] is True

    comments = client.get(f"/api/tasks/{task['id']}/comments")
    assert comments.status_code == 200
    # Executor may apply updates directly without adding an extra runner comment.
    assert isinstance(comments.json(), list)


def test_runner_dispatch_uses_plain_text_stream_events(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    task = client.post(
        '/api/tasks',
        json={
            'title': 'Runner stream dispatch task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'To do',
        },
    )
    assert task.status_code == 200
    task_id = task.json()['id']

    from features.agents import runner as runner_module
    from features.agents.executor import AutomationOutcome

    observed_kwargs: dict[str, object] = {}

    def _fake_execute_task_automation(**kwargs):
        observed_kwargs.update(kwargs)
        return AutomationOutcome(action='comment', summary='ok', comment='ok')

    monkeypatch.setattr(runner_module, "execute_task_automation", _fake_execute_task_automation)

    queued = client.post(f"/api/tasks/{task_id}/automation/run", json={'instruction': 'Do runner stream check'})
    assert queued.status_code == 200
    assert queued.json()['automation_state'] == 'queued'

    processed = runner_module.run_queued_automation_once(limit=5)
    assert processed >= 1
    assert observed_kwargs.get('stream_plain_text') is True


def test_runner_shared_workspace_mode_allows_only_one_parallel_running_job_per_project(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Shared workspace project'})
    assert project.status_code == 200
    project_id = project.json()['id']

    enable_git = client.post(
        f"/api/projects/{project_id}/plugins/git_delivery/enabled",
        json={"enabled": True},
    )
    assert enable_git.status_code == 200
    assert bool(enable_git.json().get("enabled")) is True

    task_a = client.post(
        '/api/tasks',
        json={
            'title': 'Shared runner task A',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'To do',
            'instruction': 'Implement task A',
        },
    )
    task_b = client.post(
        '/api/tasks',
        json={
            'title': 'Shared runner task B',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'To do',
            'instruction': 'Implement task B',
        },
    )
    assert task_a.status_code == 200
    assert task_b.status_code == 200
    task_a_id = task_a.json()['id']
    task_b_id = task_b.json()['id']

    queued_a = client.post(f"/api/tasks/{task_a_id}/automation/run", json={'instruction': 'run A'})
    queued_b = client.post(f"/api/tasks/{task_b_id}/automation/run", json={'instruction': 'run B'})
    assert queued_a.status_code == 200
    assert queued_b.status_code == 200

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome

    def _fake_execute_task_automation(**_kwargs):
        return AutomationOutcome(action='comment', summary='done', comment='done')

    monkeypatch.setattr(runner_module, "execute_task_automation", _fake_execute_task_automation)

    processed_first = runner_module.run_queued_automation_once(limit=10)
    assert processed_first == 1

    status_a = client.get(f"/api/tasks/{task_a_id}/automation").json().get("automation_state")
    status_b = client.get(f"/api/tasks/{task_b_id}/automation").json().get("automation_state")
    assert sorted([status_a, status_b]) == ["completed", "queued"]

    processed_second = runner_module.run_queued_automation_once(limit=10)
    assert processed_second == 1

    final_a = client.get(f"/api/tasks/{task_a_id}/automation").json().get("automation_state")
    final_b = client.get(f"/api/tasks/{task_b_id}/automation").json().get("automation_state")
    assert final_a == "completed"
    assert final_b == "completed"


def test_runner_contract_validation_rejects_trivial_only_dev_changes_when_required():
    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome

    original_inspect_handoff = runner_module._inspect_committed_task_branch_handoff
    original_merge_to_main = runner_module._merge_current_task_branch_to_main

    def _fake_inspect_handoff(_git_evidence):
        return {
            "branch_name": "task/demo-contract",
            "branch_exists": True,
            "branch_head_sha": "215590d",
            "main_head_sha": "1111111",
            "branch_differs_from_main": True,
            "branch_ahead_of_main": True,
            "branch_reachable_from_main": False,
            "main_reachable_from_branch": True,
            "after_head_sha": "215590d",
            "after_on_task_branch": True,
            "after_is_dirty": False,
        }

    runner_module._inspect_committed_task_branch_handoff = _fake_inspect_handoff
    outcome = AutomationOutcome(
        action="comment",
        summary="Updated docs and compose.",
        comment="Done.",
        execution_outcome_contract={
            "contract_version": 1,
            "files_changed": ["README.md", "docker-compose.yml"],
            "commit_sha": "215590d",
            "branch": "task/demo-contract",
            "tests_run": False,
            "tests_passed": False,
            "artifacts": [{"kind": "note", "ref": "docs-only"}],
        },
    )

    try:
        error = runner_module._validate_execution_outcome_contract(
            outcome=outcome,
            assignee_role="Developer",
            task_status="In Progress",
            git_delivery_enabled=True,
            require_nontrivial_dev_changes=True,
            git_evidence={
                "task_branch": "task/demo-contract",
                "after_head_sha": "215590d",
                "after_on_task_branch": True,
                "after_is_dirty": False,
            },
        )
        assert error is not None
        assert "non-trivial code/content change" in error
    finally:
        runner_module._inspect_committed_task_branch_handoff = original_inspect_handoff


def test_runner_contract_validation_uses_repo_state_fallback_for_task_worktree_changes(tmp_path, monkeypatch):
    import subprocess

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome
    from shared.project_repository import (
        ensure_project_repository_initialized,
        resolve_task_branch_name,
        resolve_task_worktree_path,
    )

    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path))
    project_name = "Tetris"
    project_id = "proj-123"
    task_id = "50f2a9dc-3f38-52e7-875e-033b4d057d49"
    title = "Build core gameplay loop"

    repo = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    branch = resolve_task_branch_name(task_id=task_id, title=title)
    worktree = resolve_task_worktree_path(project_name=project_name, project_id=project_id, task_id=task_id)

    subprocess.run(["git", "worktree", "add", "-b", branch, str(worktree), "main"], cwd=str(repo), check=True, capture_output=True, text=True)
    (worktree / "index.html").write_text("<!doctype html><title>Tetris</title>\n", encoding="utf-8")
    (worktree / "app.js").write_text("console.log('tetris');\n", encoding="utf-8")
    subprocess.run(["git", "add", "index.html", "app.js"], cwd=str(worktree), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "Implement playable browser Tetris core loop"], cwd=str(worktree), check=True, capture_output=True, text=True)

    outcome = AutomationOutcome(
        action="comment",
        summary="Implemented playable browser Tetris core loop.",
        comment="Ready for Lead handoff.",
        execution_outcome_contract={
            "contract_version": 1,
            "files_changed": [],
            "commit_sha": None,
            "branch": None,
            "tests_run": False,
            "tests_passed": False,
            "artifacts": [{"kind": "note", "ref": "dev:implemented"}],
        },
        usage={},
    )

    git_evidence = runner_module._merge_git_evidence(
        runner_module._collect_git_evidence_from_outcome(outcome),
        runner_module._collect_git_evidence_from_repo_state(
            project_name=project_name,
            project_id=project_id,
            task_id=task_id,
            title=title,
        ),
    )

    assert git_evidence.get("task_branch") == branch
    assert str(git_evidence.get("after_head_sha") or "").strip()
    assert sorted(runner_module._derive_files_changed_from_git_evidence(git_evidence)) == ["app.js", "index.html"]

    error = runner_module._validate_execution_outcome_contract(
        outcome=outcome,
        assignee_role="Developer",
        task_status="In Progress",
        git_delivery_enabled=True,
        require_nontrivial_dev_changes=True,
        git_evidence=git_evidence,
    )
    assert error is None


def test_runner_contract_validation_prefers_repo_state_for_post_run_branch_head(tmp_path, monkeypatch):
    import subprocess

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome
    from shared.project_repository import (
        ensure_project_repository_initialized,
        resolve_task_branch_name,
        resolve_task_worktree_path,
    )

    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path))
    project_name = "Battle City"
    project_id = "proj-stale-outcome-sha"
    task_id = "b7b24050-160f-5a60-b4a4-f51a25c6108e"
    title = "Implement core tank controls, movement, shooting, and collision loop"

    repo = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    branch = resolve_task_branch_name(task_id=task_id, title=title)
    worktree = resolve_task_worktree_path(project_name=project_name, project_id=project_id, task_id=task_id)

    subprocess.run(["git", "worktree", "add", "-b", branch, str(worktree), "main"], cwd=str(repo), check=True, capture_output=True, text=True)
    (worktree / "src").mkdir(parents=True, exist_ok=True)
    (worktree / "src" / "tank.js").write_text("export const tank = true;\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/tank.js"], cwd=str(worktree), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "feat: implement tank controls"], cwd=str(worktree), check=True, capture_output=True, text=True)
    actual_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(worktree), check=True, capture_output=True, text=True).stdout.strip().lower()
    stale_head = "1111111111111111111111111111111111111111"

    outcome = AutomationOutcome(
        action="comment",
        summary="Implementation done.",
        comment="Ready for Lead review.",
        execution_outcome_contract={
            "contract_version": 1,
            "files_changed": ["src/tank.js"],
            "commit_sha": actual_head,
            "branch": branch,
            "tests_run": True,
            "tests_passed": True,
            "artifacts": [{"kind": "test", "ref": "node --test", "description": "tests passed"}],
        },
        usage={
            "git_evidence": {
                "task_workdir": str(worktree),
                "repo_root": str(repo),
                "task_branch": branch,
                "before": {"head_sha": "", "on_task_branch": True, "is_dirty": False},
                "after": {"head_sha": stale_head, "on_task_branch": True, "is_dirty": False},
            }
        },
    )

    git_evidence = runner_module._merge_git_evidence(
        runner_module._collect_git_evidence_from_outcome(outcome),
        runner_module._collect_git_evidence_from_repo_state(
            project_name=project_name,
            project_id=project_id,
            task_id=task_id,
            title=title,
        ),
    )

    assert str(git_evidence.get("after_head_sha") or "").strip().lower() == actual_head
    error = runner_module._validate_execution_outcome_contract(
        outcome=outcome,
        assignee_role="Developer",
        task_status="In Progress",
        git_delivery_enabled=True,
        require_nontrivial_dev_changes=True,
        git_evidence=git_evidence,
    )
    assert error is None


def test_runner_contract_validation_prefers_clean_repo_state_over_stale_dirty_outcome(tmp_path, monkeypatch):
    import subprocess

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome
    from shared.project_repository import (
        ensure_project_repository_initialized,
        resolve_task_branch_name,
        resolve_task_worktree_path,
    )

    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path))
    project_name = "Tetris"
    project_id = "proj-clean-fallback"
    task_id = "6a6c8db0-b5cf-5660-9d38-6403c2948a88"
    title = "Build gameplay engine and controls"

    repo = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    branch = resolve_task_branch_name(task_id=task_id, title=title)
    worktree = resolve_task_worktree_path(project_name=project_name, project_id=project_id, task_id=task_id)

    subprocess.run(["git", "worktree", "add", "-b", branch, str(worktree), "main"], cwd=str(repo), check=True, capture_output=True, text=True)
    (worktree / "src").mkdir(parents=True, exist_ok=True)
    (worktree / "src" / "engine.js").write_text("export const engine = true;\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/engine.js"], cwd=str(worktree), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "feat: implement engine"], cwd=str(worktree), check=True, capture_output=True, text=True)
    actual_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(worktree), check=True, capture_output=True, text=True).stdout.strip().lower()

    outcome = AutomationOutcome(
        action="comment",
        summary="Implemented gameplay engine.",
        comment="Ready for Lead review.",
        execution_outcome_contract={
            "contract_version": 1,
            "files_changed": ["src/engine.js"],
            "commit_sha": actual_head,
            "branch": branch,
            "tests_run": True,
            "tests_passed": True,
            "artifacts": [{"kind": "test", "ref": "node --test", "description": "tests passed"}],
        },
        usage={
            "git_evidence": {
                "task_workdir": str(worktree),
                "repo_root": str(repo),
                "task_branch": branch,
                "before": {"head_sha": "", "on_task_branch": True, "is_dirty": False},
                "after": {"head_sha": actual_head, "on_task_branch": True, "is_dirty": True},
            }
        },
    )

    git_evidence = runner_module._merge_git_evidence(
        runner_module._collect_git_evidence_from_outcome(outcome),
        runner_module._collect_git_evidence_from_repo_state(
            project_name=project_name,
            project_id=project_id,
            task_id=task_id,
            title=title,
        ),
    )

    assert git_evidence.get("after_is_dirty") is False
    error = runner_module._validate_execution_outcome_contract(
        outcome=outcome,
        assignee_role="Developer",
        task_status="In Progress",
        git_delivery_enabled=True,
        require_nontrivial_dev_changes=True,
        git_evidence=git_evidence,
    )
    assert error is None


def test_runner_contract_validation_synthesizes_missing_contract_from_clean_branch_handoff(tmp_path, monkeypatch):
    import subprocess

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome
    from shared.project_repository import (
        ensure_project_repository_initialized,
        resolve_task_branch_name,
        resolve_task_worktree_path,
    )

    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path))
    project_name = "Battle City"
    project_id = "proj-missing-contract"
    task_id = "c698120f-13f5-5bf5-a4f3-346ea6146e83"
    title = "Implement enemy AI and wave orchestration"

    repo = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    branch = resolve_task_branch_name(task_id=task_id, title=title)
    worktree = resolve_task_worktree_path(project_name=project_name, project_id=project_id, task_id=task_id)

    subprocess.run(["git", "worktree", "add", "-b", branch, str(worktree), "main"], cwd=str(repo), check=True, capture_output=True, text=True)
    (worktree / "src").mkdir(parents=True, exist_ok=True)
    (worktree / "src" / "enemy-ai.js").write_text("export const enemyAI = true;\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/enemy-ai.js"], cwd=str(worktree), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "feat: implement enemy ai"], cwd=str(worktree), check=True, capture_output=True, text=True)

    outcome = AutomationOutcome(
        action="comment",
        summary="Enemy AI implementation is ready.",
        comment="Ready for Lead handoff.",
        execution_outcome_contract=None,
        usage={},
    )

    git_evidence = runner_module._merge_git_evidence(
        runner_module._collect_git_evidence_from_outcome(outcome),
        runner_module._collect_git_evidence_from_repo_state(
            project_name=project_name,
            project_id=project_id,
            task_id=task_id,
            title=title,
        ),
    )
    committed_handoff = runner_module._inspect_committed_task_branch_handoff(git_evidence)
    assert committed_handoff.get("branch_ahead_of_main") is True
    assert committed_handoff.get("after_is_dirty") is False

    error = runner_module._validate_execution_outcome_contract(
        outcome=outcome,
        assignee_role="Developer",
        task_status="In Progress",
        git_delivery_enabled=True,
        require_nontrivial_dev_changes=True,
        git_evidence=git_evidence,
    )
    assert error is None


def test_runner_contract_validation_derives_files_changed_from_dirty_task_worktree(tmp_path, monkeypatch):
    import subprocess

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome
    from shared.project_repository import (
        ensure_project_repository_initialized,
        resolve_task_branch_name,
        resolve_task_worktree_path,
    )

    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path))
    project_name = "Tetris"
    project_id = "proj-dirty"
    task_id = "8216c9c6-908e-5915-9422-d4ac63afb15b"
    title = "Build gameplay engine and controls"

    repo = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    branch = resolve_task_branch_name(task_id=task_id, title=title)
    worktree = resolve_task_worktree_path(project_name=project_name, project_id=project_id, task_id=task_id)

    subprocess.run(["git", "worktree", "add", "-b", branch, str(worktree), "main"], cwd=str(repo), check=True, capture_output=True, text=True)
    (worktree / "index.html").write_text("<!doctype html><title>Tetris</title>\n", encoding="utf-8")
    (worktree / "styles.css").write_text("body { background: #111; color: #eee; }\n", encoding="utf-8")

    outcome = AutomationOutcome(
        action="comment",
        summary="Implemented initial gameplay shell.",
        comment="Ready for Lead review.",
        execution_outcome_contract={
            "contract_version": 1,
            "files_changed": [],
            "commit_sha": None,
            "branch": None,
            "tests_run": False,
            "tests_passed": False,
            "artifacts": [{"kind": "note", "ref": "dev:implemented"}],
        },
        usage={},
    )

    git_evidence = runner_module._merge_git_evidence(
        runner_module._collect_git_evidence_from_outcome(outcome),
        runner_module._collect_git_evidence_from_repo_state(
            project_name=project_name,
            project_id=project_id,
            task_id=task_id,
            title=title,
        ),
    )

    assert git_evidence.get("task_branch") == branch
    assert sorted(runner_module._derive_files_changed_from_git_evidence(git_evidence)) == ["index.html", "styles.css"]

    error = runner_module._validate_execution_outcome_contract(
        outcome=outcome,
        assignee_role="Developer",
        task_status="In Progress",
        git_delivery_enabled=True,
        require_nontrivial_dev_changes=True,
        git_evidence=git_evidence,
    )
    assert error is not None
    assert "Developer handoff is not committed on the task branch yet." in error
    assert "index.html" in error
    assert "styles.css" in error


def test_runner_derives_files_changed_from_main_three_dot_when_merge_commit_has_no_file_delta(tmp_path, monkeypatch):
    import subprocess

    import features.agents.runner as runner_module
    from shared.project_repository import (
        ensure_project_repository_initialized,
        resolve_task_branch_name,
        resolve_task_worktree_path,
    )

    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path))
    project_name = "Battle City"
    project_id = "proj-main-three-dot-fallback"
    task_id = "9dca220c-2f62-57e9-8b6f-3d5164ec1e31"
    title = "Reconcile latest main into task branch"

    repo = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    branch = resolve_task_branch_name(task_id=task_id, title=title)
    worktree = resolve_task_worktree_path(project_name=project_name, project_id=project_id, task_id=task_id)
    subprocess.run(["git", "worktree", "add", "-b", branch, str(worktree), "main"], cwd=str(repo), check=True, capture_output=True, text=True)

    (repo / "ui.js").write_text("export const mobileControls = true;\n", encoding="utf-8")
    subprocess.run(["git", "add", "ui.js"], cwd=str(repo), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "feat: add ui controls on main"], cwd=str(repo), check=True, capture_output=True, text=True)

    (worktree / "ui.js").write_text("export const mobileControls = true;\n", encoding="utf-8")
    subprocess.run(["git", "add", "ui.js"], cwd=str(worktree), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "feat: add ui controls on task branch"], cwd=str(worktree), check=True, capture_output=True, text=True)

    subprocess.run(["git", "merge", "--no-ff", "main", "-m", "merge main into task branch"], cwd=str(worktree), check=True, capture_output=True, text=True)
    merge_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(worktree), check=True, capture_output=True, text=True).stdout.strip().lower()
    merge_head_files = subprocess.run(
        ["git", "show", "--pretty=format:", "--name-only", merge_head],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert merge_head_files == ""

    git_evidence = {
        "repo_root": str(repo),
        "task_workdir": str(worktree),
        "task_branch": branch,
        "before_head_sha": merge_head,
        "after_head_sha": merge_head,
        "after_is_dirty": False,
    }

    files_changed = runner_module._derive_files_changed_from_git_evidence(git_evidence)
    assert "ui.js" in files_changed


def test_runner_finalizes_dirty_developer_handoff_with_commit(tmp_path, monkeypatch):
    import subprocess

    import features.agents.runner as runner_module
    from shared.project_repository import (
        ensure_project_repository_initialized,
        resolve_task_branch_name,
        resolve_task_worktree_path,
    )

    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path))
    project_name = "Tetris"
    project_id = "proj-finalize"
    task_id = "e2384614-1122-5eb8-a3bb-e8efb14a00c5"
    title = "Build core gameplay and UI"

    repo = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    branch = resolve_task_branch_name(task_id=task_id, title=title)
    worktree = resolve_task_worktree_path(project_name=project_name, project_id=project_id, task_id=task_id)

    subprocess.run(["git", "worktree", "add", "-b", branch, str(worktree), "main"], cwd=str(repo), check=True, capture_output=True, text=True)
    (worktree / "index.html").write_text("<!doctype html><title>Tetris</title>\n", encoding="utf-8")
    (worktree / "styles.css").write_text("body { background: #111; color: #eee; }\n", encoding="utf-8")
    (worktree / "app.js").write_text("console.log('tetris');\n", encoding="utf-8")

    initial_git_evidence = runner_module._collect_git_evidence_from_repo_state(
        project_name=project_name,
        project_id=project_id,
        task_id=task_id,
        title=title,
    )
    assert bool(initial_git_evidence.get("after_is_dirty")) is True

    updated_git_evidence, auto_commit = runner_module._finalize_developer_handoff_commit_if_safe(
        project_name=project_name,
        project_id=project_id,
        task_id=task_id,
        title=title,
        git_evidence=initial_git_evidence,
        require_nontrivial_dev_changes=True,
        tests_run=False,
        tests_passed=False,
    )

    assert auto_commit is not None
    assert str(auto_commit.get("task_branch") or "").strip() == branch
    assert sorted(auto_commit.get("files_changed") or []) == ["app.js", "index.html", "styles.css"]
    assert str(auto_commit.get("commit_sha") or "").strip()
    committed_handoff = runner_module._inspect_committed_task_branch_handoff(updated_git_evidence)
    assert committed_handoff.get("after_is_dirty") is False
    assert committed_handoff.get("branch_ahead_of_main") is True


def test_runner_finalizes_trivial_dirty_residue_when_branch_already_has_nontrivial_handoff(tmp_path, monkeypatch):
    import subprocess

    import features.agents.runner as runner_module
    from shared.project_repository import (
        ensure_project_repository_initialized,
        resolve_task_branch_name,
        resolve_task_worktree_path,
    )

    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path))
    project_name = "Battle City"
    project_id = "proj-finalize-trivial-residue"
    task_id = "29e22ec9-984a-5321-83bf-ddfab30fbe9c"
    title = "Implement game foundation, map system, and player combat loop"

    repo = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    branch = resolve_task_branch_name(task_id=task_id, title=title)
    worktree = resolve_task_worktree_path(project_name=project_name, project_id=project_id, task_id=task_id)

    subprocess.run(["git", "worktree", "add", "-b", branch, str(worktree), "main"], cwd=str(repo), check=True, capture_output=True, text=True)
    (worktree / "src").mkdir(parents=True, exist_ok=True)
    (worktree / "src" / "game.js").write_text("console.log('battle-city');\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/game.js"], cwd=str(worktree), check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: implement battle city foundation"],
        cwd=str(worktree),
        check=True,
        capture_output=True,
        text=True,
    )
    (worktree / "README.md").write_text("# Battle City\n\nUpdated handoff notes.\n", encoding="utf-8")

    initial_git_evidence = runner_module._collect_git_evidence_from_repo_state(
        project_name=project_name,
        project_id=project_id,
        task_id=task_id,
        title=title,
    )
    assert bool(initial_git_evidence.get("after_is_dirty")) is True
    committed_handoff = runner_module._inspect_committed_task_branch_handoff(initial_git_evidence)
    assert committed_handoff.get("branch_ahead_of_main") is True

    updated_git_evidence, auto_commit = runner_module._finalize_developer_handoff_commit_if_safe(
        project_name=project_name,
        project_id=project_id,
        task_id=task_id,
        title=title,
        git_evidence=initial_git_evidence,
        require_nontrivial_dev_changes=True,
        tests_run=True,
        tests_passed=True,
    )

    assert auto_commit is not None
    assert sorted(auto_commit.get("files_changed") or []) == ["README.md"]
    assert str(auto_commit.get("commit_sha") or "").strip()
    refreshed_handoff = runner_module._inspect_committed_task_branch_handoff(updated_git_evidence)
    assert refreshed_handoff.get("after_is_dirty") is False
    assert refreshed_handoff.get("branch_ahead_of_main") is True


def test_runner_contract_validation_rejects_branch_already_reachable_from_main_before_files_changed(tmp_path, monkeypatch):
    import subprocess

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome
    from shared.project_repository import (
        ensure_project_repository_initialized,
        resolve_task_branch_name,
        resolve_task_worktree_path,
    )

    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path))
    project_name = "Battle City"
    project_id = "proj-stale-branch"
    task_id = "c698120f-13f5-5bf5-a4f3-346ea6146e83"
    title = "Implement enemy AI and wave orchestration"

    repo = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    branch = resolve_task_branch_name(task_id=task_id, title=title)
    worktree = resolve_task_worktree_path(project_name=project_name, project_id=project_id, task_id=task_id)

    subprocess.run(["git", "worktree", "add", "-b", branch, str(worktree), "main"], cwd=str(repo), check=True, capture_output=True, text=True)
    (worktree / "src").mkdir(parents=True, exist_ok=True)
    (worktree / "src" / "enemy-ai.js").write_text("export const enemyAI = true;\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/enemy-ai.js"], cwd=str(worktree), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "feat: implement enemy ai"], cwd=str(worktree), check=True, capture_output=True, text=True)
    branch_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(worktree), check=True, capture_output=True, text=True).stdout.strip().lower()

    subprocess.run(["git", "checkout", "main"], cwd=str(repo), check=True, capture_output=True, text=True)
    subprocess.run(["git", "merge", "--ff-only", branch], cwd=str(repo), check=True, capture_output=True, text=True)
    (repo / "README.md").write_text("# Battle City\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "docs: advance main after enemy ai merge"], cwd=str(repo), check=True, capture_output=True, text=True)
    main_head = subprocess.run(["git", "rev-parse", "main"], cwd=str(repo), check=True, capture_output=True, text=True).stdout.strip().lower()
    assert branch_head != main_head

    outcome = AutomationOutcome(
        action="comment",
        summary="Enemy AI implementation is ready.",
        comment="Ready for Lead handoff.",
        execution_outcome_contract={
            "contract_version": 1,
            "files_changed": [],
            "commit_sha": branch_head,
            "branch": branch,
            "tests_run": False,
            "tests_passed": False,
            "artifacts": [{"kind": "note", "ref": "dev:implemented"}],
        },
        usage={},
    )

    git_evidence = runner_module._merge_git_evidence(
        runner_module._collect_git_evidence_from_outcome(outcome),
        runner_module._collect_git_evidence_from_repo_state(
            project_name=project_name,
            project_id=project_id,
            task_id=task_id,
            title=title,
        ),
    )
    committed_handoff = runner_module._inspect_committed_task_branch_handoff(git_evidence)
    assert committed_handoff.get("branch_reachable_from_main") is True
    assert committed_handoff.get("branch_ahead_of_main") is False

    error = runner_module._validate_execution_outcome_contract(
        outcome=outcome,
        assignee_role="Developer",
        task_status="In Progress",
        git_delivery_enabled=True,
        require_nontrivial_dev_changes=True,
        git_evidence=git_evidence,
    )
    assert error is not None
    assert "Developer task branch must be reconciled with the latest `main` before Lead review." in error
    assert "does not contain current `main`" in error
    assert "files_changed in execution outcome contract" not in error


def test_runner_contract_validation_requires_main_reconciliation_when_task_branch_lacks_latest_main(tmp_path, monkeypatch):
    import subprocess

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome
    from shared.project_repository import (
        ensure_project_repository_initialized,
        resolve_task_branch_name,
        resolve_task_worktree_path,
    )

    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path))
    project_name = "Tetris Reconcile"
    project_id = "proj-reconcile-branch"
    task_id = "36aa0fd3-e46e-54a5-b026-0ef274f7a287"
    title = "Prepare Docker Compose runtime and health endpoint on port 6768"

    repo = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    branch = resolve_task_branch_name(task_id=task_id, title=title)
    worktree = resolve_task_worktree_path(project_name=project_name, project_id=project_id, task_id=task_id)

    subprocess.run(["git", "worktree", "add", "-b", branch, str(worktree), "main"], cwd=str(repo), check=True, capture_output=True, text=True)
    (worktree / "deploy").mkdir(parents=True, exist_ok=True)
    (worktree / "deploy" / "docker-compose.yml").write_text("services:\n  app:\n    image: tetris\n", encoding="utf-8")
    subprocess.run(["git", "add", "deploy/docker-compose.yml"], cwd=str(worktree), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "feat: add deploy runtime"], cwd=str(worktree), check=True, capture_output=True, text=True)
    branch_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(worktree), check=True, capture_output=True, text=True).stdout.strip().lower()

    subprocess.run(["git", "checkout", "-b", "main-runtime-update", "main"], cwd=str(repo), check=True, capture_output=True, text=True)
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "game.js").write_text("console.log('main advanced');\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/game.js"], cwd=str(repo), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "feat: advance main independently"], cwd=str(repo), check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "main"], cwd=str(repo), check=True, capture_output=True, text=True)
    subprocess.run(["git", "merge", "--ff-only", "main-runtime-update"], cwd=str(repo), check=True, capture_output=True, text=True)
    main_head = subprocess.run(["git", "rev-parse", "main"], cwd=str(repo), check=True, capture_output=True, text=True).stdout.strip().lower()
    assert branch_head != main_head

    outcome = AutomationOutcome(
        action="comment",
        summary="Docker runtime assets are ready.",
        comment="Ready for Lead handoff.",
        execution_outcome_contract={
            "contract_version": 1,
            "files_changed": ["deploy/docker-compose.yml"],
            "commit_sha": branch_head,
            "branch": branch,
            "tests_run": False,
            "tests_passed": False,
            "artifacts": [{"kind": "note", "ref": "dev:implemented"}],
        },
        usage={},
    )

    git_evidence = runner_module._merge_git_evidence(
        runner_module._collect_git_evidence_from_outcome(outcome),
        runner_module._collect_git_evidence_from_repo_state(
            project_name=project_name,
            project_id=project_id,
            task_id=task_id,
            title=title,
        ),
    )
    committed_handoff = runner_module._inspect_committed_task_branch_handoff(git_evidence)
    assert committed_handoff.get("branch_ahead_of_main") is False
    assert committed_handoff.get("main_reachable_from_branch") is False

    error = runner_module._validate_execution_outcome_contract(
        outcome=outcome,
        assignee_role="Developer",
        task_status="In Progress",
        git_delivery_enabled=True,
        require_nontrivial_dev_changes=False,
        git_evidence=git_evidence,
    )
    assert error is not None
    assert "must be reconciled with the latest `main` before Lead review" in error
    assert "does not contain current `main`" in error


def test_developer_handoff_reports_uncommitted_files(tmp_path, monkeypatch):
    import subprocess

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome
    from shared.project_repository import ensure_project_repository_initialized
    from shared.project_repository import resolve_task_worktree_path

    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path / "workspace"))
    project_name = "Dirty Handoff Demo"
    task_id = "task-dirty-files"
    title = "Implement gameplay"
    branch = "task/task-dir-implement-gameplay"
    repo_root = ensure_project_repository_initialized(project_name=project_name)
    worktree = resolve_task_worktree_path(project_name=project_name, task_id=task_id)
    subprocess.run(["git", "worktree", "add", "-b", branch, str(worktree), "main"], cwd=repo_root, check=True)
    (worktree / "index.html").write_text("<html></html>\n", encoding="utf-8")
    (worktree / "styles.css").write_text("body{}\n", encoding="utf-8")

    outcome = AutomationOutcome(
        action="comment",
        summary="Implemented the gameplay shell.",
        comment=None,
        execution_outcome_contract={
            "contract_version": 1,
            "files_changed": [],
            "tests_run": False,
            "tests_passed": False,
            "commit_sha": None,
            "branch": branch,
            "artifacts": [],
        },
    )
    git_evidence = runner_module._collect_git_evidence_from_repo_state(
        project_name=project_name,
        project_id=None,
        task_id=task_id,
        title=title,
    )

    error = runner_module._validate_execution_outcome_contract(
        outcome=outcome,
        assignee_role="Developer",
        task_status="In Progress",
        git_delivery_enabled=True,
        require_nontrivial_dev_changes=True,
        git_evidence=git_evidence,
    )
    assert "Developer handoff is not committed on the task branch yet." in str(error)
    assert "index.html" in str(error)
    assert "styles.css" in str(error)


def test_developer_handoff_error_prioritizes_nontrivial_files_over_readme(tmp_path, monkeypatch):
    import subprocess

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome
    from shared.project_repository import ensure_project_repository_initialized, resolve_task_worktree_path

    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path / "workspace"))
    project_name = "Tetris Dirty Preview"
    task_id = "133ac52f-655b-5613-9f2f-c4cf603e14b0"
    title = "Implement core gameplay mechanics"
    branch = "task/133ac52f-implement-core-gameplay-mechanics"
    repo_root = ensure_project_repository_initialized(project_name=project_name)
    worktree = resolve_task_worktree_path(project_name=project_name, task_id=task_id)
    subprocess.run(["git", "worktree", "add", "-b", branch, str(worktree), "main"], cwd=repo_root, check=True)
    (worktree / "README.md").write_text("# Tetris\n", encoding="utf-8")
    (worktree / "index.html").write_text("<html></html>\n", encoding="utf-8")
    (worktree / "style.css").write_text("body{}\n", encoding="utf-8")
    (worktree / "src").mkdir(parents=True, exist_ok=True)
    (worktree / "src" / "game.js").write_text("console.log('tetris');\n", encoding="utf-8")

    outcome = AutomationOutcome(
        action="comment",
        summary="Implemented the gameplay shell.",
        comment=None,
        execution_outcome_contract={
            "contract_version": 1,
            "files_changed": [],
            "tests_run": False,
            "tests_passed": False,
            "commit_sha": None,
            "branch": branch,
            "artifacts": [],
        },
    )
    git_evidence = runner_module._collect_git_evidence_from_repo_state(
        project_name=project_name,
        project_id=None,
        task_id=task_id,
        title=title,
    )

    error = runner_module._validate_execution_outcome_contract(
        outcome=outcome,
        assignee_role="Developer",
        task_status="In Progress",
        git_delivery_enabled=True,
        require_nontrivial_dev_changes=True,
        git_evidence=git_evidence,
    )
    assert "Uncommitted files:" in str(error)
    assert "README.md" in str(error)
    assert "index.html" in str(error)
    assert str(error).index("index.html") < str(error).index("README.md")


def test_project_has_merge_to_main_evidence_uses_repo_branch_merge_fallback(tmp_path, monkeypatch):
    import subprocess

    import features.agents.runner as runner_module
    from shared.project_repository import ensure_project_repository_initialized
    from shared.models import Project, SessionLocal

    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path / "workspace"))
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    patched_project = client.patch(
        f'/api/projects/{project_id}',
        json={'name': 'Merge Evidence Repo Fallback Demo'},
    )
    assert patched_project.status_code == 200
    project_name = str(patched_project.json().get('name') or '')

    repo_root = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    branch_name = 'task/abc12345-dev-implementation'

    subprocess.run(['git', 'checkout', '-b', branch_name], cwd=str(repo_root), check=True, capture_output=True, text=True)
    (repo_root / 'index.html').write_text('<!doctype html><title>demo</title>\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'index.html'], cwd=str(repo_root), check=True, capture_output=True, text=True)
    subprocess.run(['git', 'commit', '-m', 'Implement feature branch work'], cwd=str(repo_root), check=True, capture_output=True, text=True)
    subprocess.run(['git', 'checkout', 'main'], cwd=str(repo_root), check=True, capture_output=True, text=True)
    subprocess.run(['git', 'merge', '--no-ff', branch_name, '-m', 'Merge feature branch'], cwd=str(repo_root), check=True, capture_output=True, text=True)

    task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Developer delivery branch',
            'status': 'Awaiting decision',
            'external_refs': [
                {'url': f'branch:{branch_name}', 'title': 'Task branch'},
            ],
        },
    )
    assert task.status_code == 200

    with SessionLocal() as db:
        assert runner_module._project_has_merge_to_main_evidence(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
        ) is True


def test_runner_lead_cycle_synthesizes_missing_compose_and_deploys(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path))
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Lead synth compose project',
            'custom_statuses': ['To do', 'In Progress', 'In Review', 'Awaiting decision', 'Blocked', 'Completed'],
        },
    )
    assert project.status_code == 200
    project_id = project.json()['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    apply_docker = client.post(
        f'/api/projects/{project_id}/plugins/docker_compose/apply',
        json={
            'config': {
                'runtime_deploy_health': {
                    'required': True,
                    'stack': 'constructos-ws-default',
                    'port': 6768,
                    'health_path': '/health',
                    'require_http_200': True,
                },
            },
            'enabled': True,
        },
    )
    assert apply_docker.status_code == 200

    from shared.project_repository import ensure_project_repository_initialized, resolve_project_repository_path

    repo_root = ensure_project_repository_initialized(project_name='Lead synth compose project', project_id=project_id)
    dockerfile = repo_root / 'Dockerfile'
    dockerfile.write_text(
        "FROM node:20-alpine\n"
        "WORKDIR /app\n"
        "COPY . .\n"
        "ENV PORT=6768\n"
        "EXPOSE 6768\n"
        "CMD [\"node\", \"server.js\"]\n",
        encoding='utf-8',
    )

    dev_task = client.post(
        '/api/tasks',
        json={
            'title': 'Developer delivery already merged',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Completed',
            'assignee_id': team['dev1'],
            'assigned_agent_code': 'dev-a',
            'instruction': 'Developer implementation delivered.',
            'external_refs': [
                {'url': 'commit:1111111111111111111111111111111111111111', 'title': 'commit evidence'},
                {'url': 'task/dev-ready-branch', 'title': 'task branch evidence'},
                {'url': 'merge:main:1111111111111111111111111111111111111111', 'title': 'merged to main'},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    qa_task = client.post(
        '/api/tasks',
        json={
            'title': 'QA handoff target',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': team['qa'],
            'assigned_agent_code': 'qa-a',
            'instruction': 'Run QA validation after deploy.',
            'task_relationships': [
                {
                    'kind': 'hands_off_to',
                    'task_ids': [],
                    'statuses': ['In Progress'],
                }
            ],
        },
    )
    assert qa_task.status_code == 200
    qa_task_id = qa_task.json()['id']

    lead_task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead deploy cycle',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Perform deploy and handoff to QA.',
            'external_refs': [
                {'url': 'commit:2222222222222222222222222222222222222222', 'title': 'commit evidence'},
                {'url': 'task/lead-deploy-branch', 'title': 'task branch evidence'},
                {'url': 'merge:main:2222222222222222222222222222222222222222', 'title': 'merged to main'},
            ],
            'task_type': 'scheduled_instruction',
            'scheduled_instruction': 'Perform deploy and handoff to QA.',
            'scheduled_at_utc': (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
            'schedule_timezone': 'UTC',
            'recurring_rule': 'every:5m',
            'execution_triggers': [
                {
                    'kind': 'schedule',
                    'enabled': True,
                    'scheduled_at_utc': (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
                    'recurring_rule': 'every:5m',
                    'schedule_timezone': 'UTC',
                    'run_on_statuses': ['Awaiting decision'],
                    'action': 'request_automation',
                },
            ],
            'task_relationships': [
                {'kind': 'depends_on', 'task_ids': [dev_task_id], 'statuses': ['Completed']},
                {'kind': 'depends_on', 'task_ids': [dev_task_id, qa_task_id], 'statuses': ['Blocked']},
            ],
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    patched_dev = client.patch(
        f"/api/tasks/{dev_task_id}",
        json={
            'task_relationships': [
                {
                    'kind': 'delivers_to',
                    'task_ids': [lead_task_id],
                    'statuses': ['Awaiting decision'],
                }
            ]
        },
    )
    assert patched_dev.status_code == 200

    patched_qa = client.patch(
        f"/api/tasks/{qa_task_id}",
        json={
            'task_relationships': [
                {
                    'kind': 'hands_off_to',
                    'task_ids': [lead_task_id],
                    'statuses': ['In Progress'],
                }
            ]
        },
    )
    assert patched_qa.status_code == 200

    queued = client.post(
        f"/api/tasks/{lead_task_id}/automation/run",
        json={
            'instruction': 'Run lead deploy cycle now',
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
            'workflow_scope': 'team_mode',
            'execution_mode': 'resume_execution',
            'task_completion_requested': False,
            'classifier_reason': 'test override',
        },
    )
    assert queued.status_code == 200

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome

    manifest_path = resolve_project_repository_path(project_name='Lead synth compose project', project_id=project_id) / 'docker-compose.yml'
    manifest_path.write_text(
        "services:\n"
        "  app:\n"
        "    build: .\n",
        encoding='utf-8',
    )
    monkeypatch.setattr(
        runner_module,
        "execute_task_automation",
        lambda **_: AutomationOutcome(action="comment", summary="Lead cycle completed", comment=None),
    )
    monkeypatch.setattr(
        runner_module,
        "_synthesize_runtime_deploy_assets",
        lambda **_: {
            "ok": True,
            "manifest_path": str(manifest_path),
            "runtime_type": "dockerfile_build",
            "created_files": [],
            "commit_sha": None,
        },
    )
    monkeypatch.setattr(
        runner_module,
        "_run_docker_compose_up_with_error",
        lambda **_: (0, "up", ""),
    )
    monkeypatch.setattr(
        runner_module,
        "run_runtime_deploy_health_check",
        lambda **_: {
            "stack": "constructos-ws-default",
            "port": 6768,
            "health_path": "/health",
            "http_url": "http://gateway:6768/health",
            "http_status": 200,
            "ok": True,
            "error": None,
        },
    )
    monkeypatch.setattr(
        runner_module,
        "_probe_runtime_health_with_retry",
        lambda **_: {
            "stack": "constructos-ws-default",
            "port": 6768,
            "health_path": "/health",
            "http_url": "http://gateway:6768/health",
            "http_status": 200,
            "serves_application_root": True,
            "ok": True,
            "error": None,
        },
    )
    monkeypatch.setattr(runner_module, "_project_has_repo_context", lambda **_: True)

    processed = runner_module.run_queued_automation_once(limit=1)
    assert processed >= 1

    assert manifest_path.exists()
    assert 'build:' in manifest_path.read_text(encoding='utf-8')

    lead_status = client.get(f"/api/tasks/{lead_task_id}/automation").json()
    assert lead_status.get('automation_state') != 'failed', str(lead_status.get('last_agent_error') or lead_status)
    assert lead_status.get('team_mode_phase') == 'qa_validation'

    qa_task_payload = client.get(f"/api/tasks/{qa_task_id}").json()
    assert qa_task_payload["status"] == "In Progress"
    assert qa_task_payload["assigned_agent_code"] == "qa-a"

    qa_status = client.get(f"/api/tasks/{qa_task_id}/automation").json()
    assert qa_status.get('automation_state') in {'queued', 'running', 'completed'}
    assert qa_status.get('last_requested_source') == 'lead_handoff'
    assert qa_status.get('team_mode_phase') == 'qa_validation'


def test_synthesize_runtime_deploy_assets_does_not_mutate_existing_manifest_on_main(tmp_path, monkeypatch):
    import features.agents.runner as runner_module

    repo_root = tmp_path / "static-runtime-repair"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "index.html").write_text("<!doctype html><html><body>Tetris</body></html>\n", encoding="utf-8")
    (repo_root / "health").write_text("ok\n", encoding="utf-8")
    nginx_conf_dir = repo_root / "nginx-conf"
    nginx_conf_dir.mkdir(parents=True, exist_ok=True)
    (nginx_conf_dir / "default.conf").write_text("server { listen 80; }\n", encoding="utf-8")
    manifest_path = repo_root / "docker-compose.yml"
    manifest_path.write_text(
        "services:\n"
        "  app:\n"
        "    image: nginx:1.27-alpine\n"
        "    ports:\n"
        "      - \"6768:80\"\n"
        "    volumes:\n"
        "      - ./:/usr/share/nginx/html:ro\n"
        "      - ./nginx/conf.d:/etc/nginx/conf.d:ro\n"
        "    restart: unless-stopped\n",
        encoding="utf-8",
    )
    (repo_root / "health").write_text("ok\n", encoding="utf-8")
    (repo_root / "nginx-conf").mkdir(parents=True, exist_ok=True)
    (repo_root / "nginx-conf" / "default.conf").write_text("server { listen 80; }\n", encoding="utf-8")

    monkeypatch.setattr(
        runner_module,
        "resolve_project_repository_path",
        lambda **_kwargs: repo_root,
    )
    monkeypatch.setattr(
        runner_module,
        "find_project_compose_manifest",
        lambda **_kwargs: manifest_path,
    )
    result = runner_module._synthesize_runtime_deploy_assets(
        project_name="Static runtime repair",
        project_id="static-runtime-repair",
        port=6768,
        health_path="/health",
    )

    assert result["ok"] is True
    assert result["runtime_type"] == "static_web"
    assert result["commit_sha"] is None
    assert result["created_files"] == []
    assert "./nginx/conf.d:/etc/nginx/conf.d:ro" in manifest_path.read_text(encoding="utf-8")
    assert (repo_root / "health").exists()
    assert (repo_root / "nginx-conf").exists()


def test_synthesize_runtime_deploy_assets_requires_followup_task_for_static_runtime_scaffolding(tmp_path, monkeypatch):
    import features.agents.runner as runner_module

    repo_root = tmp_path / "static-from-package-json"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        json.dumps({"name": "tetris-web", "private": True, "scripts": {"build": "vite build"}}),
        encoding="utf-8",
    )
    (repo_root / "index.html").write_text("<!doctype html><html><body>Tetris</body></html>\n", encoding="utf-8")

    monkeypatch.setattr(
        runner_module,
        "resolve_project_repository_path",
        lambda **_kwargs: repo_root,
    )
    monkeypatch.setattr(
        runner_module,
        "find_project_compose_manifest",
        lambda **_kwargs: None,
    )
    result = runner_module._synthesize_runtime_deploy_assets(
        project_name="Static fallback",
        project_id="static-fallback",
        port=6768,
        health_path="/health",
    )

    assert result == {
        "ok": False,
        "error": (
            "deploy scaffolding is missing for a recognizable static_web runtime; "
            "create the missing deployment files on a task branch instead of modifying main directly"
        ),
    }
    assert not (repo_root / "docker-compose.yml").exists()
    assert not (repo_root / "nginx.constructos.conf").exists()


def test_run_docker_compose_up_uses_build_for_build_manifest(tmp_path, monkeypatch):
    import subprocess
    import features.agents.runner as runner_module

    repo_root = tmp_path / "compose-build"
    repo_root.mkdir(parents=True, exist_ok=True)
    manifest_path = repo_root / "docker-compose.yml"
    manifest_path.write_text(
        "services:\n"
        "  web:\n"
        "    build: .\n",
        encoding="utf-8",
    )

    recorded: dict[str, object] = {}

    class _Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(args, **kwargs):
        recorded["args"] = list(args)
        recorded["cwd"] = kwargs.get("cwd")
        return _Result()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    code, out, err = runner_module._run_docker_compose_up_with_error(
        cwd=repo_root,
        stack="constructos-ws-default",
        manifest_path=manifest_path,
    )

    assert code == 0
    assert out == "ok"
    assert err == ""
    assert recorded["cwd"] == str(repo_root)
    assert recorded["args"][-3:] == ["up", "-d", "--build"]


def test_synthesize_runtime_deploy_assets_requires_real_static_runtime_marker_instead_of_fabricated_index(tmp_path, monkeypatch):
    import features.agents.runner as runner_module

    repo_root = tmp_path / "static-entrypoint-fallback"
    repo_root.mkdir(parents=True, exist_ok=True)
    src_dir = repo_root / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "main.js").write_text("document.getElementById('app').textContent = 'Tetris';\n", encoding="utf-8")

    monkeypatch.setattr(
        runner_module,
        "resolve_project_repository_path",
        lambda **_kwargs: repo_root,
    )
    monkeypatch.setattr(
        runner_module,
        "find_project_compose_manifest",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        runner_module,
        "_commit_repo_changes_if_any",
        lambda **_kwargs: "entrypoint-fallback-sha",
    )

    result = runner_module._synthesize_runtime_deploy_assets(
        project_name="Static entrypoint fallback",
        project_id="static-entrypoint-fallback",
        port=6768,
        health_path="/health",
    )

    assert result == {
        "ok": False,
        "error": "unsupported runtime: repository does not contain Dockerfile, package.json, pyproject.toml, requirements.txt, or index.html",
    }
    assert not (repo_root / "index.html").exists()


def test_synthesize_runtime_deploy_assets_keeps_node_runtime_error_without_start_or_static_signals(tmp_path, monkeypatch):
    import features.agents.runner as runner_module

    repo_root = tmp_path / "node-without-start"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        json.dumps({"name": "tetris-web", "private": True, "scripts": {"build": "vite build"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        runner_module,
        "resolve_project_repository_path",
        lambda **_kwargs: repo_root,
    )
    monkeypatch.setattr(
        runner_module,
        "find_project_compose_manifest",
        lambda **_kwargs: None,
    )

    result = runner_module._synthesize_runtime_deploy_assets(
        project_name="Node fallback error",
        project_id="node-fallback-error",
        port=6768,
        health_path="/health",
    )

    assert result == {
        "ok": False,
        "error": "unsupported Node runtime: package.json is missing a non-empty scripts.start entry",
    }


def test_infer_team_mode_dispatch_source_task_id_accepts_completed_developer_with_merge_evidence(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    plugin_rule = client.post(
        '/api/project-rules',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Plugin Policy',
            'body': json.dumps({'mode': 'execution'}),
        },
    )
    assert plugin_rule.status_code == 200

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead integration",
            "status": "Awaiting decision",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer implementation",
            "status": "Completed",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "external_refs": [
                {"url": "merge:main:abc1234", "title": "merged to main"},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    import features.agents.runner as runner_module
    from shared.models import Project, SessionLocal

    with SessionLocal() as db:
        inferred = runner_module._infer_team_mode_dispatch_source_task_id(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            task_id=lead_task_id,
            assignee_role="Lead",
        )
    assert inferred == dev_task_id


def test_project_task_dependency_event_detail_returns_request_and_response(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    lead_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Lead task',
            'status': 'Awaiting decision',
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    dev_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Developer task',
            'status': 'In Progress',
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    from shared.eventing import append_event
    from shared.models import Project, SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=dev_task_id,
            event_type='TaskAutomationRequested',
            payload={
                'requested_at': '2026-03-11T10:00:00Z',
                'instruction': 'Implement the gameplay loop and commit it.',
                'source': 'lead_kickoff_dispatch',
                'source_task_id': lead_task_id,
                'reason': 'kickoff',
                'trigger_link': f'{lead_task_id}->{dev_task_id}:In Progress',
                'correlation_id': 'corr-edge-1',
            },
            metadata={
                'actor_id': AGENT_SYSTEM_USER_ID,
                'workspace_id': ws_id,
                'project_id': project_id,
                'task_id': dev_task_id,
            },
        )
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=dev_task_id,
            event_type='TaskCommentAdded',
            payload={
                'task_id': dev_task_id,
                'user_id': AGENT_SYSTEM_USER_ID,
                'body': 'Implemented gameplay and committed branch output.',
                'created_at': '2026-03-11T10:02:00Z',
            },
            metadata={
                'actor_id': AGENT_SYSTEM_USER_ID,
                'workspace_id': ws_id,
                'project_id': project_id,
                'task_id': dev_task_id,
            },
        )
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=dev_task_id,
            event_type='TaskAutomationCompleted',
            payload={
                'completed_at': '2026-03-11T10:03:00Z',
                'summary': 'Developer automation completed successfully.',
            },
            metadata={
                'actor_id': AGENT_SYSTEM_USER_ID,
                'workspace_id': ws_id,
                'project_id': project_id,
                'task_id': dev_task_id,
            },
        )
        db.commit()

    res = client.get(
        f'/api/projects/{project_id}/task-dependency-graph/event-detail',
        params={
            'source_task_id': lead_task_id,
            'target_task_id': dev_task_id,
            'source': 'lead_kickoff_dispatch',
            'at': '2026-03-11T10:00:00Z',
            'correlation_id': 'corr-edge-1',
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload['request_markdown'] == 'Implement the gameplay loop and commit it.'
    assert payload['response_markdown'] == 'Implemented gameplay and committed branch output.'
    assert payload['response_status'] == 'completed'


def test_project_task_dependency_event_detail_prefers_failure_error_markdown(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    lead_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Lead task',
            'status': 'Awaiting decision',
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    dev_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Developer task',
            'status': 'In Progress',
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    from shared.eventing import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=dev_task_id,
            event_type='TaskAutomationRequested',
            payload={
                'requested_at': '2026-03-11T10:00:00Z',
                'instruction': 'Implement the gameplay loop and commit it.',
                'source': 'lead_kickoff_dispatch',
                'source_task_id': lead_task_id,
                'reason': 'kickoff',
                'correlation_id': 'corr-edge-fail',
            },
            metadata={
                'actor_id': AGENT_SYSTEM_USER_ID,
                'workspace_id': ws_id,
                'project_id': project_id,
                'task_id': dev_task_id,
            },
        )
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=dev_task_id,
            event_type='TaskAutomationFailed',
            payload={
                'failed_at': '2026-03-11T10:03:00Z',
                'summary': 'Automation runner failed.',
                'error': 'Runner error: Developer handoff is not committed on the task branch yet.',
            },
            metadata={
                'actor_id': AGENT_SYSTEM_USER_ID,
                'workspace_id': ws_id,
                'project_id': project_id,
                'task_id': dev_task_id,
            },
        )
        db.commit()

    res = client.get(
        f'/api/projects/{project_id}/task-dependency-graph/event-detail',
        params={
            'source_task_id': lead_task_id,
            'target_task_id': dev_task_id,
            'source': 'lead_kickoff_dispatch',
            'at': '2026-03-11T10:00:00Z',
            'correlation_id': 'corr-edge-fail',
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload['response_status'] == 'failed'
    assert 'Developer handoff is not committed on the task branch yet.' in str(payload['response_markdown'])
    assert 'Automation runner failed.' in str(payload['response_markdown'])


def test_project_task_dependency_event_detail_includes_origin_chat_prompt_and_classifier(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    lead_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Lead task',
            'status': 'Awaiting decision',
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    dev_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Developer task',
            'status': 'In Progress',
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    from features.chat.application import ChatApplicationService
    from features.chat.command_handlers import AppendUserMessagePayload
    from shared.eventing import append_event
    from shared.models import SessionLocal, User
    from shared.settings import AGENT_SYSTEM_USER_ID

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.username == 'admin')).scalar_one()
        ChatApplicationService(db, user).append_user_message(
            AppendUserMessagePayload(
                workspace_id=ws_id,
                project_id=project_id,
                session_id='chat-debug-session',
                message_id=None,
                content='Create project Tetris and run kickoff after creating three Team Mode tasks.',
                usage={
                    'intent_flags': {
                        'execution_intent': True,
                        'execution_kickoff_intent': True,
                        'project_creation_intent': True,
                        'workflow_scope': 'team_mode',
                        'execution_mode': 'setup_then_kickoff',
                        'task_completion_requested': False,
                        'reason': 'Structured chat classification',
                    }
                },
            )
        )
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=dev_task_id,
            event_type='TaskAutomationRequested',
            payload={
                'requested_at': '2026-03-11T11:00:00Z',
                'instruction': 'Implement the gameplay loop and commit it.',
                'source': 'lead_kickoff_dispatch',
                'source_task_id': lead_task_id,
                'chat_session_id': 'chat-debug-session',
                'execution_intent': True,
                'execution_kickoff_intent': True,
                'workflow_scope': 'team_mode',
                'execution_mode': 'kickoff_only',
                'classifier_reason': 'Propagated from chat request',
                'reason': 'kickoff',
                'trigger_link': f'{lead_task_id}->{dev_task_id}:Dev',
                'correlation_id': 'corr-edge-chat',
            },
            metadata={
                'actor_id': AGENT_SYSTEM_USER_ID,
                'workspace_id': ws_id,
                'project_id': project_id,
                'task_id': dev_task_id,
            },
        )
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=dev_task_id,
            event_type='TaskAutomationCompleted',
            payload={
                'completed_at': '2026-03-11T11:03:00Z',
                'summary': 'Developer automation completed successfully.',
            },
            metadata={
                'actor_id': AGENT_SYSTEM_USER_ID,
                'workspace_id': ws_id,
                'project_id': project_id,
                'task_id': dev_task_id,
            },
        )
        db.commit()

    res = client.get(
        f'/api/projects/{project_id}/task-dependency-graph/event-detail',
        params={
            'source_task_id': lead_task_id,
            'target_task_id': dev_task_id,
            'source': 'lead_kickoff_dispatch',
            'at': '2026-03-11T11:00:00Z',
            'correlation_id': 'corr-edge-chat',
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload['origin_chat_session_id'] == 'chat-debug-session'
    assert 'Create project Tetris' in str(payload['origin_prompt_markdown'])
    assert payload['origin_classifier']['workflow_scope'] == 'team_mode'
    assert payload['runtime_classifier']['execution_mode'] == 'kickoff_only'


def test_runner_blocks_qa_task_until_lead_handoff_is_complete(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_resp = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'QA waits for handoff project',
            'custom_statuses': ['To do', 'In Progress', 'In Review', 'Awaiting decision', 'Blocked', 'Completed'],
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead oversight active',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Keep lead oversight active.',
        },
    )
    assert lead_task.status_code == 200

    qa_task = client.post(
        '/api/tasks',
        json={
            'title': 'QA should wait',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': team['qa'],
            'assigned_agent_code': 'qa-a',
            'instruction': 'Run QA checks.',
        },
    )
    assert qa_task.status_code == 200
    qa_task_id = qa_task.json()['id']

    queued = client.post(
        f"/api/tasks/{qa_task_id}/automation/run",
        json={
            'instruction': 'Run QA now',
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
            'workflow_scope': 'team_mode',
            'execution_mode': 'resume_execution',
            'task_completion_requested': False,
            'classifier_reason': 'test override',
        },
    )
    assert queued.status_code == 200
    queued_payload = queued.json()
    assert queued_payload["ok"] is True
    assert queued_payload["skipped"] is True
    assert "Lead handoff" in str(queued_payload.get("reason") or "")

    status_payload = client.get(f"/api/tasks/{qa_task_id}/automation").json()
    assert status_payload['automation_state'] == 'idle'
    assert status_payload.get('team_mode_phase') in {None, '', 'qa_validation'}
    handoff_gate = next(item for item in (status_payload.get('execution_gates') or []) if item.get('id') == 'qa_handoff_ready')
    assert handoff_gate['status'] == 'waiting'
    assert 'lead handoff' in str(handoff_gate.get('message') or '').lower()
    task_payload = client.get(f"/api/tasks/{qa_task_id}").json()
    assert task_payload['status'] == 'In Progress'


def test_runner_blocks_qa_task_when_handoff_is_stale_for_current_deploy_cycle(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_resp = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'QA waits for current deploy cycle project',
            'custom_statuses': ['To do', 'In Progress', 'In Review', 'Awaiting decision', 'Blocked', 'Completed'],
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead deploy cycle active',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Keep lead deploy cycle active.',
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    qa_task = client.post(
        '/api/tasks',
        json={
            'title': 'QA should wait for current deploy cycle',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': team['qa'],
            'assigned_agent_code': 'qa-a',
            'instruction': 'Run QA checks.',
        },
    )
    assert qa_task.status_code == 200
    qa_task_id = qa_task.json()['id']

    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    stale_handoff_at = "2026-03-09T10:00:00Z"
    current_deploy_at = "2026-03-09T10:05:00Z"
    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=lead_task_id,
            event_type='TaskUpdated',
            payload={
                'last_deploy_execution': {
                    'executed_at': current_deploy_at,
                    'stack': 'constructos-ws-default',
                    'port': 6768,
                    'health_path': '/health',
                    'command': 'docker compose -p constructos-ws-default up -d',
                    'manifest_path': 'docker-compose.yml',
                    'runtime_type': 'dockerfile_build',
                    'runtime_ok': True,
                    'http_url': 'http://gateway:6768/health',
                    'http_status': 200,
                }
            },
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': lead_task_id},
        )
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=qa_task_id,
            event_type='TaskAutomationRequested',
            payload={
                'requested_at': stale_handoff_at,
                'instruction': 'Run QA checks.',
                'source': 'lead_handoff',
                'source_task_id': lead_task_id,
                'reason': 'lead_handoff',
                'trigger_link': f'{lead_task_id}->{qa_task_id}:QA',
                'correlation_id': f'lead:{lead_task_id}:{stale_handoff_at}',
                'trigger_task_id': lead_task_id,
                'from_status': 'Awaiting decision',
                'to_status': 'In Progress',
                'triggered_at': stale_handoff_at,
                'lead_handoff_token': f'lead:{lead_task_id}:{stale_handoff_at}',
                'lead_handoff_at': stale_handoff_at,
                'lead_handoff_refs': [],
                'lead_handoff_deploy_execution': {
                    'executed_at': stale_handoff_at,
                    'stack': 'constructos-ws-default',
                    'port': 6768,
                    'health_path': '/health',
                },
            },
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': qa_task_id},
        )
        db.commit()

    queued = client.post(
        f"/api/tasks/{qa_task_id}/automation/run",
        json={
            'instruction': 'Run QA now',
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
            'workflow_scope': 'team_mode',
            'execution_mode': 'resume_execution',
            'task_completion_requested': False,
            'classifier_reason': 'test override',
        },
    )
    assert queued.status_code == 200

    import features.agents.runner as runner_module

    def _should_not_execute(**_kwargs):
        raise AssertionError("execute_task_automation should not run before current-cycle Lead handoff")

    monkeypatch.setattr(runner_module, "execute_task_automation", _should_not_execute)

    processed = runner_module.run_queued_automation_once(limit=5)
    assert processed >= 1

    status_payload = client.get(f"/api/tasks/{qa_task_id}/automation").json()
    assert status_payload['automation_state'] == 'completed'
    assert status_payload['team_mode_blocking_gate'] == 'qa_waiting_current_deploy_cycle'
    assert status_payload['team_mode_phase'] == 'qa_validation'
    gates = status_payload.get('execution_gates') or []
    handoff_gate = next(item for item in gates if item.get('id') == 'qa_handoff_ready')
    assert handoff_gate['status'] == 'waiting'
    assert 'current deploy cycle' in str(handoff_gate.get('message') or '').lower()


def test_task_automation_status_derives_qa_handoff_from_structured_request_and_lead_refs(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_resp = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Structured QA handoff project',
            'custom_statuses': ['To do', 'In Progress', 'In Review', 'Awaiting decision', 'Blocked', 'Completed'],
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead deploy cycle',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Completed',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'external_refs': [
                {'url': 'file:/home/app/workspace/.constructos/repos/tetris/docker-compose.yml', 'title': 'Compose manifest path'},
                {'url': 'decision:runtime_signal_static_assets_index_html', 'title': 'Runtime decision'},
                {'url': 'command:docker compose -p constructos-ws-default up -d --build:success', 'title': 'Deploy command'},
                {'url': 'http://gateway:6768/health#post-deploy-http-200-2026-03-10T15:09:54Z', 'title': 'Deploy health: pass'},
            ],
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    qa_task = client.post(
        '/api/tasks',
        json={
            'title': 'QA validation',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': team['qa'],
            'assigned_agent_code': 'qa-a',
            'instruction': 'Run QA checks.',
        },
    )
    assert qa_task.status_code == 200
    qa_task_id = qa_task.json()['id']

    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=qa_task_id,
            event_type='TaskAutomationRequested',
            payload={
                'requested_at': '2026-03-10T15:10:00Z',
                'instruction': 'Run QA checks.',
                'source': 'lead_handoff',
                'source_task_id': lead_task_id,
                'reason': 'lead_handoff',
                'workflow_scope': 'team_mode',
                'execution_intent': True,
                'correlation_id': 'lead:derived-handoff',
                'trigger_task_id': lead_task_id,
                'from_status': 'In Progress',
                'to_status': 'In Progress',
                'triggered_at': '2026-03-10T15:10:00Z',
            },
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': qa_task_id},
        )
        db.commit()

    lead_status = client.get(f"/api/tasks/{lead_task_id}/automation").json()
    assert lead_status['last_deploy_execution']['runtime_ok'] is True
    assert lead_status['last_deploy_execution']['http_status'] == 200

    qa_status = client.get(f"/api/tasks/{qa_task_id}/automation").json()
    assert qa_status['last_lead_handoff_token'] == 'lead:derived-handoff'
    assert qa_status['last_lead_handoff_deploy_execution']['runtime_ok'] is True
    handoff_gate = next(item for item in (qa_status.get('execution_gates') or []) if item.get('id') == 'qa_handoff_ready')
    assert handoff_gate['status'] == 'pass'


def test_runner_blocks_lead_task_until_merge_ready_developer_output_exists(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    apply_docker = client.post(
        f'/api/projects/{project_id}/plugins/docker_compose/apply',
        json={
            'config': {
                'runtime_deploy_health': {
                    'required': True,
                    'stack': 'constructos-ws-default',
                    'port': 6768,
                    'health_path': '/health',
                    'require_http_200': True,
                },
            },
            'enabled': True,
        },
    )
    assert apply_docker.status_code == 200

    dev_task = client.post(
        '/api/tasks',
        json={
            'title': 'Developer still implementing',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': team['dev1'],
            'instruction': 'Keep implementing.',
        },
    )
    assert dev_task.status_code == 200

    lead_task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead should wait for merge-ready output',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'assignee_id': team['lead'],
            'instruction': 'Coordinate release readiness.',
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    queued = client.post(
        f"/api/tasks/{lead_task_id}/automation/run",
        json={
            'instruction': 'Coordinate release readiness now',
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
            'workflow_scope': 'team_mode',
            'execution_mode': 'resume_execution',
            'task_completion_requested': False,
            'classifier_reason': 'test override',
        },
    )
    assert queued.status_code == 200

    import features.agents.runner as runner_module

    def _should_not_execute(**_kwargs):
        raise AssertionError("execute_task_automation should not run before merge-ready Developer output exists")

    monkeypatch.setattr(runner_module, "execute_task_automation", _should_not_execute)

    processed = runner_module.run_queued_automation_once(limit=5)
    assert processed >= 1

    status_payload = client.get(f"/api/tasks/{lead_task_id}/automation").json()
    assert status_payload['automation_state'] == 'completed'
    assert status_payload['team_mode_phase'] == 'deployment'
    assert status_payload['team_mode_blocking_gate'] == 'lead_waiting_merge_ready_developer'
    blocked_reason = str(status_payload.get('team_mode_blocked_reason') or '').lower()
    assert 'developer handoff is committed on a task branch and becomes merge-ready' in blocked_reason


def test_runner_lead_cycle_queues_qa_via_explicit_handoff_request(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Lead handoff queue QA test',
            'custom_statuses': ['To do', 'In Progress', 'In Review', 'Awaiting decision', 'Blocked', 'Completed'],
        },
    )
    assert project.status_code == 200
    project_id = project.json()['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    lead_assignee_id = team["lead"]
    qa_assignee_id = team["qa"]
    dev_assignee_id = team["dev1"]

    apply_docker = client.post(
        f'/api/projects/{project_id}/plugins/docker_compose/apply',
        json={
            'config': {
                'runtime_deploy_health': {
                    'required': True,
                    'stack': 'constructos-ws-default',
                    'port': 6768,
                    'health_path': '/health',
                    'require_http_200': True,
                },
            },
            'enabled': True,
        },
    )
    assert apply_docker.status_code == 200

    dev_task = client.post(
        '/api/tasks',
        json={
            'title': 'Developer output already merged',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Completed',
            'assignee_id': dev_assignee_id,
            'assigned_agent_code': 'dev-a',
            'instruction': 'Developer implementation delivered.',
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']
    patched_dev = client.patch(
        f"/api/tasks/{dev_task_id}",
        json={
            'external_refs': [
                {'url': 'commit:1111111111111111111111111111111111111111', 'title': 'commit evidence'},
                {'url': 'task/dev-merged-branch', 'title': 'task branch evidence'},
                {'url': 'merge:main:1111111111111111111111111111111111111111', 'title': 'merged to main'},
            ]
        },
    )
    assert patched_dev.status_code == 200

    qa_task = client.post(
        '/api/tasks',
        json={
            'title': 'QA task waiting for lead handoff',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': qa_assignee_id,
            'assigned_agent_code': 'qa-a',
            'instruction': 'Run QA checks after explicit lead handoff.',
        },
    )
    assert qa_task.status_code == 200
    qa_task_id = qa_task.json()['id']

    lead_task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead integration cycle',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': lead_assignee_id,
            'assigned_agent_code': 'lead-a',
            'instruction': 'Perform integration and handoff to QA.',
            'external_refs': [
                {'url': 'commit:2222222222222222222222222222222222222222', 'title': 'commit evidence'},
                {'url': 'task/lead-integration-branch', 'title': 'task branch evidence'},
                {'url': 'merge:main:2222222222222222222222222222222222222222', 'title': 'merged to main'},
            ],
            'task_type': 'scheduled_instruction',
            'scheduled_instruction': 'Perform integration and handoff to QA.',
            'scheduled_at_utc': (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
            'schedule_timezone': 'UTC',
            'recurring_rule': 'every:5m',
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    patched_dev_triggers = client.patch(
        f"/api/tasks/{dev_task_id}",
        json={
            'task_relationships': [
                {
                    'kind': 'delivers_to',
                    'task_ids': [lead_task_id],
                    'statuses': ['In Progress'],
                }
            ]
        },
    )
    assert patched_dev_triggers.status_code == 200

    patched_lead_triggers = client.patch(
        f"/api/tasks/{lead_task_id}",
        json={
            'task_relationships': [
                {
                    'kind': 'depends_on',
                    'task_ids': [dev_task_id],
                    'statuses': ['Completed'],
                },
            ]
        },
    )
    assert patched_lead_triggers.status_code == 200

    patched_qa_triggers = client.patch(
        f"/api/tasks/{qa_task_id}",
        json={
            'task_relationships': [
                {
                    'kind': 'hands_off_to',
                    'task_ids': [lead_task_id],
                    'statuses': ['In Progress'],
                }
            ]
        },
    )
    assert patched_qa_triggers.status_code == 200

    from features.agents.runner import _queue_qa_handoff_requests
    from shared.eventing_rebuild import rebuild_state
    from shared.models import SessionLocal

    handoff_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        state, _ = rebuild_state(db, "Task", lead_task_id)
        from shared.eventing import append_event

        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=lead_task_id,
            event_type="TaskUpdated",
            payload={
                "last_deploy_execution": {
                    "executed_at": handoff_at,
                    "stack": "constructos-ws-default",
                    "port": 6768,
                    "health_path": "/health",
                    "command": "docker compose -p constructos-ws-default up -d",
                    "manifest_path": "docker-compose.yml",
                    "runtime_type": "node_web",
                    "runtime_ok": True,
                    "http_url": "http://gateway:6768/health",
                    "http_status": 200,
                },
                "team_mode_phase": "qa_validation",
            },
            metadata={
                "actor_id": bootstrap["current_user"]["id"],
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": lead_task_id,
            },
        )
        queued = _queue_qa_handoff_requests(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            lead_task_id=lead_task_id,
            actor_user_id=bootstrap["current_user"]["id"],
            lead_handoff_token=f"lead:{lead_task_id}:{handoff_at}",
            lead_handoff_at=handoff_at,
            lead_handoff_refs=[],
        )
        db.commit()

    assert queued >= 1

    qa_status = client.get(f"/api/tasks/{qa_task_id}/automation").json()
    assert qa_status['automation_state'] in {'queued', 'running', 'completed'}
    assert qa_status.get('last_requested_source') == 'lead_handoff'
    assert qa_status.get('last_ignored_request_source') in {None, '', 'status_change'}

    checks_verify = client.get(f"/api/projects/{project_id}/checks/verify")
    assert checks_verify.status_code == 200
    workflow_communication = (
        checks_verify.json().get("workflow_communication")
        if isinstance(checks_verify.json().get("workflow_communication"), dict)
        else {}
    )
    ignored_events = [
        event
        for event in (workflow_communication.get("events") or [])
        if isinstance(event, dict)
        and str(event.get("task_id") or "").strip() == qa_task_id
        and str(event.get("delivery") or "").strip() == "ignored"
        and str(event.get("source") or "").strip() == "status_change"
    ]
    assert ignored_events == []


def test_team_mode_transition_uses_task_workflow_role_not_owner_membership_role(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Workflow-role transition check',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': team['dev1'],
            'assigned_agent_code': 'dev-a',
            'instruction': 'Implement and handoff.',
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    moved = client.patch(f'/api/tasks/{task_id}', json={'status': 'In Review'})
    assert moved.status_code == 200
    assert moved.json()['status'] == 'In Review'


def test_team_mode_rejects_lead_completion_transition_before_closeout_prereqs(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})

    service = AgentTaskService()
    service.archive_all_tasks(workspace_id=ws_id, project_id=project_id)

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Lead deploy task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Coordinate deploy and QA handoff.',
        },
    )
    assert created.status_code == 200

    blocked = client.patch(f"/api/tasks/{created.json()['id']}", json={'status': 'Completed'})
    assert blocked.status_code == 409
    assert "Lead Completed transition blocked" in str(blocked.json().get('detail') or '')


def test_runner_can_complete_task_from_instruction(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    task = client.post('/api/tasks', json={'title': 'Complete me', 'workspace_id': ws_id, 'project_id': project_id}).json()

    import features.tasks.command_handlers as task_handlers

    def _classified_complete(**kwargs):
        _ = kwargs
        return {
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
            'workflow_scope': 'unknown',
            'execution_mode': 'unknown',
            'deploy_requested': False,
            'docker_compose_requested': False,
            'requested_port': None,
            'project_name_provided': False,
            'task_completion_requested': True,
            'reason': 'Explicit task completion requested.',
        }

    from pytest import MonkeyPatch

    monkeypatch = MonkeyPatch()
    monkeypatch.setattr(task_handlers, 'classify_instruction_intent', _classified_complete)

    try:
        queued = client.post(f"/api/tasks/{task['id']}/automation/run", json={'instruction': 'Zatvori ovaj task sada.'})
        assert queued.status_code == 200

        from features.agents.runner import run_queued_automation_once

        processed = run_queued_automation_once(limit=5)
        assert processed >= 1

        refreshed = client.get(f"/api/tasks?workspace_id={ws_id}&project_id={project_id}&q=Complete me")
        assert refreshed.status_code == 200
        current = next(t for t in refreshed.json()['items'] if t['id'] == task['id'])
        assert current['status'] == 'Done'
    finally:
        monkeypatch.undo()


def test_runner_kickoff_does_not_complete_team_lead_oversight_task(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    due_at = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    members = client.get(f"/api/projects/{project_id}/members")
    assert members.status_code == 200
    lead_assignee_id = team["lead"]

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Lead kickoff should stay active',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'assignee_id': lead_assignee_id,
            'assigned_agent_code': 'lead-a',
            'task_type': 'scheduled_instruction',
            'scheduled_instruction': 'Lead oversight cycle',
            'scheduled_at_utc': due_at,
            'schedule_timezone': 'UTC',
            'recurring_rule': 'every:5m',
            'execution_triggers': [
                {
                    'kind': 'schedule',
                    'enabled': True,
                    'scheduled_at_utc': due_at,
                    'schedule_timezone': 'UTC',
                    'run_on_statuses': ['Awaiting decision'],
                    'recurring_rule': 'every:5m',
                },
            ],
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    queued = client.post(
        f"/api/tasks/{task_id}/automation/run",
        json={
            'instruction': f'Team Mode kickoff for project {project_id}.\nDispatch-only run.',
            'execution_intent': True,
            'execution_kickoff_intent': True,
            'project_creation_intent': False,
            'workflow_scope': 'team_mode',
            'execution_mode': 'kickoff_only',
        },
    )
    assert queued.status_code == 200

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome

    monkeypatch.setattr(
        runner_module,
        "execute_task_automation",
        lambda **_: AutomationOutcome(action="complete", summary="Kickoff completed", comment=None, usage=None),
    )

    processed = runner_module.run_queued_automation_once(limit=5)
    assert processed >= 1

    status_payload = client.get(f"/api/tasks/{task_id}/automation").json()
    assert status_payload['automation_state'] == 'completed'

    refreshed = client.get(f"/api/tasks?workspace_id={ws_id}&project_id={project_id}&q=Lead kickoff should stay active")
    assert refreshed.status_code == 200
    task_payload = next(t for t in refreshed.json()['items'] if t['id'] == task_id)
    assert task_payload['status'] == 'In Progress'
    assert task_payload['completed_at'] is None


def test_prompt_tetris_setup_spec_three_tasks_and_kickoff_sends_human_notification(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    current_user_id = bootstrap["current_user"]["id"]

    from features.agents.service import AgentTaskService

    service = AgentTaskService(
        require_token=False,
        actor_user_id=current_user_id,
        allowed_workspace_ids={ws_id},
        allowed_project_ids=set(),
        default_workspace_id=ws_id,
    )

    setup = service.setup_project_orchestration(
        workspace_id=ws_id,
        name="Tetris",
        short_description="Web game Tetris",
        primary_starter_key="web_game",
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=True,
        docker_port=6768,
        seed_team_tasks=False,
        kickoff_after_setup=False,
        command_id="e2e-prompt-tetris-setup",
    )
    assert setup.get("contract_version") == 1
    project = dict(setup.get("project") or {})
    project_id = str(project.get("id") or "").strip()
    assert project_id

    roles = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    spec = client.post(
        "/api/specifications",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Implement web game Tetris",
            "body": "Create an MVP web-based Tetris with gameplay, controls, and validation.",
        },
    )
    assert spec.status_code == 200
    spec_id = spec.json()["id"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "title": "Implement core gameplay loop",
            "workspace_id": ws_id,
            "project_id": project_id,
            "specification_id": spec_id,
            "status": "To do",
            "assignee_id": roles["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement gameplay loop and controls.",
            "task_relationships": [
                {
                    "kind": "delivers_to",
                    "task_ids": [],
                    "statuses": ["Awaiting decision"],
                }
            ],
        },
    )
    qa_task = client.post(
        "/api/tasks",
        json={
            "title": "Validate gameplay quality",
            "workspace_id": ws_id,
            "project_id": project_id,
            "specification_id": spec_id,
            "status": "In Progress",
            "assignee_id": roles["qa"],
            "assigned_agent_code": "qa-a",
            "instruction": "Validate gameplay behavior and acceptance criteria.",
            "task_relationships": [
                {
                    "kind": "hands_off_to",
                    "task_ids": [],
                    "statuses": ["In Progress"],
                }
            ],
        },
    )
    lead_task = client.post(
        "/api/tasks",
        json={
            "title": "Coordinate deployment readiness",
            "workspace_id": ws_id,
            "project_id": project_id,
            "specification_id": spec_id,
            "status": "To do",
            "assignee_id": roles["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Coordinate handoffs, deployment, and release readiness.",
            "task_relationships": [
                {"kind": "depends_on", "task_ids": [], "statuses": ["Awaiting decision"]},
                {"kind": "depends_on", "task_ids": [], "statuses": ["Blocked"]},
            ],
        },
    )
    assert dev_task.status_code == 200
    assert qa_task.status_code == 200
    assert lead_task.status_code == 200
    dev_task_id = dev_task.json()["id"]
    qa_task_id = qa_task.json()["id"]
    lead_task_id = lead_task.json()["id"]

    patched_lead = client.patch(
        f"/api/tasks/{lead_task_id}",
        json={
            "task_relationships": [
                {
                    "kind": "depends_on",
                    "task_ids": [dev_task_id],
                    "statuses": ["Awaiting decision"],
                },
                {
                    "kind": "depends_on",
                    "task_ids": [dev_task_id, qa_task_id],
                    "statuses": ["Blocked"],
                },
            ]
        },
    )
    assert patched_lead.status_code == 200

    patched_dev = client.patch(
        f"/api/tasks/{dev_task_id}",
        json={
            "task_relationships": [
                {
                    "kind": "delivers_to",
                    "task_ids": [lead_task_id],
                    "statuses": ["Awaiting decision"],
                }
            ]
        },
    )
    assert patched_dev.status_code == 200

    patched_qa = client.patch(
        f"/api/tasks/{qa_task_id}",
        json={
            "task_relationships": [
                {
                    "kind": "hands_off_to",
                    "task_ids": [lead_task_id],
                    "statuses": ["In Progress"],
                }
            ]
        },
    )
    assert patched_qa.status_code == 200

    kickoff = service._dispatch_team_mode_kickoff_after_setup(
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=None,
        command_id="e2e-prompt-tetris-kickoff",
    )
    assert isinstance(kickoff, dict)
    assert bool(kickoff.get("ok")) is True
    assert bool(kickoff.get("kickoff_dispatched")) is True
    queued_task_ids = [str(item or "").strip() for item in (kickoff.get("queued_task_ids") or []) if str(item or "").strip()]
    assert dev_task_id in queued_task_ids
    assert lead_task_id not in queued_task_ids

    listed = client.get(f"/api/tasks?workspace_id={ws_id}&project_id={project_id}&specification_id={spec_id}")
    assert listed.status_code == 200
    items = listed.json().get("items") or []
    assert len(items) == 3


def _legacy_test_team_mode_topology_backfill_normalizes_single_lead_schedule_to_awaiting_decision(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    current_user_id = bootstrap["current_user"]["id"]

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    from features.agents.service import AgentTaskService

    service = AgentTaskService(
        require_token=False,
        actor_user_id=current_user_id,
        allowed_workspace_ids={ws_id},
        allowed_project_ids={project_id},
        default_workspace_id=ws_id,
    )

    spec = client.post(
        "/api/specifications",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Implement web Tetris",
            "body": "Generic Team Mode topology backfill.",
        },
    )
    assert spec.status_code == 200
    spec_id = spec.json()["id"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "specification_id": spec_id,
            "title": "Build gameplay",
            "status": "In Progress",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement gameplay.",
        },
    )
    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "specification_id": spec_id,
            "title": "Coordinate release",
            "status": "Awaiting decision",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Coordinate integration and deployment.",
            "task_type": "scheduled_instruction",
            "scheduled_instruction": "Coordinate integration and deployment.",
            "scheduled_at_utc": "2026-03-10T08:00:00Z",
            "recurring_rule": "every:5m",
            "execution_triggers": [
                {
                    "kind": "schedule",
                    "enabled": True,
                    "scheduled_at_utc": "2026-03-10T08:00:00Z",
                    "recurring_rule": "every:5m",
                    "run_on_statuses": ["In Progress"],
                    "action": "request_automation",
                }
            ],
        },
    )
    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "specification_id": spec_id,
            "title": "Validate release",
            "status": "In Progress",
            "assignee_id": team["qa"],
            "assigned_agent_code": "qa-a",
            "instruction": "Validate release quality.",
        },
    )
    assert dev_task.status_code == 200
    assert lead_task.status_code == 200
    assert qa_task.status_code == 200

    service._maybe_backfill_team_mode_topology(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=spec_id,
        auth_token="",
        command_id="tm-topology-backfill",
    )

    refreshed = client.get(f"/api/tasks/{lead_task.json()['id']}")
    assert refreshed.status_code == 200
    triggers = refreshed.json()["execution_triggers"]
    assert isinstance(triggers, list)
    assert len(triggers) == 1
    assert triggers[0]["run_on_statuses"] == ["Awaiting decision"]


def test_setup_orchestration_e2e_emits_project_completed_notification(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    current_user_id = bootstrap["current_user"]["id"]

    from features.agents.service import AgentTaskService
    from features.agents.executor import AutomationOutcome
    from shared.eventing import rebuild_state
    from shared.models import Notification, Project, SessionLocal
    import features.agents.runner as runner_module

    service = AgentTaskService(
        require_token=False,
        actor_user_id=current_user_id,
        allowed_workspace_ids={ws_id},
        allowed_project_ids=set(),
        default_workspace_id=ws_id,
    )

    setup = service.setup_project_orchestration(
        workspace_id=ws_id,
        name="Completion E2E",
        short_description="Simple completion flow validation.",
        primary_starter_key="blank",
        enable_team_mode=False,
        enable_git_delivery=False,
        enable_docker_compose=False,
        seed_team_tasks=False,
        kickoff_after_setup=False,
        command_id="e2e-project-completion-setup",
    )
    project = dict(setup.get("project") or {})
    project_id = str(project.get("id") or "").strip()
    assert project_id

    task_a = client.post(
        "/api/tasks",
        json={
            "title": "E2E task A",
            "workspace_id": ws_id,
            "project_id": project_id,
            "status": "To do",
            "instruction": "Complete task A",
            "external_refs": [
                {"url": "https://app.example.test", "title": "Live deployment URL"},
            ],
        },
    )
    task_b = client.post(
        "/api/tasks",
        json={
            "title": "E2E task B",
            "workspace_id": ws_id,
            "project_id": project_id,
            "status": "To do",
            "instruction": "Complete task B",
        },
    )
    assert task_a.status_code == 200
    assert task_b.status_code == 200
    task_a_id = str(task_a.json().get("id") or "")
    task_b_id = str(task_b.json().get("id") or "")
    assert task_a_id and task_b_id

    monkeypatch.setattr(
        runner_module,
        "execute_task_automation",
        lambda **_: AutomationOutcome(
            action="complete",
            summary="Completed task successfully.",
            comment="Completed task successfully.",
        ),
    )
    monkeypatch.setattr(runner_module, "_project_has_repo_context", lambda **_: True)

    execution_request = {
        "execution_intent": True,
        "execution_kickoff_intent": False,
        "project_creation_intent": False,
        "workflow_scope": "task_execution",
        "execution_mode": "resume_execution",
        "task_completion_requested": True,
        "classifier_reason": "test override",
    }
    queued_a = client.post(
        f"/api/tasks/{task_a_id}/automation/run",
        json={"instruction": "Complete A", **execution_request},
    )
    queued_b = client.post(
        f"/api/tasks/{task_b_id}/automation/run",
        json={"instruction": "Complete B", **execution_request},
    )
    assert queued_a.status_code == 200
    assert queued_b.status_code == 200

    processed_first = runner_module.run_queued_automation_once(limit=1)
    processed_second = runner_module.run_queued_automation_once(limit=1)
    assert processed_first >= 1
    assert processed_second >= 1

    with SessionLocal() as db:
        notices = (
            db.query(Notification)
            .filter(
                Notification.workspace_id == ws_id,
                Notification.project_id == project_id,
                Notification.user_id == current_user_id,
                Notification.source_event == "agents.runner.project_completed",
            )
            .order_by(Notification.created_at.asc())
            .all()
        )
    assert len(notices) == 1
    payload = json.loads(str(notices[0].payload_json or "{}"))
    assert payload.get("kind") == "project_completed"
    assert int(payload.get("done_tasks") or 0) == 2
    assert int(payload.get("total_tasks") or 0) == 2
    assert isinstance(payload.get("project_completion_finalized_at"), str)
    note_id = str(payload.get("note_id") or "").strip()
    assert note_id

    notes = client.get(f"/api/notes?workspace_id={ws_id}&project_id={project_id}&q=Project Completion Report")
    assert notes.status_code == 200
    note_items = notes.json()["items"]
    assert len(note_items) == 1
    note_payload = note_items[0]
    assert note_payload["id"] == note_id
    assert "Project Completion Report" in note_payload["title"]
    assert "## Completed Tasks" in note_payload["body"]
    assert "E2E task A" in note_payload["body"]
    assert "E2E task B" in note_payload["body"]
    note_urls = [str(item.get("url") or "").strip() for item in note_payload.get("external_refs") or []]
    assert "https://app.example.test" in note_urls

    with SessionLocal() as db:
        project_row = db.get(Project, project_id)
        assert project_row is not None
        project_refs = json.loads(str(project_row.external_refs or "[]"))
    project_urls = [str(item.get("url") or "").strip() for item in project_refs if isinstance(item, dict)]
    assert "https://app.example.test" in project_urls

    with SessionLocal() as db:
        state_a, _ = rebuild_state(db, "Task", task_a_id)
        state_b, _ = rebuild_state(db, "Task", task_b_id)
    assert isinstance(state_a.get("project_completion_finalized_at"), str)
    assert isinstance(state_b.get("project_completion_finalized_at"), str)


def test_runner_escalates_dev_automation_failure_to_team_lead_and_notifies_human(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _enable_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    members = client.get(f"/api/projects/{project_id}/members")
    assert members.status_code == 200
    items = members.json()["items"]
    lead_assignee_id = team["lead"]
    dev_assignee_id = team["dev1"]

    lead_task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead blocker escalation task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'assignee_id': lead_assignee_id,
            'assigned_agent_code': 'lead-a',
            'instruction': 'Monitor blockers and coordinate unblock actions.',
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    dev_task = client.post(
        '/api/tasks',
        json={
            'title': 'Dev task that will fail',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': dev_assignee_id,
            'assigned_agent_code': 'dev-a',
            'instruction': 'Implement feature scope.',
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    queued = client.post(
        f"/api/tasks/{dev_task_id}/automation/run",
        json={
            'instruction': 'Run implementation',
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
            'workflow_scope': 'team_mode',
            'execution_mode': 'resume_execution',
            'task_completion_requested': False,
            'classifier_reason': 'test override',
        },
    )
    assert queued.status_code == 200

    import features.agents.runner as runner_module

    def _raise_failure(**_kwargs):
        raise RuntimeError("simulated dev failure")

    monkeypatch.setattr(runner_module, "execute_task_automation", _raise_failure)
    monkeypatch.setattr(runner_module, "_is_recoverable_failure", lambda _error: False)
    runner_module.run_queued_automation_once(limit=1)

    task_payload = client.get(f"/api/tasks/{dev_task_id}").json()
    assert task_payload["assigned_agent_code"] == "lead-a"
    assert task_payload["status"] == "Blocked"
    assert task_payload["assignee_id"] in {lead_assignee_id, None, ""}

    dev_status_payload = client.get(f"/api/tasks/{dev_task_id}/automation").json()
    assert dev_status_payload["automation_state"] in {"failed", "completed", "idle", "running"}

    lead_status_payload = client.get(f"/api/tasks/{lead_task_id}/automation").json()
    assert lead_status_payload["automation_state"] in {"idle", "queued", "running", "completed"}


def test_runner_returns_lead_deploy_topology_failure_to_developer_without_failed_terminal_state(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _enable_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead deploy topology mismatch',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Deploy the merged runtime.',
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    from features.agents.runner import _handoff_failed_team_mode_lead_task_to_developer
    from shared.eventing_rebuild import rebuild_state
    from shared.models import SessionLocal

    with SessionLocal() as db:
        state, _ = rebuild_state(db, "Task", lead_task_id)
        queued = _handoff_failed_team_mode_lead_task_to_developer(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            task_id=lead_task_id,
            state=state,
            actor_user_id=team['lead'],
            failed_at_iso='2026-03-18T21:21:08Z',
            failure_reason=(
                "Lead deploy execution failed: docker compose up -d detected stale orphaned service state "
                "after a service rename/removal. Lead retried with --remove-orphans but the deploy still failed. "
                "time=\"2026-03-18T21:21:08Z\" level=warning msg=\"Found orphan containers ([constructos-ws-default-battle-city-1]) "
                "for this project. If you removed or renamed this service in your compose file, you can run this command with the --remove-orphans\""
            ),
            failure_gate='lead_deploy_topology_reconciliation_required',
        )
        db.commit()

    assert queued is True

    task_payload = client.get(f"/api/tasks/{lead_task_id}").json()
    assert task_payload["status"] == "In Progress"
    assert str(task_payload["assigned_agent_code"]).startswith("dev-")

    automation_payload = client.get(f"/api/tasks/{lead_task_id}/automation").json()
    assert automation_payload["automation_state"] == "queued"
    assert automation_payload["last_requested_source"] in {"lead_triage_return", "runner_orchestrator"}
    assert automation_payload["team_mode_phase"] == "implementation"
    assert automation_payload["team_mode_blocking_gate"] in {None, ""}


def test_runner_requeues_developer_merge_conflict_to_developer_reconciliation(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _enable_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    dev_assignee_id = team["dev1"]

    dev_task = client.post(
        '/api/tasks',
        json={
            'title': 'Developer task with stale branch',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': dev_assignee_id,
            'assigned_agent_code': 'dev-a',
            'instruction': 'Implement feature scope.',
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    queued = client.post(
        f"/api/tasks/{dev_task_id}/automation/run",
        json={
            'instruction': 'Run implementation',
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
            'workflow_scope': 'team_mode',
            'execution_mode': 'resume_execution',
            'task_completion_requested': False,
            'classifier_reason': 'test override',
        },
    )
    assert queued.status_code == 200

    import features.agents.runner as runner_module

    def _raise_merge_conflict(**_kwargs):
        raise RuntimeError(
            "Runner error: Developer merge to main failed for task/test-branch: "
            "Automatic merge failed; fix conflicts and then commit the result."
        )

    monkeypatch.setattr(runner_module, "execute_task_automation", _raise_merge_conflict)
    runner_module.run_queued_automation_once(limit=1)

    task_payload = client.get(f"/api/tasks/{dev_task_id}").json()
    assert task_payload["assigned_agent_code"] == "dev-a"
    assert task_payload["status"] == "In Progress"
    assert str(task_payload["assignee_id"] or "").strip()

    automation_payload = client.get(f"/api/tasks/{dev_task_id}/automation").json()
    assert automation_payload["automation_state"] in {"queued", "running", "failed"}
    assert automation_payload.get("team_mode_blocking_gate") == "developer_main_reconciliation_required"

    from shared.models import Notification, SessionLocal

    with SessionLocal() as db:
        triage_notice = (
            db.query(Notification)
            .filter(
                Notification.workspace_id == ws_id,
                Notification.project_id == project_id,
                Notification.user_id == bootstrap["current_user"]["id"],
                Notification.source_event == "agents.runner.team_mode_triage_required",
            )
            .order_by(Notification.created_at.desc())
            .first()
        )
        assert triage_notice is None
        blocked_notice = (
            db.query(Notification)
            .filter(
                Notification.workspace_id == ws_id,
                Notification.project_id == project_id,
                Notification.user_id == bootstrap["current_user"]["id"],
                Notification.source_event == "agents.runner.automation_blocked",
            )
            .order_by(Notification.created_at.desc())
            .first()
        )
        assert blocked_notice is None


def test_runner_requeues_developer_handoff_without_branch_commit_to_developer(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _enable_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    dev_assignee_id = team["dev1"]

    dev_task = client.post(
        '/api/tasks',
        json={
            'title': 'Developer task without committed handoff',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': dev_assignee_id,
            'assigned_agent_code': 'dev-a',
            'instruction': 'Implement feature scope.',
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    queued = client.post(
        f"/api/tasks/{dev_task_id}/automation/run",
        json={
            'instruction': 'Run implementation',
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
            'workflow_scope': 'team_mode',
            'execution_mode': 'resume_execution',
            'task_completion_requested': False,
            'classifier_reason': 'test override',
        },
    )
    assert queued.status_code == 200

    import features.agents.runner as runner_module

    def _raise_uncommitted_handoff(**_kwargs):
        raise RuntimeError(
            "Runner error: Developer handoff is not committed on a task branch ahead of main yet. "
            "Branch `task/test-branch` is still at `abc1234`, same as `main`."
        )

    monkeypatch.setattr(runner_module, "execute_task_automation", _raise_uncommitted_handoff)
    runner_module.run_queued_automation_once(limit=1)

    task_payload = client.get(f"/api/tasks/{dev_task_id}").json()
    assert task_payload["assigned_agent_code"] == "dev-a"
    assert task_payload["status"] == "In Progress"
    assert str(task_payload["assignee_id"] or "").strip()

    automation_payload = client.get(f"/api/tasks/{dev_task_id}/automation").json()
    assert automation_payload["automation_state"] in {"queued", "running", "failed"}
    assert automation_payload.get("team_mode_blocking_gate") == "developer_handoff_not_committed"

    from shared.models import Notification, SessionLocal

    with SessionLocal() as db:
        triage_notice = (
            db.query(Notification)
            .filter(
                Notification.workspace_id == ws_id,
                Notification.project_id == project_id,
                Notification.user_id == bootstrap["current_user"]["id"],
                Notification.source_event == "agents.runner.team_mode_triage_required",
            )
            .order_by(Notification.created_at.desc())
            .first()
        )
        assert triage_notice is None


def test_runner_requeues_stale_task_branch_to_developer_reconciliation(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _enable_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    dev_assignee_id = team["dev1"]

    dev_task = client.post(
        '/api/tasks',
        json={
            'title': 'Developer task with stale branch',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': dev_assignee_id,
            'assigned_agent_code': 'dev-a',
            'instruction': 'Implement feature scope.',
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    queued = client.post(
        f"/api/tasks/{dev_task_id}/automation/run",
        json={
            'instruction': 'Run implementation',
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
            'workflow_scope': 'team_mode',
            'execution_mode': 'resume_execution',
            'task_completion_requested': False,
            'classifier_reason': 'test override',
        },
    )
    assert queued.status_code == 200

    import features.agents.runner as runner_module

    def _raise_stale_branch(**_kwargs):
        raise RuntimeError(
            "Runner error: Developer task branch must be reconciled with the latest `main` before Lead review. "
            "Branch `task/test-branch` at `abc1234` does not contain current `main` `def5678`."
        )

    monkeypatch.setattr(runner_module, "execute_task_automation", _raise_stale_branch)
    runner_module.run_queued_automation_once(limit=1)

    task_payload = client.get(f"/api/tasks/{dev_task_id}").json()
    assert task_payload["assigned_agent_code"] == "dev-a"
    assert task_payload["status"] == "In Progress"
    assert str(task_payload["assignee_id"] or "").strip()

    automation_payload = client.get(f"/api/tasks/{dev_task_id}/automation").json()
    assert automation_payload["automation_state"] in {"queued", "running", "failed"}
    assert automation_payload.get("team_mode_blocking_gate") == "developer_main_reconciliation_required"


def test_developer_merge_to_main_is_blocked_while_project_deploy_lock_is_active(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    os.environ["AGENT_CODEX_WORKDIR"] = str(tmp_path / "workspace")

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    from shared.project_repository import ensure_project_repository_initialized
    from shared.models import Project, SessionLocal
    from shared.eventing import append_event
    from shared.settings import AGENT_SYSTEM_USER_ID
    from features.agents.runner import _merge_current_task_branch_to_main
    import features.agents.runner as runner_module
    import subprocess

    with SessionLocal() as db:
        project_row = db.get(Project, project_id)
        project_name = str(getattr(project_row, 'name', '') or '').strip() or 'Demo Project'
    repo_root = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=repo_root, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=repo_root, check=True)
    (repo_root / 'README.md').write_text('base\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'README.md'], cwd=repo_root, check=True)
    subprocess.run(['git', 'commit', '-m', 'Initial'], cwd=repo_root, check=True)

    original_resolver = runner_module.resolve_project_repository_path
    runner_module.resolve_project_repository_path = lambda **_kwargs: repo_root

    lead_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Lead deploy task',
            'status': 'In Progress',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Deploy current slice.',
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    dev_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Developer task waiting to merge',
            'status': 'In Progress',
            'assignee_id': team['dev1'],
            'assigned_agent_code': 'dev-a',
            'instruction': 'Implement feature scope.',
            'external_refs': [
                {'url': 'task/dev-freeze-branch', 'title': 'task branch'},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    subprocess.run(['git', 'checkout', '-b', 'task/dev-freeze-branch'], cwd=repo_root, check=True)
    (repo_root / 'feature.txt').write_text('feature\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'feature.txt'], cwd=repo_root, check=True)
    subprocess.run(['git', 'commit', '-m', 'Feature'], cwd=repo_root, check=True)
    subprocess.run(['git', 'checkout', 'main'], cwd=repo_root, check=True)

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=lead_task_id,
            event_type='TaskUpdated',
                payload={
                    'deploy_lock_id': 'deploy-lock:test',
                    'deploy_lock_acquired_at': '2099-03-16T22:00:00Z',
                    'deploy_lock_released_at': None,
                    'last_deploy_cycle_id': 'deploy-cycle:test',
                },
            metadata={
                'actor_id': AGENT_SYSTEM_USER_ID,
                'workspace_id': ws_id,
                'project_id': project_id,
                'task_id': lead_task_id,
            },
        )
        db.commit()

    try:
        with SessionLocal() as db:
            result = _merge_current_task_branch_to_main(
                db=db,
                workspace_id=ws_id,
                project_id=project_id,
                task_id=dev_task_id,
                actor_user_id=AGENT_SYSTEM_USER_ID,
            )
    finally:
        runner_module.resolve_project_repository_path = original_resolver

    assert result['ok'] is False
    assert 'deployment in progress; merge to main is temporarily frozen' in str(result['error']).lower()


def test_developer_merge_to_main_rejects_literal_patch_markers(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    os.environ["AGENT_CODEX_WORKDIR"] = str(tmp_path / "workspace")

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    from shared.project_repository import ensure_project_repository_initialized
    from shared.models import Project, SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID
    from features.agents.runner import _merge_current_task_branch_to_main
    import features.agents.runner as runner_module
    import subprocess

    with SessionLocal() as db:
        project_row = db.get(Project, project_id)
        project_name = str(getattr(project_row, 'name', '') or '').strip() or 'Demo Project'
    repo_root = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=repo_root, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=repo_root, check=True)
    (repo_root / 'README.md').write_text('base\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'README.md'], cwd=repo_root, check=True)
    subprocess.run(['git', 'commit', '-m', 'Initial'], cwd=repo_root, check=True)

    original_resolver = runner_module.resolve_project_repository_path
    runner_module.resolve_project_repository_path = lambda **_kwargs: repo_root

    dev_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Developer task with malformed compose',
            'status': 'In Progress',
            'assignee_id': team['dev1'],
            'assigned_agent_code': 'dev-a',
            'instruction': 'Implement feature scope.',
            'external_refs': [
                {'url': 'task/dev-patch-marker-branch', 'title': 'task branch'},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    subprocess.run(['git', 'checkout', '-b', 'task/dev-patch-marker-branch'], cwd=repo_root, check=True)
    (repo_root / 'docker-compose.yml').write_text(
        "services:\n"
        "  app:\n"
        "    image: nginx:1.27-alpine\n"
        "*** End Patch\n",
        encoding='utf-8',
    )
    subprocess.run(['git', 'add', 'docker-compose.yml'], cwd=repo_root, check=True)
    subprocess.run(['git', 'commit', '-m', 'Malformed compose'], cwd=repo_root, check=True)
    subprocess.run(['git', 'checkout', 'main'], cwd=repo_root, check=True)

    try:
        with SessionLocal() as db:
            result = _merge_current_task_branch_to_main(
                db=db,
                workspace_id=ws_id,
                project_id=project_id,
                task_id=dev_task_id,
                actor_user_id=AGENT_SYSTEM_USER_ID,
            )
    finally:
        runner_module.resolve_project_repository_path = original_resolver

    assert result['ok'] is False
    assert 'literal patch markers' in str(result['error']).lower()


def test_lead_deploy_failure_returns_same_task_to_developer_for_scaffolding_fix(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    spec = client.post(
        '/api/specifications',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Implement Tetris',
        },
    )
    assert spec.status_code == 200
    spec_id = spec.json()['id']

    lead_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'specification_id': spec_id,
            'title': 'Build Tetris core slice',
            'status': 'In Progress',
            'priority': 'High',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Review merged slice and deploy.',
            'external_refs': [
                {'url': 'commit:abc1234abc1234abc1234abc1234abc1234ab', 'title': 'commit evidence'},
                {'url': 'task/fc414509-build-tetris-core-slice', 'title': 'task branch evidence'},
                {'url': 'merge:main:def5678def5678def5678def5678def5678de', 'title': 'merged to main'},
            ],
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    import features.agents.runner as runner_module
    from features.agents.runner import QueuedAutomationRun, _record_automation_failure

    repo_root = tmp_path / 'tetris-followup'
    src_dir = repo_root / 'src'
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / 'game.js').write_text('export const version = 1;\n', encoding='utf-8')

    monkeypatch.setattr(
        runner_module,
        'resolve_project_repository_path',
        lambda **_kwargs: repo_root,
    )

    _record_automation_failure(
        QueuedAutomationRun(
            task_id=lead_task_id,
            workspace_id=ws_id,
            project_id=project_id,
            title='Build Tetris core slice',
            description='',
            status='In Progress',
            instruction='Review merged slice and deploy.',
            request_source='developer_handoff',
            is_scheduled_run=False,
            trigger_task_id=None,
            trigger_from_status=None,
            trigger_to_status=None,
            triggered_at=None,
            actor_user_id=team['lead'],
        ),
        RuntimeError(
            'Lead deploy gate failed: compose manifest is missing and deterministic synthesis failed. '
            'unsupported runtime: repository does not contain Dockerfile, package.json, pyproject.toml, requirements.txt, or index.html'
        ),
    )

    refreshed_task = client.get(f"/api/tasks/{lead_task_id}").json()
    assert refreshed_task["status"] == "In Progress"
    assert refreshed_task["assigned_agent_code"] in {"dev-a", "dev-b"}
    assert refreshed_task["execution_triggers"] == [] or refreshed_task["execution_triggers"] is None

    automation_payload = client.get(f"/api/tasks/{lead_task_id}/automation").json()
    assert automation_payload['automation_state'] == 'queued'
    assert automation_payload['last_requested_source'] == 'lead_triage_return'
    assert automation_payload['team_mode_phase'] == 'implementation'
    assert automation_payload['team_mode_blocking_gate'] in {None, ""}
    remediation_instruction = str(automation_payload.get('last_requested_instruction') or '')
    assert "Inspect the existing code already present" in remediation_instruction
    assert "align your changes with that code" in remediation_instruction
    assert "assigned task worktree" in remediation_instruction


def test_lead_runtime_health_failure_returns_same_task_to_developer(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    spec = client.post(
        '/api/specifications',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Implement Tetris',
        },
    )
    assert spec.status_code == 200
    spec_id = spec.json()['id']

    plugin = client.post(
        f'/api/projects/{project_id}/plugins/docker_compose/apply',
        json={
            'expected_version': 1,
            'config': {
                'runtime_deploy_health': {
                    'required': True,
                    'stack': 'constructos-ws-default',
                    'port': 6768,
                    'health_path': '/health',
                    'host': 'gateway',
                    'require_http_200': True,
                }
            },
        },
    )
    assert plugin.status_code == 200

    lead_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'specification_id': spec_id,
            'title': 'Prepare deployable Tetris runtime',
            'status': 'In Progress',
            'priority': 'High',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Review merged slice and deploy.',
            'external_refs': [
                {'url': 'commit:abc1234abc1234abc1234abc1234abc1234ab', 'title': 'commit evidence'},
                {'url': 'task/lead-runtime-task', 'title': 'task branch evidence'},
                {'url': 'merge:main:def5678def5678def5678def5678def5678de', 'title': 'merged to main'},
                {'url': 'deploy:compose:/workspace/docker-compose.yml', 'title': 'compose manifest path'},
            ],
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    import features.agents.runner as runner_module
    from features.agents.runner import QueuedAutomationRun, _record_automation_failure

    repo_root = tmp_path / 'tetris-runtime-followup'
    src_dir = repo_root / 'src'
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / 'server.js').write_text('console.log("ready")\n', encoding='utf-8')
    (repo_root / 'package.json').write_text(
        json.dumps({'name': 'tetris', 'private': True, 'scripts': {'start': 'node src/server.js'}}),
        encoding='utf-8',
    )
    (repo_root / 'docker-compose.yml').write_text(
        "services:\n  web:\n    build: .\n    ports:\n      - '6768:6768'\n",
        encoding='utf-8',
    )

    monkeypatch.setattr(
        runner_module,
        'resolve_project_repository_path',
        lambda **_kwargs: repo_root,
    )

    _record_automation_failure(
        QueuedAutomationRun(
            task_id=lead_task_id,
            workspace_id=ws_id,
            project_id=project_id,
            title='Prepare deployable Tetris runtime',
            description='',
            status='In Progress',
            instruction='Review merged slice and deploy.',
            request_source='developer_handoff',
            is_scheduled_run=False,
            trigger_task_id=None,
            trigger_from_status=None,
            trigger_to_status=None,
            triggered_at=None,
            actor_user_id=team['lead'],
        ),
        RuntimeError(
            'Lead deploy gate failed: runtime health check did not pass '
            '(stack=constructos-ws-default, port=6768, path=/health)'
        ),
    )

    refreshed_task = client.get(f"/api/tasks/{lead_task_id}").json()
    assert refreshed_task["status"] == "In Progress"
    assert refreshed_task["assigned_agent_code"] in {"dev-a", "dev-b"}
    assert refreshed_task["execution_triggers"] == [] or refreshed_task["execution_triggers"] is None

    automation_payload = client.get(f"/api/tasks/{lead_task_id}/automation").json()
    assert automation_payload['automation_state'] == 'queued'
    assert automation_payload['last_requested_source'] == 'lead_triage_return'
    assert automation_payload['team_mode_phase'] == 'implementation'
    assert automation_payload['team_mode_blocking_gate'] in {None, ""}
    remediation_instruction = str(automation_payload.get('last_requested_instruction') or '')
    assert "http://gateway:6768/health" in remediation_instruction
    assert "Inspect the existing code already present" in remediation_instruction
    assert "align your changes with that code" in remediation_instruction


def test_probe_runtime_health_with_retry_waits_for_cold_start(monkeypatch):
    import features.agents.runner as runner_module

    attempts: list[int] = []

    def _fake_check(**_kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            return {
                'ok': False,
                'stack_running': True,
                'port_mapped': True,
                'http_200': False,
                'serves_application_root': False,
                'http_url': 'http://gateway:6768/health',
            }
        return {
            'ok': True,
            'stack_running': True,
            'port_mapped': True,
            'http_200': True,
            'serves_application_root': True,
            'http_url': 'http://gateway:6768/health',
            'root_url': 'http://gateway:6768/',
        }

    monkeypatch.setattr(runner_module, 'run_runtime_deploy_health_check', _fake_check)
    monkeypatch.setattr(runner_module.time, 'sleep', lambda _seconds: None)

    result = runner_module._probe_runtime_health_with_retry(
        stack='constructos-ws-default',
        port=6768,
        health_path='/health',
        require_http_200=True,
        host='gateway',
        attempts=4,
        delay_seconds=0.01,
    )

    assert len(attempts) == 3
    assert result['ok'] is True
    assert result['serves_application_root'] is True
    assert result['http_url'] == 'http://gateway:6768/health'


def test_blocker_escalation_persists_when_lead_is_already_running(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead integration task",
            "status": "In Progress",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Coordinate the workflow.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer implementation task",
            "status": "Blocked",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement feature scope.",
            "task_relationships": [
                {"kind": "delivers_to", "task_ids": [lead_task_id], "statuses": ["Awaiting decision"]},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    from shared.eventing import append_event
    from shared.eventing_rebuild import load_events_after, rebuild_state
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID
    import features.agents.runner as runner_module

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=lead_task_id,
            event_type="TaskAutomationRequested",
            payload={
                "requested_at": "2026-03-11T10:00:00Z",
                "instruction": "Lead kickoff/manual cycle.",
                "source": "manual",
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": lead_task_id,
            },
        )
        queued = runner_module._enqueue_team_lead_blocker_escalation(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            blocked_task_id=dev_task_id,
            blocked_title="Developer implementation task",
            blocked_role="Developer",
            blocked_status="Blocked",
            blocked_error="Runner error: Developer handoff is not committed on a task branch ahead of main yet.",
        )
        db.commit()
        lead_state, _ = rebuild_state(db, "Task", lead_task_id)
        lead_events = load_events_after(db, "Task", lead_task_id, 0)

    assert queued == 1
    assert lead_state["last_requested_source"] == "blocker_escalation"
    assert lead_state["last_requested_source_task_id"] == dev_task_id
    request_events = [
        event
        for event in lead_events
        if str(event.event_type or "").strip() == "TaskAutomationRequested"
    ]
    assert any(
        (dict(event.payload or {}).get("source") == "blocker_escalation")
        and (dict(event.payload or {}).get("source_task_id") == dev_task_id)
        for event in request_events
    )

    graph_res = client.get(f"/api/projects/{project_id}/task-dependency-graph")
    assert graph_res.status_code == 200
    graph_payload = graph_res.json()
    edge_map = {
        (str(item.get("source_entity_id") or ""), str(item.get("target_entity_id") or "")): item
        for item in (graph_payload.get("edges") or [])
    }
    dev_to_lead = edge_map[(dev_task_id, lead_task_id)]
    assert dev_to_lead["runtime_dependency"] is True
    assert dev_to_lead["runtime_sources"]["blocker_escalation"] >= 1


def test_runner_preflight_reports_role_coverage_and_topology_failures_separately(tmp_path, monkeypatch):
    from plugins.team_mode.plugin import TeamModePlugin
    import plugins.team_mode.plugin as plugin_module

    plugin = TeamModePlugin()

    monkeypatch.setattr(plugin_module, "team_mode_project_has_team_mode_enabled", lambda **_: True)
    monkeypatch.setattr(
        plugin_module,
        "policy_required_checks",
        lambda *_args, **_kwargs: ["role_coverage_present", "single_lead_present", "human_owner_present", "status_semantics_present"],
    )
    monkeypatch.setattr(
        plugin_module,
        "evaluate_required_checks",
        lambda _checks, _required: (False, ["role_coverage_present"]),
    )
    monkeypatch.setattr(
        plugin_module,
        "evaluate_team_mode_gates",
        lambda **_kwargs: {"checks": {"role_coverage_present": False, "single_lead_present": True, "human_owner_present": True, "status_semantics_present": True}},
    )

    class _FakeExecuteResult:
        def first(self):
            return ("{}", "{}")

        def all(self):
            return []

        def scalars(self):
            return self

    class _FakeDb:
        def execute(self, *_args, **_kwargs):
            return _FakeExecuteResult()

    role_message = plugin.runner_preflight_error(
        db=_FakeDb(),
        workspace_id="ws",
        project_id="proj",
        task_status="Lead",
        assignee_role="Lead",
        has_git_delivery_skill=False,
        has_repo_context=False,
    )
    assert role_message is not None
    assert "Team Mode project requirements are incomplete" in role_message
    assert "Developer, QA, and Lead agent coverage" in role_message


def test_runner_blocked_outcome_notifies_humans_with_dedupe(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    user_id = bootstrap["current_user"]["id"]

    task = client.post(
        '/api/tasks',
        json={
            'title': 'Blocked outcome task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'instruction': 'Implement feature and report blockers.',
        },
    )
    assert task.status_code == 200
    task_id = task.json()['id']

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome
    from shared.models import Notification, SessionLocal

    def _blocked_outcome(**_kwargs):
        return AutomationOutcome(
            action='comment',
            summary='BLOCKED\nRepository lock prevented progress.',
            comment='BLOCKED\nRepository lock prevented progress.',
        )

    monkeypatch.setattr(runner_module, "execute_task_automation", _blocked_outcome)

    queued_a = client.post(f"/api/tasks/{task_id}/automation/run", json={'instruction': 'Kickoff blocked run'})
    assert queued_a.status_code == 200
    runner_module.run_queued_automation_once(limit=1)

    queued_b = client.post(f"/api/tasks/{task_id}/automation/run", json={'instruction': 'Kickoff blocked run again'})
    assert queued_b.status_code == 200
    runner_module.run_queued_automation_once(limit=1)

    with SessionLocal() as db:
        notices = (
            db.query(Notification)
            .filter(
                Notification.workspace_id == ws_id,
                Notification.project_id == project_id,
                Notification.task_id == task_id,
                Notification.user_id == user_id,
                Notification.source_event == "agents.runner.automation_blocked",
            )
            .order_by(Notification.created_at.asc())
            .all()
        )
    assert len(notices) == 1
    notice = notices[0]
    assert notice.notification_type == "ManualMessage"
    assert notice.severity == "warning"
    payload = json.loads(str(notice.payload_json or "{}"))
    assert payload.get("kind") == "automation_blocked"
    assert payload.get("task_id") == task_id


def test_blocked_notifications_dedupe_by_task_phase_and_gate_even_when_comment_changes(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    user_id = bootstrap["current_user"]["id"]

    project = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Blocked dedupe project'})
    assert project.status_code == 200
    project_id = project.json()['id']

    task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead deploy task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'instruction': 'Coordinate deploy.',
        },
    )
    assert task.status_code == 200
    task_id = task.json()['id']

    from features.agents.runner import _notify_humans_blocked
    from shared.models import Notification, SessionLocal

    with SessionLocal() as db:
        _notify_humans_blocked(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            actor_user_id=user_id,
            task_id=task_id,
            task_title='Lead deploy task',
            task_status='Blocked',
            summary='Automation runner failed.',
            comment='First wording of the same deploy blocker.',
            blocking_gate='lead_runtime_health_failed',
            phase='deploy',
        )
        _notify_humans_blocked(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            actor_user_id=user_id,
            task_id=task_id,
            task_title='Lead deploy task',
            task_status='Blocked',
            summary='Automation runner failed.',
            comment='Second wording of the same deploy blocker.',
            blocking_gate='lead_runtime_health_failed',
            phase='deploy',
        )
        db.commit()

    with SessionLocal() as db:
        notices = (
            db.query(Notification)
            .filter(
                Notification.workspace_id == ws_id,
                Notification.project_id == project_id,
                Notification.task_id == task_id,
                Notification.user_id == user_id,
                Notification.source_event == "agents.runner.automation_blocked",
            )
            .order_by(Notification.created_at.asc())
            .all()
        )

    assert len(notices) == 1
    payload = json.loads(str(notices[0].payload_json or "{}"))
    assert payload.get("blocking_gate") == "lead_runtime_health_failed"
    assert payload.get("phase") == "deploy"


def test_nonblocking_team_mode_waiting_gates_do_not_emit_blocked_notifications(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    user_id = bootstrap["current_user"]["id"]

    project = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Waiting gate notification project'})
    assert project.status_code == 200
    project_id = project.json()['id']

    task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead coordination task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'instruction': 'Coordinate delivery.',
        },
    )
    assert task.status_code == 200
    task_id = task.json()['id']

    from features.agents.runner import _notify_humans_blocked
    from shared.models import Notification, SessionLocal

    with SessionLocal() as db:
        _notify_humans_blocked(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            actor_user_id=user_id,
            task_id=task_id,
            task_title='Lead coordination task',
            task_status='Lead',
            summary='Automation deferred by workflow gate.',
            comment='Lead is waiting for committed Developer handoff.',
            blocking_gate='lead_waiting_committed_developer_handoff',
            phase='triage',
        )
        db.commit()

    with SessionLocal() as db:
        notices = (
            db.query(Notification)
            .filter(
                Notification.workspace_id == ws_id,
                Notification.project_id == project_id,
                Notification.task_id == task_id,
                Notification.user_id == user_id,
                Notification.source_event == "agents.runner.automation_blocked",
            )
            .all()
        )

    assert notices == []


def test_autonomous_block_recovery_policy_suppresses_human_blocked_notification():
    from features.agents.runner import _should_notify_humans_about_blocked_automation

    assert _should_notify_humans_about_blocked_automation(
        team_mode_enabled=False,
        should_retry=False,
        non_blocking_gate_failure=False,
        lead_triage_handoff=False,
        lead_scaffolding_followup_task_id="followup-task-1",
        developer_main_reconciliation_queued=False,
        developer_handoff_recovery_queued=False,
        developer_deploy_lock_waiting=False,
    ) is False

    assert _should_notify_humans_about_blocked_automation(
        team_mode_enabled=False,
        should_retry=False,
        non_blocking_gate_failure=False,
        lead_triage_handoff=False,
        lead_scaffolding_followup_task_id=None,
        developer_main_reconciliation_queued=False,
        developer_handoff_recovery_queued=True,
        developer_deploy_lock_waiting=False,
    ) is False

    assert _should_notify_humans_about_blocked_automation(
        team_mode_enabled=False,
        should_retry=False,
        non_blocking_gate_failure=False,
        lead_triage_handoff=False,
        lead_scaffolding_followup_task_id=None,
        developer_main_reconciliation_queued=False,
        developer_handoff_recovery_queued=False,
        developer_deploy_lock_waiting=True,
    ) is False

    assert _should_notify_humans_about_blocked_automation(
        team_mode_enabled=False,
        should_retry=False,
        non_blocking_gate_failure=False,
        lead_triage_handoff=False,
        lead_scaffolding_followup_task_id=None,
        developer_main_reconciliation_queued=False,
        developer_handoff_recovery_queued=False,
        developer_deploy_lock_waiting=False,
    ) is True

    assert _should_notify_humans_about_blocked_automation(
        team_mode_enabled=True,
        should_retry=False,
        non_blocking_gate_failure=False,
        lead_triage_handoff=False,
        lead_scaffolding_followup_task_id=None,
        developer_main_reconciliation_queued=False,
        developer_handoff_recovery_queued=False,
        developer_deploy_lock_waiting=False,
    ) is False


def test_task_assigned_to_me_dedupes_repeated_same_transition(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created_user = client.post(
        '/api/admin/users',
        json={'workspace_id': ws_id, 'username': 'dedupe-assignee', 'full_name': 'Dedupe Assignee'},
    )
    assert created_user.status_code == 200
    assignee_id = created_user.json()['user']['id']

    task = client.post(
        '/api/tasks',
        json={
            'title': 'Assignment dedupe task',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    assert task.status_code == 200
    task_id = task.json()['id']

    first_assign = client.patch(
        f'/api/tasks/{task_id}',
        json={'assignee_id': assignee_id},
    )
    assert first_assign.status_code == 200

    second_assign = client.patch(
        f'/api/tasks/{task_id}',
        json={'assignee_id': assignee_id},
    )
    assert second_assign.status_code == 200

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
    assert rows[0].dedupe_key == f"task-assigned:{task_id}:none:{assignee_id}"


def test_team_mode_blocked_tasks_do_not_notify_human_owner_until_awaiting_decision(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    user_id = bootstrap["current_user"]["id"]

    team = _enable_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    dev_task = client.post(
        '/api/tasks',
        json={
            'title': 'Blocked Team Mode task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': team['dev1'],
            'assigned_agent_code': 'dev-a',
            'instruction': 'Implement feature scope.',
        },
    )
    assert dev_task.status_code == 200
    task_id = dev_task.json()['id']

    import features.agents.runner as runner_module
    from shared.models import Notification, SessionLocal

    def _raise_uncommitted_handoff(**_kwargs):
        raise RuntimeError(
            'Runner error: Developer handoff is not committed on a task branch ahead of main yet. '
            'Branch `task/test-branch` is still at `abc1234`, same as `main`.'
        )

    monkeypatch.setattr(runner_module, "execute_task_automation", _raise_uncommitted_handoff)
    queued = client.post(f"/api/tasks/{task_id}/automation/run", json={'instruction': 'Run implementation'})
    assert queued.status_code == 200
    runner_module.run_queued_automation_once(limit=1)

    with SessionLocal() as db:
        notices = (
            db.query(Notification)
            .filter(
                Notification.workspace_id == ws_id,
                Notification.project_id == project_id,
                Notification.user_id == user_id,
                Notification.task_id == task_id,
                Notification.source_event.in_([
                    "agents.runner.automation_blocked",
                    "agents.runner.team_mode_triage_required",
                ]),
            )
            .all()
        )
    assert notices == []


def test_runner_complete_outcome_notifies_humans_when_project_reaches_done(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    user_id = bootstrap["current_user"]["id"]

    project = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Completion project'})
    assert project.status_code == 200
    project_id = project.json()['id']

    task_a = client.post(
        '/api/tasks',
        json={
            'title': 'Completion task A',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'To do',
            'instruction': 'Complete task A.',
        },
    )
    task_b = client.post(
        '/api/tasks',
        json={
            'title': 'Completion task B',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'To do',
            'instruction': 'Complete task B.',
        },
    )
    assert task_a.status_code == 200
    assert task_b.status_code == 200
    task_a_id = task_a.json()['id']
    task_b_id = task_b.json()['id']

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome
    from shared.models import Notification, SessionLocal

    def _complete_outcome(**_kwargs):
        return AutomationOutcome(
            action='complete',
            summary='Completed task successfully.',
            comment='Completed task successfully.',
        )

    monkeypatch.setattr(runner_module, "execute_task_automation", _complete_outcome)
    monkeypatch.setattr(runner_module, "_project_has_repo_context", lambda **_: True)

    queued_a = client.post(f"/api/tasks/{task_a_id}/automation/run", json={'instruction': 'Complete A'})
    assert queued_a.status_code == 200
    runner_module.run_queued_automation_once(limit=1)

    with SessionLocal() as db:
        interim = (
            db.query(Notification)
            .filter(
                Notification.workspace_id == ws_id,
                Notification.project_id == project_id,
                Notification.user_id == user_id,
                Notification.source_event == "agents.runner.project_completed",
            )
            .all()
        )
    assert len(interim) == 0

    queued_b = client.post(f"/api/tasks/{task_b_id}/automation/run", json={'instruction': 'Complete B'})
    assert queued_b.status_code == 200
    runner_module.run_queued_automation_once(limit=1)

    with SessionLocal() as db:
        notices = (
            db.query(Notification)
            .filter(
                Notification.workspace_id == ws_id,
                Notification.project_id == project_id,
                Notification.user_id == user_id,
                Notification.source_event == "agents.runner.project_completed",
            )
            .order_by(Notification.created_at.asc())
            .all()
        )
    assert len(notices) == 1
    notice = notices[0]
    assert notice.notification_type == "ManualMessage"
    assert notice.severity == "info"
    payload = json.loads(str(notice.payload_json or "{}"))
    assert payload.get("kind") == "project_completed"
    assert int(payload.get("done_tasks") or 0) == 2
    assert int(payload.get("total_tasks") or 0) == 2


def test_runner_blocked_notification_falls_back_to_workspace_human_when_project_has_no_human_member(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    user_id = bootstrap["current_user"]["id"]

    project = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Blocked fallback project'})
    assert project.status_code == 200
    project_id = project.json()['id']

    from shared.models import Notification, ProjectMember, SessionLocal

    with SessionLocal() as db:
        db.query(ProjectMember).filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        ).delete()
        db.commit()

    task = client.post(
        '/api/tasks',
        json={
            'title': 'Blocked fallback task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'instruction': 'Implement feature and report blockers.',
        },
    )
    assert task.status_code == 200
    task_id = task.json()['id']

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome

    def _blocked_outcome(**_kwargs):
        return AutomationOutcome(
            action='comment',
            summary='BLOCKED\nRepository lock prevented progress.',
            comment='BLOCKED\nRepository lock prevented progress.',
        )

    monkeypatch.setattr(runner_module, "execute_task_automation", _blocked_outcome)

    queued = client.post(f"/api/tasks/{task_id}/automation/run", json={'instruction': 'Kickoff blocked fallback'})
    assert queued.status_code == 200
    runner_module.run_queued_automation_once(limit=1)

    with SessionLocal() as db:
        notices = (
            db.query(Notification)
            .filter(
                Notification.workspace_id == ws_id,
                Notification.project_id == project_id,
                Notification.user_id == user_id,
                Notification.source_event == "agents.runner.automation_blocked",
            )
            .order_by(Notification.created_at.asc())
            .all()
        )
    assert len(notices) == 1


def test_agent_service_create_task_backfills_structural_dependencies_from_priority(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    setup = service.setup_project_orchestration(
        name="Structural Dependency Backfill",
        short_description="Backfill dependencies for Team Mode implementation tasks.",
        primary_starter_key="web_game",
        workspace_id=ws_id,
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=False,
        seed_team_tasks=False,
        kickoff_after_setup=False,
        command_id="tm-structural-backfill-setup",
    )

    assert setup["blocking"] is False
    project_id = str((setup.get("project") or {}).get("id") or "").strip()
    assert project_id

    team = _ensure_team_mode_member_roles(workspace_id=ws_id, project_id=project_id)
    specification = service.create_specification(
        title="Implement Web Tetris Game",
        workspace_id=ws_id,
        project_id=project_id,
        auth_token="",
        command_id="tm-structural-backfill-spec",
    )
    specification_id = str(specification.get("id") or "").strip()
    assert specification_id

    high = service.create_task(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        title="Build the Tetris game engine",
        status="To Do",
        priority="High",
        assignee_id=team["dev1"],
        assigned_agent_code="dev-a",
        instruction="Implement the core engine first.",
        auth_token="",
        command_id="tm-structural-backfill-high",
    )
    med = service.create_task(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        title="Build the browser rendering layer",
        status="To Do",
        priority="Med",
        assignee_id=team["dev2"],
        assigned_agent_code="dev-b",
        instruction="Build the rendering layer after the engine is stable.",
        auth_token="",
        command_id="tm-structural-backfill-med",
    )
    low = service.create_task(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        title="Prepare packaging and deploy readiness",
        status="To Do",
        priority="Low",
        assignee_id=team["dev1"],
        assigned_agent_code="dev-a",
        instruction="Package the application after implementation tasks are complete.",
        auth_token="",
        command_id="tm-structural-backfill-low",
    )

    high_id = str(high.get("id") or "").strip()
    med_id = str(med.get("id") or "").strip()
    low_id = str(low.get("id") or "").strip()

    listed = service.list_tasks(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        archived=False,
        limit=10,
        offset=0,
        auth_token="",
    )
    items = {str(item.get("id") or "").strip(): item for item in (listed.get("items") or [])}
    assert set(items.keys()) == {high_id, med_id, low_id}

    assert items[high_id]["task_relationships"] == []
    assert items[med_id]["task_relationships"] == [
        {
            "kind": "depends_on",
            "task_ids": [high_id],
            "match_mode": "all",
            "statuses": ["merged"],
        }
    ]
    assert items[low_id]["task_relationships"] == [
        {
            "kind": "depends_on",
            "task_ids": [high_id, med_id],
            "match_mode": "all",
            "statuses": ["merged"],
        }
    ]


def test_api_create_task_auto_routes_team_mode_spec_tasks_and_backfills_dependencies(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_resp = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'API Team Mode Auto Routing',
            'custom_statuses': ['To Do', 'In Progress', 'In Review', 'Awaiting Decision', 'Blocked', 'Completed'],
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()['id']

    _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    spec_resp = client.post(
        '/api/specifications',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Implement Tetris',
        },
    )
    assert spec_resp.status_code == 200
    spec_id = spec_resp.json()['id']

    high = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'specification_id': spec_id,
            'title': 'Build engine',
            'status': 'To Do',
            'priority': 'High',
            'instruction': 'Implement the core Tetris engine.',
        },
    )
    med = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'specification_id': spec_id,
            'title': 'Build renderer',
            'status': 'To Do',
            'priority': 'Med',
            'instruction': 'Implement the renderer.',
        },
    )
    low = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'specification_id': spec_id,
            'title': 'Prepare deploy assets',
            'status': 'To Do',
            'priority': 'Low',
            'instruction': 'Prepare deployment assets.',
        },
    )
    assert high.status_code == 200
    assert med.status_code == 200
    assert low.status_code == 200

    high_payload = client.get(f"/api/tasks/{high.json()['id']}").json()
    med_payload = client.get(f"/api/tasks/{med.json()['id']}").json()
    low_payload = client.get(f"/api/tasks/{low.json()['id']}").json()

    assert high_payload["assigned_agent_code"] in {"dev-a", "dev-b"}
    assert med_payload["assigned_agent_code"] in {"dev-a", "dev-b"}
    assert low_payload["assigned_agent_code"] in {"dev-a", "dev-b"}
    assert high_payload["task_relationships"] == []
    assert med_payload["task_relationships"] == [
        {
            "kind": "depends_on",
            "task_ids": [high_payload["id"]],
            "match_mode": "all",
            "statuses": ["merged"],
        }
    ]
    assert low_payload["task_relationships"] == [
        {
            "kind": "depends_on",
            "task_ids": sorted([high_payload["id"], med_payload["id"]]),
            "match_mode": "all",
            "statuses": ["merged"],
        }
    ]


def test_api_team_mode_topology_strengthens_partial_dependencies_and_single_deployable_slice_for_docker(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_resp = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'API Team Mode Docker Topology',
            'custom_statuses': ['To Do', 'In Progress', 'In Review', 'Awaiting Decision', 'Blocked', 'Completed'],
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()['id']

    _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    docker_configured = client.post(
        f"/api/projects/{project_id}/plugins/docker_compose/apply",
        json={
            'enabled': True,
            'config': {
                'runtime_deploy_health': {
                    'required': True,
                    'stack': 'constructos-ws-default',
                    'host': 'gateway',
                    'port': 6768,
                    'health_path': '/health',
                    'require_http_200': True,
                },
            },
        },
    )
    assert docker_configured.status_code == 200

    spec_resp = client.post(
        '/api/specifications',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Implement Tetris',
        },
    )
    assert spec_resp.status_code == 200
    spec_id = spec_resp.json()['id']

    high = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'specification_id': spec_id,
            'title': 'Build engine',
            'status': 'To Do',
            'priority': 'High',
            'instruction': 'Implement the core Tetris engine.',
        },
    )
    assert high.status_code == 200
    med = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'specification_id': spec_id,
            'title': 'Build renderer',
            'status': 'To Do',
            'priority': 'Med',
            'instruction': 'Implement the renderer.',
        },
    )
    assert med.status_code == 200
    low = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'specification_id': spec_id,
            'title': 'Prepare deploy assets',
            'status': 'To Do',
            'priority': 'Low',
            'instruction': 'Prepare deployment assets.',
            'task_relationships': [
                {
                    'kind': 'depends_on',
                    'task_ids': [high.json()['id']],
                    'match_mode': 'all',
                    'statuses': ['merged'],
                }
            ],
        },
    )
    assert low.status_code == 200

    high_payload = client.get(f"/api/tasks/{high.json()['id']}").json()
    med_payload = client.get(f"/api/tasks/{med.json()['id']}").json()
    low_payload = client.get(f"/api/tasks/{low.json()['id']}").json()

    assert med_payload["task_relationships"] == [
        {
            "kind": "depends_on",
            "task_ids": [high_payload["id"]],
            "match_mode": "all",
            "statuses": ["merged"],
        }
    ]
    assert low_payload["task_relationships"] == [
        {
            "kind": "depends_on",
            "task_ids": sorted([high_payload["id"], med_payload["id"]]),
            "match_mode": "all",
            "statuses": ["merged"],
        }
    ]
    assert high_payload["delivery_mode"] == "merged_increment"
    assert med_payload["delivery_mode"] == "merged_increment"
    assert low_payload["delivery_mode"] == "deployable_slice"


def test_manual_automation_run_defaults_team_mode_scope_for_routed_task(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    spec_resp = client.post(
        '/api/specifications',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Implement Tetris',
        },
    )
    assert spec_resp.status_code == 200
    spec_id = spec_resp.json()['id']

    task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'specification_id': spec_id,
            'title': 'Build engine',
            'status': 'To Do',
            'priority': 'High',
            'instruction': 'Implement the core Tetris engine.',
        },
    )
    assert task.status_code == 200
    task_id = task.json()['id']
    assert task.json()['assigned_agent_code'] in {'dev-a', 'dev-b'}

    queued = client.post(
        f"/api/tasks/{task_id}/automation/run",
        json={'instruction': 'Implement the core game engine now.'},
    )
    assert queued.status_code == 200

    status = client.get(f"/api/tasks/{task_id}/automation")
    assert status.status_code == 200
    payload = status.json()
    assert payload["last_requested_workflow_scope"] == "team_mode"
    assert payload["last_requested_execution_mode"] == "resume_execution"


def test_manual_automation_run_skips_team_mode_task_when_structural_dependencies_are_unmet(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    spec_resp = client.post(
        '/api/specifications',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Implement Tetris',
        },
    )
    assert spec_resp.status_code == 200
    spec_id = spec_resp.json()['id']

    upstream = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'specification_id': spec_id,
            'title': 'Build engine',
            'status': 'To Do',
            'priority': 'High',
            'assignee_id': team['dev1'],
            'assigned_agent_code': 'dev-a',
            'instruction': 'Implement the engine on the task branch.',
        },
    )
    assert upstream.status_code == 200
    upstream_id = upstream.json()['id']

    downstream = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'specification_id': spec_id,
            'title': 'Build renderer',
            'status': 'To Do',
            'priority': 'Med',
            'assignee_id': team['dev2'],
            'assigned_agent_code': 'dev-b',
            'instruction': 'Implement the renderer on the task branch.',
            'task_relationships': [
                {'kind': 'depends_on', 'task_ids': [upstream_id], 'statuses': ['merged']},
            ],
        },
    )
    assert downstream.status_code == 200
    downstream_id = downstream.json()['id']

    queued = client.post(
        f"/api/tasks/{downstream_id}/automation/run",
        json={'instruction': 'Implement the renderer now.'},
    )
    assert queued.status_code == 200
    payload = queued.json()
    assert payload['skipped'] is True
    assert 'structural dependencies' in str(payload['reason'] or '').lower()

    status = client.get(f"/api/tasks/{downstream_id}/automation")
    assert status.status_code == 200
    automation_payload = status.json()
    assert automation_payload['automation_state'] in {'idle', ''}
    assert str(automation_payload.get('last_requested_source') or '').strip() == ''


def test_runner_project_completed_notification_falls_back_to_workspace_human_when_project_has_no_human_member(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    user_id = bootstrap["current_user"]["id"]

    project = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Completion fallback project'})
    assert project.status_code == 200
    project_id = project.json()['id']

    from shared.models import Notification, ProjectMember, SessionLocal

    with SessionLocal() as db:
        db.query(ProjectMember).filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        ).delete()
        db.commit()

    task_a = client.post(
        '/api/tasks',
        json={
            'title': 'Completion fallback A',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'To do',
            'instruction': 'Complete task A.',
        },
    )
    task_b = client.post(
        '/api/tasks',
        json={
            'title': 'Completion fallback B',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'To do',
            'instruction': 'Complete task B.',
        },
    )
    assert task_a.status_code == 200
    assert task_b.status_code == 200

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome

    def _complete_outcome(**_kwargs):
        return AutomationOutcome(
            action='complete',
            summary='Completed task successfully.',
            comment='Completed task successfully.',
        )

    monkeypatch.setattr(runner_module, "execute_task_automation", _complete_outcome)

    execution_request = {
        "execution_intent": True,
        "execution_kickoff_intent": False,
        "project_creation_intent": False,
        "workflow_scope": "task_execution",
        "execution_mode": "resume_execution",
        "task_completion_requested": True,
        "classifier_reason": "test override",
    }
    assert (
        client.post(
            f"/api/tasks/{task_a.json()['id']}/automation/run",
            json={'instruction': 'Complete A', **execution_request},
        ).status_code
        == 200
    )
    runner_module.run_queued_automation_once(limit=1)
    assert (
        client.post(
            f"/api/tasks/{task_b.json()['id']}/automation/run",
            json={'instruction': 'Complete B', **execution_request},
        ).status_code
        == 200
    )
    runner_module.run_queued_automation_once(limit=1)

    with SessionLocal() as db:
        notices = (
            db.query(Notification)
            .filter(
                Notification.workspace_id == ws_id,
                Notification.project_id == project_id,
                Notification.user_id == user_id,
                Notification.source_event == "agents.runner.project_completed",
            )
            .order_by(Notification.created_at.asc())
            .all()
        )
    assert len(notices) == 1


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


def test_runner_recoverable_failure_auto_requeues_without_blocking_dev(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _enable_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    dev_assignee_id = team["dev1"]

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Recoverable dev failure',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': dev_assignee_id,
            'instruction': 'Implement scoped change',
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    queued = client.post(f"/api/tasks/{task_id}/automation/run", json={'instruction': 'Run implementation'})
    assert queued.status_code == 200

    import features.agents.runner as runner_module

    def _recoverable_fail(**_kwargs):
        raise RuntimeError("upstream timeout while contacting model service")

    monkeypatch.setattr(runner_module, "execute_task_automation", _recoverable_fail)
    runner_module.run_queued_automation_once(limit=1)

    task_payload = client.get(f"/api/tasks/{task_id}").json()
    assert task_payload['status'] == 'In Progress'

    automation_payload = client.get(f"/api/tasks/{task_id}/automation").json()
    assert automation_payload['automation_state'] in {'queued', 'running'}
    assert automation_payload['last_requested_source'] == 'runner_recover_after_failure'


def test_runner_recoverable_failure_caps_retry_and_then_blocks_dev(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _enable_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    dev_assignee_id = team["dev1"]

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Recoverable failure capped',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': dev_assignee_id,
            'instruction': 'Implement scoped change',
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    queued = client.post(f"/api/tasks/{task_id}/automation/run", json={'instruction': 'Run implementation'})
    assert queued.status_code == 200

    import features.agents.runner as runner_module

    def _recoverable_fail(**_kwargs):
        raise RuntimeError("request timeout 504 gateway timeout")

    monkeypatch.setattr(runner_module, "execute_task_automation", _recoverable_fail)

    for _ in range(4):
        processed = runner_module.run_queued_automation_once(limit=1)
        assert processed >= 1

    task_payload = client.get(f"/api/tasks/{task_id}").json()
    assert task_payload['status'] == 'Awaiting Decision'

    automation_payload = client.get(f"/api/tasks/{task_id}/automation").json()
    assert automation_payload['automation_state'] == 'failed'


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


def test_agent_service_list_projects_uses_default_workspace_and_search(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    alpha = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Alpha Tetris'}).json()
    client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Beta Sudoku'}).json()

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    service = AgentTaskService()
    payload = service.list_projects(
        q='alpha',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )

    assert payload['workspace_id'] == ws_id
    assert payload['total'] >= 1
    assert [item['id'] for item in payload['items']] == [alpha['id']]


def test_agent_service_list_tasks_uses_default_workspace_with_project_id(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    created = client.post('/api/tasks', json={'workspace_id': ws_id, 'project_id': project_id, 'title': 'Workspace scoped list task'})
    assert created.status_code == 200

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    service = AgentTaskService()
    payload = service.list_tasks(
        project_id=project_id,
        limit=200,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )

    assert payload['total'] >= 1
    assert any(item['id'] == created.json()['id'] for item in payload['items'])


def test_agent_service_recurring_rule_infers_scheduled_task_type_on_create_and_update(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    created = service.create_task(
        title='MCP infer scheduled task type',
        workspace_id=ws_id,
        project_id=project_id,
        instruction='Run recurring check',
        scheduled_at_utc='2026-03-01T10:00:00+00:00',
        recurring_rule='every:1d',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert created['task_type'] == 'scheduled_instruction'
    assert created['scheduled_instruction'] == 'Run recurring check'
    assert created['recurring_rule'] == 'every:1d'

    manual = service.create_task(
        title='MCP infer scheduled patch target',
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    updated = service.update_task(
        task_id=manual['id'],
        patch={
            'instruction': 'Run recurring check from patch',
            'scheduled_at_utc': '2026-03-02T10:00:00+00:00',
            'recurring_rule': 'every:2d',
        },
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert updated['task_type'] == 'scheduled_instruction'
    assert updated['recurring_rule'] == 'every:2d'


def test_agent_service_create_note_accepts_string_tags_input(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    created = service.create_note(
        title='MCP string tags note',
        workspace_id=ws_id,
        project_id=project_id,
        tags='Ops, mcp',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert created['tags'] == ['ops', 'mcp']


def test_agent_service_long_command_id_does_not_overflow_bulk_and_archive_all(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    task_a = service.create_task(
        title='Overflow test A',
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    task_b = service.create_task(
        title='Overflow test B',
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    service.create_note(
        title='Overflow test note',
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )

    bulk_result = service.bulk_task_action(
        task_ids=[task_a['id'], task_b['id']],
        action='complete',
        command_id='b' * 64,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert bulk_result['updated'] >= 1

    archived_tasks = service.archive_all_tasks(
        workspace_id=ws_id,
        project_id=project_id,
        command_id='c' * 64,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert archived_tasks['updated'] >= 1

    archived_notes = service.archive_all_notes(
        workspace_id=ws_id,
        project_id=project_id,
        command_id='d' * 64,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert archived_notes['updated'] >= 1


def test_agent_service_create_task_accepts_status_on_create(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    created = service.create_task(
        title='MCP create with explicit status',
        workspace_id=ws_id,
        project_id=project_id,
        status='In Progress',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    assert created['status'] == 'In Progress'


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
                    'run_on_statuses': ['In Progress'],
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
                        'to_statuses': ['Completed'],
                    }
                ]
            ),
        },
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )
    status_change = [trigger for trigger in updated['execution_triggers'] if trigger.get('kind') == 'status_change']
    assert len(status_change) == 1
    assert status_change[0].get('to_statuses') == ['Completed']


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
    assert status_change[0].get('to_statuses') == ['Completed']


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


def test_agent_service_send_in_app_notification_creates_notification(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    sent = service.send_in_app_notification(
        user_id=user_id,
        message='Manual MCP notification',
        workspace_id=ws_id,
        project_id=project_id,
        notification_type='ManualMessage',
        severity='warning',
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
    )

    assert sent['ok'] is True
    assert sent['created'] is True
    assert sent['notification']['message'] == 'Manual MCP notification'
    assert sent['notification']['notification_type'] == 'ManualMessage'
    assert sent['notification']['severity'] == 'warning'
    assert sent['notification']['workspace_id'] == ws_id
    assert sent['notification']['project_id'] == project_id


def test_agent_service_send_in_app_notification_is_idempotent_with_command_id(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    user_id = bootstrap['current_user']['id']
    ws_id = bootstrap['workspaces'][0]['id']
    command_id = 'test-send-notification-idempotent'

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    service = AgentTaskService()
    first = service.send_in_app_notification(
        user_id=user_id,
        message='Idempotent notification',
        workspace_id=ws_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id=command_id,
    )
    second = service.send_in_app_notification(
        user_id=user_id,
        message='Idempotent notification',
        workspace_id=ws_id,
        auth_token=svc_module.MCP_AUTH_TOKEN or None,
        command_id=command_id,
    )

    assert first['created'] is True
    assert second['created'] is False
    assert first['notification']['id'] == second['notification']['id']


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


def test_agent_service_create_project_can_disable_event_storming(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})

    service = AgentTaskService()
    created = service.create_project(
        name='MCP No Event Storming',
        event_storming_enabled=False,
    )
    assert created['workspace_id'] == ws_id
    assert created['name'] == 'MCP No Event Storming'
    assert created['event_storming_enabled'] is False


def test_agent_service_create_project_adds_default_human_member_for_bot_actor(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    from shared.models import ProjectMember, SessionLocal
    from shared.settings import DEFAULT_USER_ID

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})

    service = AgentTaskService()
    created = service.create_project(name='MCP Human Visible Project')

    with SessionLocal() as db:
        member_ids = [
            str(row[0])
            for row in db.query(ProjectMember.user_id)
            .filter(ProjectMember.project_id == created['id'])
            .order_by(ProjectMember.id.asc())
            .all()
        ]
    assert '00000000-0000-0000-0000-000000000099' in member_ids
    assert DEFAULT_USER_ID in member_ids


def test_agent_service_create_project_adds_configured_claude_bot_member_when_codex_unavailable(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    from shared.models import ProjectMember, SessionLocal, User
    from shared.settings import DEFAULT_USER_ID

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(
        svc_module,
        "resolve_provider_effective_auth_source",
        lambda provider: "system_override" if provider == "claude" else "none",
    )

    service = AgentTaskService()
    created = service.create_project(name='MCP Claude Available Project')

    with SessionLocal() as db:
        member_rows = (
            db.query(ProjectMember.user_id, User.username)
            .join(User, User.id == ProjectMember.user_id)
            .filter(ProjectMember.project_id == created['id'])
            .order_by(ProjectMember.id.asc())
            .all()
        )
    member_ids = [str(user_id) for user_id, _ in member_rows]
    member_usernames = [str(username or "") for _, username in member_rows]

    assert 'codex-bot' in member_usernames
    assert 'claude-bot' in member_usernames
    assert DEFAULT_USER_ID in member_ids


def test_team_mode_task_assignment_reroutes_unavailable_codex_bot_to_claude(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    import features.tasks.command_handlers as task_handlers
    from shared.models import SessionLocal
    from shared.settings import CLAUDE_SYSTEM_USER_ID, CODEX_SYSTEM_USER_ID

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(
        svc_module,
        "resolve_provider_effective_auth_source",
        lambda provider: "system_override" if provider == "claude" else "none",
    )
    monkeypatch.setattr(
        task_handlers,
        "resolve_provider_effective_auth_source",
        lambda provider: "system_override" if provider == "claude" else "none",
    )

    service = AgentTaskService()
    created = service.create_project(name='MCP Claude Reroute Project')

    with SessionLocal() as db:
        resolved_assignee = task_handlers._resolve_available_system_bot_assignee_for_project(
            db,
            project_id=created['id'],
            requested_assignee_id=CODEX_SYSTEM_USER_ID,
            assigned_agent_code='dev-a',
        )

    assert resolved_assignee == CLAUDE_SYSTEM_USER_ID


def test_agent_service_update_project_can_toggle_event_storming(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})

    service = AgentTaskService()
    created = service.create_project(name='MCP Patch Event Storming')
    assert created['event_storming_enabled'] is True

    patched = service.update_project(
        project_id=created['id'],
        patch={'event_storming_enabled': False},
    )
    assert patched['id'] == created['id']
    assert patched['event_storming_enabled'] is False


def test_agent_service_verify_team_mode_workflow_uses_core_checks_without_legacy_oversight_guard(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    dev1 = team["dev1"]
    dev2 = team["dev2"]
    qa = team["qa"]
    lead = team["lead"]

    d1 = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer A",
            "status": "In Progress",
            "assignee_id": dev1,
            "assigned_agent_code": "dev-a",
            "instruction": "Implement and hand off for Lead review.",
            "task_relationships": [{"kind": "delivers_to", "task_ids": [], "statuses": ["Awaiting decision"]}],
        },
    )
    assert d1.status_code == 200
    d2 = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer B",
            "status": "In Progress",
            "assignee_id": dev2,
            "assigned_agent_code": "dev-b",
            "instruction": "Implement and hand off for Lead review.",
            "task_relationships": [{"kind": "delivers_to", "task_ids": [], "statuses": ["Awaiting decision"]}],
        },
    )
    assert d2.status_code == 200

    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA task",
            "status": "In Progress",
            "assignee_id": qa,
            "assigned_agent_code": "qa-a",
            "instruction": "Run QA validation before completion.",
            "task_relationships": [{"kind": "hands_off_to", "task_ids": [], "statuses": ["Completed"]}],
        },
    )
    assert qa_task.status_code == 200

    lead_oversight = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead oversight cadence",
            "status": "Completed",
            "assignee_id": lead,
            "assigned_agent_code": "lead-a",
            "instruction": "Lead review and deploy readiness cadence for constructos-ws-default on port 6768.",
            "execution_triggers": [
                {
                    "kind": "schedule",
                    "scheduled_at_utc": "2026-03-02T00:00:00Z",
                    "recurring_rule": "every:5m",
                    "run_on_statuses": ["Awaiting decision"],
                },
            ],
            "task_relationships": [
                {"kind": "depends_on", "task_ids": [d1.json()["id"], d2.json()["id"]], "statuses": ["Completed"]},
                {"kind": "depends_on", "task_ids": [d1.json()["id"], d2.json()["id"], qa_task.json()["id"]], "statuses": ["Blocked"]},
            ],
        },
    )
    assert lead_oversight.status_code == 200
    patched_d1 = client.patch(
        f"/api/tasks/{d1.json()['id']}",
        json={
            "task_relationships": [
                {
                    "kind": "delivers_to",
                    "task_ids": [lead_oversight.json()["id"]],
                    "statuses": ["Awaiting decision"],
                }
            ]
        },
    )
    assert patched_d1.status_code == 200
    patched_d2 = client.patch(
        f"/api/tasks/{d2.json()['id']}",
        json={
            "task_relationships": [
                {
                    "kind": "delivers_to",
                    "task_ids": [lead_oversight.json()["id"]],
                    "statuses": ["Awaiting decision"],
                }
            ]
        },
    )
    assert patched_d2.status_code == 200
    patched_qa = client.patch(
        f"/api/tasks/{qa_task.json()['id']}",
        json={
            "task_relationships": [
                {
                    "kind": "hands_off_to",
                    "task_ids": [lead_oversight.json()["id"]],
                    "statuses": ["Completed"],
                }
            ]
        },
    )
    assert patched_qa.status_code == 200

    service = AgentTaskService()
    verification = service.verify_team_mode_workflow(
        project_id=project_id,
        workspace_id=ws_id,
    )
    assert verification["checks"]["role_coverage_present"] is True
    assert verification["checks"]["single_lead_present"] is True
    assert verification["checks"]["human_owner_present"] is True
    assert verification["checks"]["status_semantics_present"] is True
    assert "lead_oversight_not_done_before_delivery_complete" not in verification["checks"]
    assert "lead_oversight_not_done_before_delivery_complete" not in verification["required_failed_checks"]
    assert verification["ok"] is True


def test_team_mode_qa_task_completed_transition_is_blocked_until_delivery_prereqs_pass(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    dev = team["dev1"]
    qa = team["qa"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Dev open task",
            "status": "In Progress",
            "assignee_id": dev,
            "assigned_agent_code": "dev-a",
            "instruction": "Implement scope",
        },
    )
    assert dev_task.status_code == 200

    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA handoff task",
            "status": "In Progress",
            "assignee_id": qa,
            "assigned_agent_code": "qa-a",
            "instruction": "Validate implementation",
        },
    )
    assert qa_task.status_code == 200

    blocked = client.post(f"/api/tasks/{qa_task.json()['id']}/complete")
    assert blocked.status_code in {400, 409}
    assert "QA Completed transition blocked by Team Mode closeout guards" in str(blocked.json().get("detail") or "")


def test_runner_completes_deployable_task_after_successful_qa_handoff(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    qa = team["qa"]

    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA validation task",
            "status": "In Progress",
            "assignee_id": qa,
            "assigned_agent_code": "qa-a",
            "instruction": "Validate deployed runtime",
            "delivery_mode": "deployable_slice",
            "external_refs": [
                {"url": "merge:main:abc123", "title": "merged to main"},
                {"url": "deploy:stack:constructos-ws-default", "title": "deploy stack"},
                {"url": "deploy:command:docker compose -p constructos-ws-default up -d", "title": "deploy command"},
                {"url": "deploy:compose:docker-compose.yml", "title": "deploy compose manifest"},
                {"url": "deploy:runtime:static_web", "title": "deploy runtime decision"},
                {"url": "deploy:health:http://gateway:6768/health:http_200", "title": "deploy health: pass"},
            ],
        },
    )
    assert qa_task.status_code == 200
    qa_task_id = qa_task.json()["id"]

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead deploy handoff source",
            "status": "In Progress",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Lead deploy handoff source",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    handoff_at = datetime.now(timezone.utc).isoformat()
    from shared.models import SessionLocal

    with SessionLocal() as db:
        from shared.eventing import append_event
        from features.tasks.domain import EVENT_UPDATED as TASK_EVENT_UPDATED, EVENT_AUTOMATION_REQUESTED

        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=qa_task_id,
            event_type=TASK_EVENT_UPDATED,
            payload={
                "last_requested_source": "lead_handoff",
                "last_requested_source_task_id": lead_task_id,
                "last_requested_reason": "lead_handoff",
                "last_requested_workflow_scope": "team_mode",
                "last_requested_correlation_id": f"lead:{lead_task_id}:{handoff_at}",
                "last_requested_trigger_task_id": lead_task_id,
                "last_requested_from_status": "In Progress",
                "last_requested_to_status": "In Progress",
                "last_requested_triggered_at": handoff_at,
                "last_lead_handoff_token": f"lead:{lead_task_id}:{handoff_at}",
                "last_lead_handoff_at": handoff_at,
                "last_lead_handoff_refs_json": [],
                "last_lead_handoff_deploy_execution": {
                    "executed_at": handoff_at,
                    "stack": "constructos-ws-default",
                    "port": 6768,
                    "health_path": "/health",
                    "command": "docker compose -p constructos-ws-default up -d",
                    "manifest_path": "docker-compose.yml",
                    "runtime_type": "static_web",
                    "runtime_ok": True,
                    "http_url": "http://gateway:6768/health",
                    "http_status": 200,
                },
                "team_mode_phase": "qa_validation",
            },
            metadata={
                "actor_id": bootstrap["current_user"]["id"],
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": qa_task_id,
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=qa_task_id,
            event_type=EVENT_AUTOMATION_REQUESTED,
            payload={
                "requested_at": handoff_at,
                "instruction": "Validate deployed runtime",
                "source": "lead_handoff",
                "source_task_id": lead_task_id,
                "reason": "lead_handoff",
                "workflow_scope": "team_mode",
                "correlation_id": f"lead:{lead_task_id}:{handoff_at}",
                "trigger_task_id": lead_task_id,
                "from_status": "In Progress",
                "to_status": "In Progress",
                "triggered_at": handoff_at,
                "lead_handoff_token": f"lead:{lead_task_id}:{handoff_at}",
                "lead_handoff_at": handoff_at,
                "lead_handoff_refs": [],
                "lead_handoff_deploy_execution": {
                    "executed_at": handoff_at,
                    "stack": "constructos-ws-default",
                    "port": 6768,
                    "health_path": "/health",
                    "command": "docker compose -p constructos-ws-default up -d",
                    "manifest_path": "docker-compose.yml",
                    "runtime_type": "static_web",
                    "runtime_ok": True,
                    "http_url": "http://gateway:6768/health",
                    "http_status": 200,
                },
            },
            metadata={
                "actor_id": bootstrap["current_user"]["id"],
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": qa_task_id,
            },
        )
        db.commit()

    from features.agents.executor import AutomationOutcome
    from features.agents.runner import QueuedAutomationRun, _record_automation_success

    _record_automation_success(
        QueuedAutomationRun(
            task_id=qa_task_id,
            workspace_id=ws_id,
            project_id=project_id,
            title="QA validation task",
            description="",
            status="In Progress",
            instruction="Validate deployed runtime",
            request_source="lead_handoff",
            is_scheduled_run=False,
            trigger_task_id=lead_task_id,
            trigger_from_status="In Progress",
            trigger_to_status="In Progress",
            triggered_at=handoff_at,
            actor_user_id=bootstrap["current_user"]["id"],
            workflow_scope="team_mode",
            execution_mode="resume_execution",
        ),
        outcome=AutomationOutcome(
            action="comment",
            summary="QA verification passed",
            comment="Verification: PASS",
            usage=None,
        ),
    )

    payload = client.get(f"/api/tasks/{qa_task_id}").json()
    assert payload["status"] == "Completed"

    automation_payload = client.get(f"/api/tasks/{qa_task_id}/automation").json()
    assert automation_payload["team_mode_phase"] == "completed"


def test_team_mode_completed_transition_uses_assigned_agent_code_when_member_role_is_generic(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from shared.models import ProjectMember, SessionLocal, User, WorkspaceMember

    generic_user_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(
            User(
                id=generic_user_id,
                username="generic-team-mode-user",
                full_name="Generic Team Mode User",
                user_type="agent",
                password_hash=None,
                must_change_password=False,
                is_active=True,
            )
        )
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws_id, user_id=generic_user_id, role="Member"))
        db.add(
            ProjectMember(
                workspace_id=ws_id,
                project_id=project_id,
                user_id=generic_user_id,
                role="Contributor",
            )
        )
        db.commit()

    _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA generic member role",
            "status": "In Progress",
            "assignee_id": generic_user_id,
            "assigned_agent_code": "qa-a",
            "instruction": "Validate implementation",
        },
    )
    assert qa_task.status_code == 200

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead generic member role",
            "status": "Awaiting decision",
            "assignee_id": generic_user_id,
            "assigned_agent_code": "lead-a",
            "instruction": "Coordinate delivery handoff",
        },
    )
    assert lead_task.status_code == 200

    qa_blocked = client.post(f"/api/tasks/{qa_task.json()['id']}/complete")
    assert qa_blocked.status_code in {400, 409}
    assert "QA Completed transition blocked by Team Mode closeout guards" in str(qa_blocked.json().get("detail") or "")

    lead_blocked = client.post(f"/api/tasks/{lead_task.json()['id']}/complete")
    assert lead_blocked.status_code in {400, 409}
    assert "Lead Completed transition blocked" in str(lead_blocked.json().get("detail") or "")


def test_team_mode_lead_done_transition_requires_runtime_deploy_health_ok(monkeypatch):
    from fastapi import HTTPException
    from plugins.team_mode import service_policy as policy

    class _State:
        project_id = "project-1"
        workspace_id = "workspace-1"

    monkeypatch.setattr(policy, "project_has_team_mode_enabled", lambda **_: True)
    monkeypatch.setattr(policy, "open_developer_tasks", lambda **_: [])

    def _verify_delivery_workflow_fn(**_: object) -> dict[str, object]:
        return {
            "checks": {
                "repo_context_present": True,
                "git_contract_ok": True,
                "compose_manifest_present": True,
                "lead_deploy_decision_evidence_present": True,
                "qa_handoff_current_cycle_ok": True,
                "deploy_serves_application_root": True,
                "qa_has_verifiable_artifacts": True,
                "deploy_execution_evidence_present": True,
                "runtime_deploy_health_ok": False,
            }
        }

    with pytest.raises(HTTPException) as exc_info:
        policy.enforce_done_transition(
            db=None,
            state=_State(),
            assignee_role="Lead",
            verify_delivery_workflow_fn=_verify_delivery_workflow_fn,
            auth_token=None,
        )

    assert "runtime_deploy_health_ok" in str(exc_info.value.detail)


def test_team_mode_lead_task_completed_transition_is_blocked_until_dev_tasks_done(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    dev = team["dev1"]
    lead = team["lead"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Dev open task",
            "status": "In Progress",
            "assignee_id": dev,
            "assigned_agent_code": "dev-a",
            "instruction": "Implement scope",
        },
    )
    assert dev_task.status_code == 200

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead oversight task",
            "status": "Awaiting decision",
            "assignee_id": lead,
            "assigned_agent_code": "lead-a",
            "instruction": "Coordinate team",
        },
    )
    assert lead_task.status_code == 200

    blocked = client.post(f"/api/tasks/{lead_task.json()['id']}/complete")
    assert blocked.status_code in {400, 409}
    assert "Lead Completed transition blocked: open implementation tasks remain" in str(blocked.json().get("detail") or "")


def test_agent_service_verify_delivery_workflow_requires_commit_and_qa_evidence(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})
    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path / "workspace"))

    # Ensure repo context exists for git contract checks.
    patched_project = client.patch(
        f"/api/projects/{project_id}",
        json={
            "external_refs": [{"url": "https://github.com/example/delivery-demo", "title": "Repo"}],
        },
    )
    assert patched_project.status_code == 200
    project_name = str(patched_project.json().get("name") or "")

    service = AgentTaskService()
    service.archive_all_tasks(workspace_id=ws_id, project_id=project_id)
    service.set_project_plugin_enabled(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="team_mode",
        enabled=True,
    )
    service.set_project_plugin_enabled(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="git_delivery",
        enabled=True,
    )
    team = _ensure_team_mode_member_roles(workspace_id=ws_id, project_id=project_id)
    default_assignee = team["dev1"]
    qa_assignee = team["qa"]
    lead_assignee = team["lead"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer with commit evidence",
            "status": "In Progress",
            "assignee_id": default_assignee,
            "assigned_agent_code": "dev-a",
        },
    )
    assert dev_task.status_code == 200
    qa_task = client.post(
        "/api/tasks",
        json={
                "workspace_id": ws_id,
                "project_id": project_id,
                "title": "QA with artifacts",
                "status": "In Progress",
                "assignee_id": qa_assignee,
                "assigned_agent_code": "qa-a",
            },
        )
    assert qa_task.status_code == 200
    deploy_task = client.post(
        "/api/tasks",
        json={
                "workspace_id": ws_id,
                "project_id": project_id,
                "title": "Deploy app with Docker Compose",
                "status": "Awaiting decision",
                "assignee_id": lead_assignee,
                "assigned_agent_code": "lead-a",
            },
        )
    assert deploy_task.status_code == 200

    service = AgentTaskService()
    failed = service.verify_delivery_workflow(project_id=project_id, workspace_id=ws_id)
    assert failed["checks"]["repo_context_present"] is True
    assert failed["checks"]["git_contract_ok"] is False
    assert failed["checks"]["qa_has_verifiable_artifacts"] is False
    assert isinstance(failed["checks"]["deploy_execution_evidence_present"], bool)
    assert failed["ok"] is False

    dev_note = client.post(
        "/api/notes",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "task_id": dev_task.json()["id"],
            "title": "Commit evidence",
            "body": f"Implemented in commit a1b2c3d4 with branch task/{dev_task.json()['id'][:8]}-dev-evidence.",
            "external_refs": [
                {"url": "commit:a1b2c3d4", "title": "Dev commit"},
                {"url": f"branch:task/{dev_task.json()['id'][:8]}-dev-evidence", "title": "Task branch"},
            ],
        },
    )
    assert dev_note.status_code == 200
    qa_note = client.post(
        "/api/notes",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "task_id": qa_task.json()["id"],
            "title": "QA Report",
            "body": "Pytest report attached. All smoke tests passed.",
            "external_refs": [{"url": "https://example.com/qa/report/1", "title": "QA report"}],
        },
    )
    assert qa_note.status_code == 200
    deploy_note = client.post(
        "/api/notes",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "task_id": deploy_task.json()["id"],
            "title": "Deploy execution",
            "body": "Ran docker compose up -d and verified http://localhost:6768/health status 200. Service is running.",
            "external_refs": [
                {"url": "https://example.com/deploy/run/1", "title": "Deploy verification"},
                {"url": "deploy:runtime:static_assets", "title": "Runtime decision"},
                {"url": "deploy:compose:docker-compose.yml", "title": "Compose manifest"},
                {"url": "deploy:command:docker compose -p constructos-ws-default up -d", "title": "Deploy command"},
                {"url": "deploy:health:http://gateway:6768/health:http_200", "title": "Health probe"},
            ],
        },
    )
    assert deploy_note.status_code == 200

    from shared.project_repository import resolve_project_repository_path

    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "docker-compose.yml").write_text(
        "services:\n"
        "  web:\n"
        "    image: nginx:alpine\n"
        "    ports:\n"
        "      - \"6768:80\"\n",
        encoding="utf-8",
    )

    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    completed_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        for task_id in (dev_task.json()["id"], qa_task.json()["id"], deploy_task.json()["id"]):
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=task_id,
                event_type="TaskAutomationCompleted",
                payload={"completed_at": completed_at},
                metadata={
                    "actor_id": AGENT_SYSTEM_USER_ID,
                    "workspace_id": ws_id,
                    "project_id": project_id,
                    "task_id": task_id,
                },
            )
        db.commit()

    passed = service.verify_delivery_workflow(project_id=project_id, workspace_id=ws_id)
    assert passed["checks"]["repo_context_present"] is True
    assert passed["checks"]["git_contract_ok"] is True
    assert passed["checks"]["qa_has_verifiable_artifacts"] is True
    assert passed["checks"]["deploy_execution_evidence_present"] is True
    assert passed["ok"] is True


def test_agent_service_verify_delivery_workflow_rejects_duplicate_commit_evidence_across_dev_tasks(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})
    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path / "workspace"))

    patched_project = client.patch(
        f"/api/projects/{project_id}",
        json={
            "external_refs": [{"url": "https://github.com/example/delivery-demo", "title": "Repo"}],
        },
    )
    assert patched_project.status_code == 200
    project_name = str(patched_project.json().get("name") or "")
    project_name = str(patched_project.json().get("name") or "")

    service = AgentTaskService()
    service.archive_all_tasks(workspace_id=ws_id, project_id=project_id)
    service.set_project_plugin_enabled(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="team_mode",
        enabled=True,
    )
    service.set_project_plugin_enabled(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="git_delivery",
        enabled=True,
    )

    team = _ensure_team_mode_member_roles(workspace_id=ws_id, project_id=project_id)
    dev1 = team["dev1"]
    dev2 = team["dev2"]
    qa = team["qa"]
    lead = team["lead"]

    dev_task_1 = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer task 1",
            "status": "In Progress",
            "assignee_id": dev1,
            "assigned_agent_code": "dev-a",
            "external_refs": [{"url": "commit:abc1234"}],
        },
    )
    assert dev_task_1.status_code == 200
    dev_task_2 = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer task 2",
            "status": "In Progress",
            "assignee_id": dev2,
            "assigned_agent_code": "dev-b",
            "external_refs": [{"url": "commit:abc1234"}],
        },
    )
    assert dev_task_2.status_code == 200
    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA task",
            "status": "In Progress",
            "assignee_id": qa,
            "assigned_agent_code": "qa-a",
        },
    )
    assert qa_task.status_code == 200
    deploy_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Deploy app with Docker Compose",
            "status": "Awaiting decision",
            "assignee_id": lead,
            "assigned_agent_code": "lead-a",
        },
    )
    assert deploy_task.status_code == 200

    qa_note = client.post(
        "/api/notes",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "task_id": qa_task.json()["id"],
            "title": "QA report",
            "body": "Pytest run passed with smoke log attached.",
            "external_refs": [{"url": "https://example.com/qa/report/2", "title": "QA report"}],
        },
    )
    assert qa_note.status_code == 200
    dev1_branch_note = client.post(
        "/api/notes",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "task_id": dev_task_1.json()["id"],
            "title": "Dev task 1 branch",
            "body": f"Implementation branch: task/{dev_task_1.json()['id'][:8]}-task-1",
            "external_refs": [{"url": f"branch:task/{dev_task_1.json()['id'][:8]}-task-1", "title": "Task branch"}],
        },
    )
    assert dev1_branch_note.status_code == 200
    dev2_branch_note = client.post(
        "/api/notes",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "task_id": dev_task_2.json()["id"],
            "title": "Dev task 2 branch",
            "body": f"Implementation branch: task/{dev_task_2.json()['id'][:8]}-task-2",
            "external_refs": [{"url": f"branch:task/{dev_task_2.json()['id'][:8]}-task-2", "title": "Task branch"}],
        },
    )
    assert dev2_branch_note.status_code == 200
    deploy_note = client.post(
        "/api/notes",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "task_id": deploy_task.json()["id"],
            "title": "Deploy execution",
            "body": "Deploy completed via docker compose and /health returned status 200.",
            "external_refs": [
                {"url": "https://example.com/deploy/run/2", "title": "Deploy verification"},
                {"url": "deploy:runtime:static_assets", "title": "Runtime decision"},
                {"url": "deploy:compose:docker-compose.yml", "title": "Compose manifest"},
                {"url": "deploy:command:docker compose -p constructos-ws-default up -d", "title": "Deploy command"},
                {"url": "deploy:health:http://gateway:6768/health:http_200", "title": "Health probe"},
            ],
        },
    )
    assert deploy_note.status_code == 200

    from shared.project_repository import resolve_project_repository_path

    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "docker-compose.yml").write_text(
        "services:\n"
        "  web:\n"
        "    image: nginx:alpine\n"
        "    ports:\n"
        "      - \"6768:80\"\n",
        encoding="utf-8",
    )

    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    completed_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        for task_id in (dev_task_1.json()["id"], dev_task_2.json()["id"], qa_task.json()["id"], deploy_task.json()["id"]):
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=task_id,
                event_type="TaskAutomationCompleted",
                payload={"completed_at": completed_at},
                metadata={
                    "actor_id": AGENT_SYSTEM_USER_ID,
                    "workspace_id": ws_id,
                    "project_id": project_id,
                    "task_id": task_id,
                },
            )
        db.commit()

    service = AgentTaskService()
    verification = service.verify_delivery_workflow(project_id=project_id, workspace_id=ws_id)
    assert verification["checks"]["git_contract_ok"] is True
    assert verification["checks"]["qa_has_verifiable_artifacts"] is True
    assert verification["checks"]["deploy_execution_evidence_present"] is True
    assert verification["ok"] is True


def test_verify_delivery_workflow_accepts_structured_lead_deploy_snapshot(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})
    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path / "workspace"))

    patched_project = client.patch(
        f"/api/projects/{project_id}",
        json={
            "external_refs": [{"url": "https://github.com/example/delivery-demo", "title": "Repo"}],
        },
    )
    assert patched_project.status_code == 200
    project_name = str(patched_project.json().get("name") or "")

    service = AgentTaskService()
    service.archive_all_tasks(workspace_id=ws_id, project_id=project_id)
    service.set_project_plugin_enabled(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="team_mode",
        enabled=True,
    )
    service.set_project_plugin_enabled(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="git_delivery",
        enabled=True,
    )

    team = _ensure_team_mode_member_roles(workspace_id=ws_id, project_id=project_id)
    dev_assignee = team["dev1"]
    qa_assignee = team["qa"]
    lead_assignee = team["lead"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer delivery",
            "status": "In Progress",
            "assignee_id": dev_assignee,
            "assigned_agent_code": "dev-a",
            "external_refs": [
                {"url": "commit:abc1234", "title": "Commit"},
                {"url": "branch:task/abcdefgh-implementation", "title": "Task branch"},
            ],
        },
    )
    assert dev_task.status_code == 200
    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA report",
            "status": "In Progress",
            "assignee_id": qa_assignee,
            "assigned_agent_code": "qa-a",
            "external_refs": [{"url": "https://example.com/qa/report/structured", "title": "QA report"}],
        },
    )
    assert qa_task.status_code == 200
    deploy_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead deploy cycle",
            "status": "Awaiting decision",
            "assignee_id": lead_assignee,
            "assigned_agent_code": "lead-a",
            "external_refs": [],
        },
    )
    assert deploy_task.status_code == 200

    completed_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=deploy_task.json()["id"],
            event_type="TaskUpdated",
            payload={
                "last_deploy_execution": {
                    "executed_at": completed_at,
                    "stack": "constructos-ws-default",
                    "port": 6768,
                    "health_path": "/health",
                    "command": "docker compose -p constructos-ws-default up -d",
                    "manifest_path": "docker-compose.yml",
                    "runtime_type": "dockerfile_build",
                    "runtime_ok": True,
                    "http_url": "http://gateway:6768/health",
                    "http_status": 200,
                    "synthesized": False,
                    "synthesized_files": [],
                    "synthesis_commit_sha": None,
                }
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": deploy_task.json()["id"],
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=qa_task.json()["id"],
            event_type="TaskUpdated",
            payload={
                "last_requested_source": "lead_handoff",
                "last_requested_source_task_id": deploy_task.json()["id"],
                "last_requested_reason": "lead_handoff",
                "last_requested_workflow_scope": "team_mode",
                "last_requested_correlation_id": f"lead:{deploy_task.json()['id']}:{completed_at}",
                "last_requested_trigger_task_id": deploy_task.json()["id"],
                "last_requested_from_status": "In Progress",
                "last_requested_to_status": "In Progress",
                "last_requested_triggered_at": completed_at,
                "last_lead_handoff_token": f"lead:{deploy_task.json()['id']}:{completed_at}",
                "last_lead_handoff_at": completed_at,
                "last_lead_handoff_refs_json": [],
                "last_lead_handoff_deploy_execution": {
                    "executed_at": completed_at,
                    "stack": "constructos-ws-default",
                    "port": 6768,
                    "health_path": "/health",
                    "command": "docker compose -p constructos-ws-default up -d",
                    "manifest_path": "docker-compose.yml",
                    "runtime_type": "dockerfile_build",
                    "runtime_ok": True,
                    "http_url": "http://gateway:6768/health",
                    "http_status": 200,
                },
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": qa_task.json()["id"],
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=qa_task.json()["id"],
            event_type="TaskAutomationRequested",
            payload={
                "requested_at": completed_at,
                "instruction": "Run QA checks.",
                "source": "lead_handoff",
                "source_task_id": deploy_task.json()["id"],
                "reason": "lead_handoff",
                "workflow_scope": "team_mode",
                "trigger_link": f"{deploy_task.json()['id']}->{qa_task.json()['id']}:QA",
                "correlation_id": f"lead:{deploy_task.json()['id']}:{completed_at}",
                "trigger_task_id": deploy_task.json()["id"],
                "from_status": "In Progress",
                "to_status": "In Progress",
                "triggered_at": completed_at,
                "lead_handoff_token": f"lead:{deploy_task.json()['id']}:{completed_at}",
                "lead_handoff_at": completed_at,
                "lead_handoff_refs": [],
                "lead_handoff_deploy_execution": {
                    "executed_at": completed_at,
                    "stack": "constructos-ws-default",
                    "port": 6768,
                    "health_path": "/health",
                },
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": qa_task.json()["id"],
            },
        )
        for task_id in (dev_task.json()["id"], qa_task.json()["id"], deploy_task.json()["id"]):
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=task_id,
                event_type="TaskAutomationCompleted",
                payload={"completed_at": completed_at},
                metadata={
                    "actor_id": AGENT_SYSTEM_USER_ID,
                    "workspace_id": ws_id,
                    "project_id": project_id,
                    "task_id": task_id,
                },
            )
        db.commit()

    from shared.project_repository import resolve_project_repository_path

    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "docker-compose.yml").write_text(
        "services:\n"
        "  web:\n"
        "    build: .\n"
        "    ports:\n"
        "      - \"6768:80\"\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        AgentTaskService,
        "_run_runtime_deploy_health_check",
        staticmethod(
            lambda **_: {
                "stack": "constructos-ws-default",
                "port": 6768,
                "health_path": "/health",
                "stack_running": True,
                "port_mapped": True,
                "http_200": True,
                "serves_application_root": True,
                "ok": True,
                "error": None,
            }
        ),
    )

    configured = service.apply_project_plugin_config(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="git_delivery",
        enabled=True,
        config={
            "required_checks": {
                "delivery": [
                    "repo_context_present",
                    "git_contract_ok",
                    "qa_has_verifiable_artifacts",
                    "lead_deploy_decision_evidence_present",
                    "deploy_execution_evidence_present",
                    "runtime_deploy_health_ok",
                ]
            },
        },
    )
    assert configured["enabled"] is True
    docker_configured = service.apply_project_plugin_config(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="docker_compose",
        enabled=True,
        config={
            "runtime_deploy_health": {
                "required": True,
                "stack": "constructos-ws-default",
                "port": 6768,
                "health_path": "/health",
                "require_http_200": True,
            },
        },
    )
    assert docker_configured["enabled"] is True

    verification = service.verify_delivery_workflow(project_id=project_id, workspace_id=ws_id)
    assert "compose_manifest_present" in verification["required_checks"]
    assert verification["checks"]["compose_manifest_present"] is True
    assert verification["checks"]["lead_deploy_decision_evidence_present"] is True
    assert verification["checks"]["deploy_execution_evidence_present"] is True
    assert verification["checks"]["runtime_deploy_health_ok"] is True


def test_verify_delivery_workflow_accepts_legacy_lead_deploy_evidence(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    from shared.project_repository import resolve_project_repository_path

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})
    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path / "workspace"))

    patched_project = client.patch(
        f"/api/projects/{project_id}",
        json={
            "name": "Legacy Delivery Demo",
            "external_refs": [{"url": "https://github.com/example/delivery-demo", "title": "Repo"}],
        },
    )
    assert patched_project.status_code == 200
    project_name = str(patched_project.json().get("name") or "")

    service = AgentTaskService()
    service.archive_all_tasks(workspace_id=ws_id, project_id=project_id)
    service.set_project_plugin_enabled(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="team_mode",
        enabled=True,
    )
    service.set_project_plugin_enabled(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="git_delivery",
        enabled=True,
    )
    service.apply_project_plugin_config(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="git_delivery",
        enabled=True,
        config={
            "required_checks": {
                "delivery": [
                    "repo_context_present",
                    "git_contract_ok",
                ]
            },
        },
    )

    team = _ensure_team_mode_member_roles(workspace_id=ws_id, project_id=project_id)
    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer delivery",
            "status": "In Progress",
            "assignee_id": team["dev1"],
            "external_refs": [
                {"url": "commit:abc1234", "title": "Commit"},
                {"url": "branch:task/abcdefgh-implementation", "title": "Task branch"},
            ],
        },
    )
    assert dev_task.status_code == 200
    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA report",
            "status": "In Progress",
            "assignee_id": team["qa"],
            "assigned_agent_code": "qa-a",
            "external_refs": [{"url": "https://example.com/qa/report/legacy", "title": "QA report"}],
        },
    )
    assert qa_task.status_code == 200
    deploy_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead deploy cycle",
            "status": "Awaiting decision",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "external_refs": [
                {"url": "file:/home/app/workspace/.constructos/repos/legacy-delivery-demo/docker-compose.yml", "title": "Compose manifest path"},
                {"url": "decision:runtime_signal_static_assets_index_html", "title": "Runtime decision"},
                {"url": "command:docker compose -p constructos-ws-default up -d --build:success", "title": "Deploy command"},
                {"url": "probe:postdeploy:http://gateway:6768/health:http_200", "title": "Post-deploy health probe"},
            ],
        },
    )
    assert deploy_task.status_code == 200

    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "docker-compose.yml").write_text(
        "services:\n"
        "  web:\n"
        "    image: nginx:alpine\n"
        "    ports:\n"
        "      - \"6768:80\"\n",
        encoding="utf-8",
    )

    verification = service.verify_delivery_workflow(project_id=project_id, workspace_id=ws_id)
    assert "compose_manifest_present" in verification["required_checks"]
    assert verification["checks"]["compose_manifest_present"] is True
    assert verification["checks"]["lead_deploy_decision_evidence_present"] is True
    assert verification["checks"]["deploy_execution_evidence_present"] is True
    assert verification["ok"] is True


def test_task_automation_read_model_derives_deploy_snapshot_from_refs(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead deploy evidence task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'external_refs': [
                {'url': 'deploy:compose:docker-compose.yml', 'title': 'Compose manifest'},
                {'url': 'deploy:runtime:static_assets', 'title': 'Runtime decision'},
                {'url': 'deploy:command:docker compose -p constructos-ws-default up -d', 'title': 'Deploy command'},
                {'url': 'deploy:health:http://gateway:6768/health:http_200', 'title': 'Health probe'},
            ],
        },
    )
    assert task.status_code == 200

    status = client.get(f"/api/tasks/{task.json()['id']}/automation")
    assert status.status_code == 200
    payload = status.json()
    deploy_snapshot = payload.get('last_deploy_execution') or {}
    assert deploy_snapshot.get('manifest_path') == 'docker-compose.yml'
    assert deploy_snapshot.get('runtime_type') == 'static_assets'
    assert deploy_snapshot.get('stack') == 'constructos-ws-default'
    assert deploy_snapshot.get('runtime_ok') is True
    assert deploy_snapshot.get('http_status') == 200


def test_verify_delivery_workflow_accepts_direct_runner_health_refs(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    from shared.project_repository import resolve_project_repository_path

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})
    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path / "workspace"))

    patched_project = client.patch(
        f"/api/projects/{project_id}",
        json={
            "name": "Direct Health Ref Delivery Demo",
            "external_refs": [{"url": "https://github.com/example/direct-health-demo", "title": "Repo"}],
        },
    )
    assert patched_project.status_code == 200
    project_name = str(patched_project.json().get("name") or "")

    service = AgentTaskService()
    service.archive_all_tasks(workspace_id=ws_id, project_id=project_id)
    team = _ensure_team_mode_member_roles(workspace_id=ws_id, project_id=project_id)

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer delivery",
            "status": "In Progress",
            "assignee_id": team["dev1"],
            "external_refs": [
                {"url": "commit:abc1234", "title": "Commit"},
                {"url": "branch:task/abcdefgh-implementation", "title": "Task branch"},
            ],
        },
    )
    assert dev_task.status_code == 200
    deploy_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead deploy cycle",
            "status": "Awaiting decision",
            "assignee_id": team["lead"],
            "external_refs": [
                {"url": "file:/home/app/workspace/.constructos/repos/direct-health-ref-delivery-demo/docker-compose.yml", "title": "Compose manifest path"},
                {"url": "decision:runtime_signal_static_assets_index_html", "title": "Runtime decision"},
                {"url": "command:docker compose -p constructos-ws-default up -d --build:success", "title": "Deploy command"},
                {"url": "http://gateway:6768/health#post-deploy-http-200-2026-03-10T15:09:54Z", "title": "Deploy health: pass"},
            ],
        },
    )
    assert deploy_task.status_code == 200

    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "docker-compose.yml").write_text(
        "services:\n"
        "  web:\n"
        "    image: nginx:alpine\n"
        "    ports:\n"
        "      - \"6768:80\"\n",
        encoding="utf-8",
    )

    verification = service.verify_delivery_workflow(project_id=project_id, workspace_id=ws_id)
    assert verification["checks"]["lead_deploy_decision_evidence_present"] is True
    assert verification["checks"]["deploy_execution_evidence_present"] is True


def test_project_task_dependency_graph_includes_structural_trigger_and_runtime_channels(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    project = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Task Flow Demo',
            'description': 'Task dependency graph demo.',
        },
    )
    assert project.status_code == 200
    project_id = project.json()['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    dev_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Developer implementation',
            'status': 'In Progress',
            'assignee_id': team['dev1'],
            'assigned_agent_code': 'dev-a',
            'instruction': 'Implement the feature.',
            'task_relationships': [
                {'kind': 'delivers_to', 'task_ids': []},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    lead_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Lead integration',
            'status': 'Awaiting decision',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Merge and deploy.',
            'task_relationships': [
                {'kind': 'depends_on', 'task_ids': [dev_task_id], 'statuses': ['Completed']},
            ],
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    patched_dev = client.patch(
        f'/api/tasks/{dev_task_id}',
        json={
            'task_relationships': [
                {'kind': 'delivers_to', 'task_ids': [lead_task_id]},
            ],
        },
    )
    assert patched_dev.status_code == 200

    qa_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'QA validation',
            'status': 'In Progress',
            'assignee_id': team['qa'],
            'assigned_agent_code': 'qa-a',
            'instruction': 'Run QA checks.',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'scope': 'external',
                    'selector': {'task_ids': [lead_task_id]},
                    'to_statuses': ['Done'],
                }
            ],
            'task_relationships': [
                {'kind': 'hands_off_to', 'task_ids': [lead_task_id]},
            ],
        },
    )
    assert qa_task.status_code == 200
    qa_task_id = qa_task.json()['id']

    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=lead_task_id,
            event_type='TaskAutomationRequested',
            payload={
                'requested_at': '2026-03-10T15:50:00Z',
                'instruction': 'Run Lead cycle.',
                'source': 'runner_orchestrator',
                'source_task_id': dev_task_id,
                'reason': 'developer_handoff',
                'trigger_link': f'{dev_task_id}->{lead_task_id}:Awaiting decision',
                'correlation_id': 'run-1',
            },
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': lead_task_id},
        )
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=qa_task_id,
            event_type='TaskAutomationRequested',
            payload={
                'requested_at': '2026-03-10T15:55:00Z',
                'instruction': 'Run QA checks.',
                'source': 'lead_handoff',
                'source_task_id': lead_task_id,
                'reason': 'lead_handoff',
                'workflow_scope': 'team_mode',
                'trigger_link': f'{lead_task_id}->{qa_task_id}:QA',
                'correlation_id': 'lead-handoff-1',
            },
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': qa_task_id},
        )
        db.commit()

    graph_res = client.get(f'/api/projects/{project_id}/task-dependency-graph')
    assert graph_res.status_code == 200
    payload = graph_res.json()

    assert payload['project_id'] == project_id
    assert payload['node_count'] == 3
    assert payload['counts']['structural_edges'] >= 2
    assert payload['counts']['status_trigger_edges'] >= 1
    assert payload['counts']['runtime_edges'] >= 2

    edge_map = {
        (str(item.get('source_entity_id') or ''), str(item.get('target_entity_id') or '')): item
        for item in (payload.get('edges') or [])
    }
    dev_to_lead = edge_map[(dev_task_id, lead_task_id)]
    assert dev_to_lead['structural'] is True
    assert dev_to_lead['runtime_dependency'] is True
    assert dev_to_lead['runtime_requests_total'] >= 1
    assert any(str(channel.get('kind') or '') == 'relationship' for channel in (dev_to_lead.get('channels') or []))
    assert any(str(channel.get('kind') or '') == 'runtime_request' for channel in (dev_to_lead.get('channels') or []))

    lead_to_qa = edge_map[(lead_task_id, qa_task_id)]
    assert lead_to_qa['structural'] is True
    assert lead_to_qa['trigger_dependency'] is True
    assert lead_to_qa['runtime_dependency'] is True
    assert int(lead_to_qa['lead_handoffs_total']) == 1
    assert any(str(channel.get('kind') or '') == 'status_trigger' for channel in (lead_to_qa.get('channels') or []))
    assert any(str(channel.get('source') or '') == 'lead_handoff' for channel in (lead_to_qa.get('channels') or []))


def test_task_dependency_graph_creates_runtime_edge_from_request_source_task_id(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    lead_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Lead dispatch',
            'status': 'Awaiting decision',
            'instruction': 'Coordinate handoffs.',
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    dev_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Developer implementation',
            'status': 'In Progress',
            'instruction': 'Implement feature changes.',
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    run_res = client.post(
        f'/api/tasks/{dev_task_id}/automation/run',
        json={
            'instruction': 'Implement feature changes.',
            'source': 'runner_orchestrator',
            'source_task_id': lead_task_id,
        },
    )
    assert run_res.status_code == 200

    graph_res = client.get(f'/api/projects/{project_id}/task-dependency-graph')
    assert graph_res.status_code == 200
    payload = graph_res.json()

    edge_map = {
        (str(item.get('source_entity_id') or ''), str(item.get('target_entity_id') or '')): item
        for item in (payload.get('edges') or [])
    }
    runtime_edge = edge_map[(lead_task_id, dev_task_id)]
    assert runtime_edge['runtime_dependency'] is True
    assert runtime_edge['runtime_requests_total'] >= 1
    assert runtime_edge['runtime_sources']['runner_orchestrator'] >= 1
    assert any(str(channel.get('source') or '') == 'runner_orchestrator' for channel in (runtime_edge.get('channels') or []))
    runtime_events = runtime_edge.get('runtime_events') or []
    assert any(str(event.get('source') or '') == 'runner_orchestrator' for event in runtime_events)


def test_task_dependency_graph_event_detail_returns_request_and_response(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Lead dispatch',
            'status': 'Awaiting decision',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Coordinate developer work.',
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    dev_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Developer task',
            'status': 'In Progress',
            'assignee_id': team['dev1'],
            'assigned_agent_code': 'dev-a',
            'instruction': 'Implement gameplay.',
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=dev_task_id,
            event_type='TaskAutomationRequested',
            payload={
                'requested_at': '2026-03-11T10:00:00Z',
                'instruction': 'Implement gameplay loop and controls.',
                'source': 'lead_kickoff_dispatch',
                'source_task_id': lead_task_id,
                'reason': 'kickoff_dispatch',
                'trigger_link': f'{lead_task_id}->{dev_task_id}:Dev',
                'correlation_id': 'corr-edge-detail',
            },
            metadata={
                'actor_id': AGENT_SYSTEM_USER_ID,
                'workspace_id': ws_id,
                'project_id': project_id,
                'task_id': dev_task_id,
            },
        )
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=dev_task_id,
            event_type='TaskCommentAdded',
            payload={
                'task_id': dev_task_id,
                'user_id': AGENT_SYSTEM_USER_ID,
                'body': 'Implemented the first playable Tetris loop.',
                'created_at': '2026-03-11T10:01:00Z',
            },
            metadata={
                'actor_id': AGENT_SYSTEM_USER_ID,
                'workspace_id': ws_id,
                'project_id': project_id,
                'task_id': dev_task_id,
            },
        )
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=dev_task_id,
            event_type='TaskAutomationCompleted',
            payload={
                'completed_at': '2026-03-11T10:02:00Z',
                'summary': 'Developer automation completed successfully.',
            },
            metadata={
                'actor_id': AGENT_SYSTEM_USER_ID,
                'workspace_id': ws_id,
                'project_id': project_id,
                'task_id': dev_task_id,
            },
        )
        db.commit()

    detail_res = client.get(
        f'/api/projects/{project_id}/task-dependency-graph/event-detail',
        params={
            'source_task_id': lead_task_id,
            'target_task_id': dev_task_id,
            'source': 'lead_kickoff_dispatch',
            'at': '2026-03-11T10:00:00Z',
            'correlation_id': 'corr-edge-detail',
        },
    )
    assert detail_res.status_code == 200
    payload = detail_res.json()
    assert payload['found'] is True
    assert payload['request_markdown'] == 'Implement gameplay loop and controls.'
    assert payload['response_markdown'] == 'Implemented the first playable Tetris loop.'
    assert payload['response_status'] == 'completed'


def test_derive_deploy_execution_snapshot_accepts_current_legacy_lead_refs():
    from shared.delivery_evidence import derive_deploy_execution_snapshot

    snapshot = derive_deploy_execution_snapshot(
        refs=[
            {'url': 'merge:main:c00ed7c7cd35fa05451158e8fb66371214094efb'},
            {'url': 'compose:/home/app/workspace/.constructos/repos/tetris/docker-compose.yml'},
            {'url': 'runtime-basis:static-web-assets(index.html)+nginx'},
            {'url': 'deploy:docker compose -p constructos-ws-default up -d:exit=0'},
            {'url': 'health:http://gateway:6768/health:http=000:curl(56)-recv-reset:2026-03-11T09:18:55Z'},
        ],
        current_snapshot={'http_url': 'http://gateway:6768/health', 'executed_at': '2026-03-11T09:15:25Z'},
    )

    assert snapshot['manifest_path'] == '/home/app/workspace/.constructos/repos/tetris/docker-compose.yml'
    assert snapshot['runtime_type'] == 'static-web-assets(index.html)+nginx'
    assert snapshot['command'] == 'docker compose -p constructos-ws-default up -d'
    assert snapshot['stack'] == 'constructos-ws-default'
    assert snapshot['http_url'] == 'http://gateway:6768/health'
    assert snapshot['http_status'] == 0
    assert snapshot['runtime_ok'] is False


def test_derive_deploy_execution_snapshot_does_not_infer_success_from_pass_title_without_http_200():
    from shared.delivery_evidence import derive_deploy_execution_snapshot, is_strict_deploy_success_snapshot

    snapshot = derive_deploy_execution_snapshot(
        refs=[
            {'url': 'deploy:stack:constructos-ws-default'},
            {'url': 'deploy:command:docker compose -p constructos-ws-default up -d'},
            {'url': 'deploy:compose:docker-compose.yml'},
            {'url': 'http://gateway:6768/health', 'title': 'deploy health: pass'},
        ],
        current_snapshot={'executed_at': '2026-03-11T22:47:28Z'},
    )

    assert snapshot['http_url'] == 'http://gateway:6768/health'
    assert snapshot.get('http_status') is None
    assert snapshot.get('runtime_ok') is not True
    assert is_strict_deploy_success_snapshot(snapshot) is False


def test_append_lead_deploy_external_refs_encodes_explicit_health_status():
    from features.agents.runner import _append_lead_deploy_external_refs

    refs = _append_lead_deploy_external_refs(
        refs=[],
        stack='constructos-ws-default',
        build_required=False,
        port=6768,
        health_path='/health',
        runtime_ok=True,
        http_url='http://gateway:6768/health',
        http_status=200,
        project_name=None,
        project_id=None,
    )

    urls = {str(item.get('url') or '') for item in refs}
    assert 'deploy:health:http://gateway:6768/health:http_200' in urls


def test_append_lead_deploy_external_refs_replaces_stale_deploy_markers():
    from features.agents.runner import _append_lead_deploy_external_refs

    refs = _append_lead_deploy_external_refs(
        refs=[
            {'url': 'deploy:stack:constructos-ws-default', 'title': 'deploy stack'},
            {'url': 'deploy:health:http://gateway:6768/health:http_000', 'title': 'deploy health: fail (0)'},
            {'url': 'https://example.com/deploy-report', 'title': 'Deploy report'},
        ],
        stack='constructos-ws-default',
        build_required=False,
        port=6768,
        health_path='/health',
        runtime_ok=True,
        http_url='http://gateway:6768/health',
        http_status=200,
        project_name=None,
        project_id=None,
    )

    urls = [str(item.get('url') or '') for item in refs]
    assert 'https://example.com/deploy-report' in urls
    assert 'deploy:health:http://gateway:6768/health:http_000' not in urls
    assert urls.count('deploy:stack:constructos-ws-default') == 1
    assert urls.count('deploy:health:http://gateway:6768/health:http_200') == 1


def test_task_dependency_graph_merges_runtime_sources_from_event_history_and_current_state(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    dev_task = client.post(
        '/api/tasks',
        json={
            'title': 'Developer task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': team['dev1'],
            'assigned_agent_code': 'dev-a',
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=lead_task_id,
            event_type='TaskAutomationRequested',
            payload={
                'requested_at': '2026-03-11T03:30:00Z',
                'instruction': 'Review blocked developer output.',
                'source': 'blocker_escalation',
                'source_task_id': dev_task_id,
            },
            metadata={
                'actor_id': AGENT_SYSTEM_USER_ID,
                'workspace_id': ws_id,
                'project_id': project_id,
                'task_id': lead_task_id,
            },
        )
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=lead_task_id,
            event_type='TaskUpdated',
            payload={
                'last_requested_source': 'runner_orchestrator',
                'last_requested_source_task_id': dev_task_id,
                'last_requested_triggered_at': '2026-03-11T03:35:00Z',
                'last_requested_correlation_id': 'corr-123',
            },
            metadata={
                'actor_id': AGENT_SYSTEM_USER_ID,
                'workspace_id': ws_id,
                'project_id': project_id,
                'task_id': lead_task_id,
            },
        )
        db.commit()

    graph_res = client.get(f'/api/projects/{project_id}/task-dependency-graph')
    assert graph_res.status_code == 200
    payload = graph_res.json()
    edge_map = {
        (str(item.get('source_entity_id') or ''), str(item.get('target_entity_id') or '')): item
        for item in (payload.get('edges') or [])
    }
    runtime_edge = edge_map[(dev_task_id, lead_task_id)]
    assert runtime_edge['runtime_dependency'] is True
    assert runtime_edge['runtime_sources']['blocker_escalation'] >= 1


def test_team_mode_orchestrator_records_lead_source_task_from_completed_developer(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    plugin_rule = client.post(
        '/api/project-rules',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Plugin Policy',
            'body': json.dumps({'mode': 'execution'}),
        },
    )
    assert plugin_rule.status_code == 200

    lead_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Lead task',
            'status': 'Awaiting decision',
            'priority': 'High',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Continue the Lead cycle.',
            'task_relationships': [
                {'kind': 'depends_on', 'task_ids': [], 'statuses': ['Completed']},
            ],
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()['id']

    dev_task = client.post(
        '/api/tasks',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Developer task',
            'status': 'Completed',
            'priority': 'High',
            'assignee_id': team['dev1'],
            'assigned_agent_code': 'dev-a',
            'instruction': 'Implement the gameplay changes.',
            'task_relationships': [
                {'kind': 'delivers_to', 'task_ids': [lead_task_id], 'statuses': ['Completed']},
            ],
            'external_refs': [
                {'url': 'commit:abc1234', 'title': 'commit evidence'},
                {'url': 'task/dev-gameplay', 'title': 'task branch evidence'},
                {'url': 'merge:main:def5678', 'title': 'merged to main'},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    patched_lead = client.patch(
        f'/api/tasks/{lead_task_id}',
        json={
            'task_relationships': [
                {'kind': 'depends_on', 'task_ids': [dev_task_id], 'statuses': ['Completed']},
            ],
        },
    )
    assert patched_lead.status_code == 200

    run_res = client.post(
        f'/api/tasks/{lead_task_id}/automation/run',
        json={
            'instruction': 'Continue the Lead cycle.',
            'source': 'runner_orchestrator',
            'source_task_id': dev_task_id,
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
            'workflow_scope': 'team_mode',
            'execution_mode': 'resume_execution',
            'task_completion_requested': False,
            'classifier_reason': 'test override',
        },
    )
    assert run_res.status_code == 200
    assert run_res.json().get('skipped') is not True

    lead_status = client.get(f'/api/tasks/{lead_task_id}/automation')
    assert lead_status.status_code == 200
    payload = lead_status.json()
    assert payload['last_requested_source'] == 'runner_orchestrator'
    assert payload['last_requested_source_task_id'] == dev_task_id
    graph_res = client.get(f'/api/projects/{project_id}/task-dependency-graph')
    assert graph_res.status_code == 200
    edge_map = {
        (str(item.get('source_entity_id') or ''), str(item.get('target_entity_id') or '')): item
        for item in (graph_res.json().get('edges') or [])
    }
    runtime_edge = edge_map[(dev_task_id, lead_task_id)]
    assert runtime_edge['runtime_sources']['runner_orchestrator'] >= 1
    channel_sources = {str(channel.get('source') or '') for channel in (runtime_edge.get('channels') or [])}
    assert 'runner_orchestrator' in channel_sources
    event_sources = {str(event.get('source') or '') for event in (runtime_edge.get('runtime_events') or [])}
    assert 'runner_orchestrator' in event_sources


def test_verify_delivery_workflow_ignores_bare_task_http_refs_for_deploy_execution(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    from shared.project_repository import resolve_project_repository_path

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})
    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path / "workspace"))

    patched_project = client.patch(
        f"/api/projects/{project_id}",
        json={
            "name": "Deferred Lead Evidence Demo",
            "external_refs": [{"url": "https://github.com/example/delivery-demo", "title": "Repo"}],
        },
    )
    assert patched_project.status_code == 200
    project_name = str(patched_project.json().get("name") or "")

    service = AgentTaskService()
    service.archive_all_tasks(workspace_id=ws_id, project_id=project_id)
    service.set_project_plugin_enabled(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="team_mode",
        enabled=True,
    )
    service.set_project_plugin_enabled(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="git_delivery",
        enabled=True,
    )

    team = _ensure_team_mode_member_roles(workspace_id=ws_id, project_id=project_id)
    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer delivery",
            "status": "In Progress",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "external_refs": [
                {"url": "commit:abc1234", "title": "Commit"},
                {"url": "branch:task/abcdefgh-implementation", "title": "Task branch"},
            ],
        },
    )
    assert dev_task.status_code == 200
    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA report",
            "status": "In Progress",
            "assignee_id": team["qa"],
            "assigned_agent_code": "qa-a",
            "external_refs": [{"url": "https://example.com/qa/report/deferred", "title": "QA report"}],
        },
    )
    assert qa_task.status_code == 200
    deploy_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead deploy cycle",
            "status": "Awaiting decision",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "external_refs": [
                {"url": "http://gateway:6768/health", "title": "Health endpoint"},
                {
                    "url": "http://gateway:6768/health?observed_at=2026-03-10T13:40:39Z&http_status=000&probe=connect_failed",
                    "title": "Observability-only probe",
                },
                {"url": "https://evidence.local/deploy-deferred?reason=no-merge-to-main-evidence", "title": "Deferred evidence"},
            ],
        },
    )
    assert deploy_task.status_code == 200

    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "docker-compose.yml").write_text(
        "services:\n"
        "  web:\n"
        "    image: nginx:alpine\n"
        "    ports:\n"
        "      - \"6768:80\"\n",
        encoding="utf-8",
    )

    verification = service.verify_delivery_workflow(project_id=project_id, workspace_id=ws_id)
    assert verification["checks"]["deploy_execution_evidence_present"] is True
    assert verification["checks"]["lead_deploy_decision_evidence_present"] is False
    assert verification["ok"] is False


def test_verify_delivery_workflow_requires_current_cycle_qa_handoff(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})
    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path / "workspace"))

    patched_project = client.patch(
        f"/api/projects/{project_id}",
        json={
            "external_refs": [{"url": "https://github.com/example/delivery-demo", "title": "Repo"}],
        },
    )
    assert patched_project.status_code == 200
    project_name = str(patched_project.json().get("name") or "")

    service = AgentTaskService()
    service.archive_all_tasks(workspace_id=ws_id, project_id=project_id)
    service.set_project_plugin_enabled(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="team_mode",
        enabled=True,
    )
    service.set_project_plugin_enabled(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="git_delivery",
        enabled=True,
    )

    team = _ensure_team_mode_member_roles(workspace_id=ws_id, project_id=project_id)
    dev_assignee = team["dev1"]
    qa_assignee = team["qa"]
    lead_assignee = team["lead"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer delivery",
            "status": "In Progress",
            "assignee_id": dev_assignee,
            "assigned_agent_code": "dev-a",
            "external_refs": [
                {"url": "commit:abc1234", "title": "Commit"},
                {"url": "branch:task/abcdefgh-implementation", "title": "Task branch"},
            ],
        },
    )
    assert dev_task.status_code == 200
    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA report",
            "status": "In Progress",
            "assignee_id": qa_assignee,
            "assigned_agent_code": "qa-a",
            "external_refs": [{"url": "https://example.com/qa/report/current", "title": "QA report"}],
        },
    )
    assert qa_task.status_code == 200
    deploy_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead deploy cycle",
            "status": "Completed",
            "assignee_id": lead_assignee,
            "assigned_agent_code": "lead-a",
            "external_refs": [],
        },
    )
    assert deploy_task.status_code == 200

    stale_handoff_at = "2026-03-09T10:00:00Z"
    current_deploy_at = "2026-03-09T10:05:00Z"
    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=deploy_task.json()["id"],
            event_type="TaskUpdated",
            payload={
                "last_deploy_execution": {
                    "executed_at": current_deploy_at,
                    "stack": "constructos-ws-default",
                    "port": 6768,
                    "health_path": "/health",
                    "command": "docker compose -p constructos-ws-default up -d",
                    "manifest_path": "docker-compose.yml",
                    "runtime_type": "dockerfile_build",
                    "runtime_ok": True,
                    "http_url": "http://gateway:6768/health",
                    "http_status": 200,
                }
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": deploy_task.json()["id"],
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=qa_task.json()["id"],
            event_type="TaskUpdated",
            payload={
                "last_requested_source": "lead_handoff",
                "last_requested_source_task_id": deploy_task.json()["id"],
                "last_requested_reason": "lead_handoff",
                "last_requested_workflow_scope": "team_mode",
                "last_requested_correlation_id": f"lead:{deploy_task.json()['id']}:{stale_handoff_at}",
                "last_requested_trigger_task_id": deploy_task.json()["id"],
                "last_requested_from_status": "In Progress",
                "last_requested_to_status": "In Progress",
                "last_requested_triggered_at": stale_handoff_at,
                "last_lead_handoff_token": f"lead:{deploy_task.json()['id']}:{stale_handoff_at}",
                "last_lead_handoff_at": stale_handoff_at,
                "last_lead_handoff_refs_json": [],
                "last_lead_handoff_deploy_execution": {
                    "executed_at": stale_handoff_at,
                    "stack": "constructos-ws-default",
                    "port": 6768,
                    "health_path": "/health",
                    "command": "docker compose -p constructos-ws-default up -d",
                    "manifest_path": "docker-compose.yml",
                    "runtime_type": "dockerfile_build",
                    "runtime_ok": True,
                    "http_url": "http://gateway:6768/health",
                    "http_status": 200,
                },
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": qa_task.json()["id"],
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=qa_task.json()["id"],
            event_type="TaskAutomationRequested",
            payload={
                "requested_at": stale_handoff_at,
                "instruction": "Run QA checks.",
                "source": "lead_handoff",
                "source_task_id": deploy_task.json()["id"],
                "reason": "lead_handoff",
                "workflow_scope": "team_mode",
                "trigger_link": f"{deploy_task.json()['id']}->{qa_task.json()['id']}:QA",
                "correlation_id": f"lead:{deploy_task.json()['id']}:{stale_handoff_at}",
                "trigger_task_id": deploy_task.json()["id"],
                "from_status": "In Progress",
                "to_status": "In Progress",
                "triggered_at": stale_handoff_at,
                "lead_handoff_token": f"lead:{deploy_task.json()['id']}:{stale_handoff_at}",
                "lead_handoff_at": stale_handoff_at,
                "lead_handoff_refs": [],
                "lead_handoff_deploy_execution": {
                    "executed_at": stale_handoff_at,
                    "stack": "constructos-ws-default",
                    "port": 6768,
                    "health_path": "/health",
                    "command": "docker compose -p constructos-ws-default up -d",
                    "manifest_path": "docker-compose.yml",
                    "runtime_type": "dockerfile_build",
                    "runtime_ok": True,
                    "http_url": "http://gateway:6768/health",
                    "http_status": 200,
                },
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": qa_task.json()["id"],
            },
        )
        for task_id in (dev_task.json()["id"], qa_task.json()["id"], deploy_task.json()["id"]):
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=task_id,
                event_type="TaskAutomationCompleted",
                payload={"completed_at": current_deploy_at},
                metadata={
                    "actor_id": AGENT_SYSTEM_USER_ID,
                    "workspace_id": ws_id,
                    "project_id": project_id,
                    "task_id": task_id,
                },
            )
        db.commit()

    from shared.project_repository import resolve_project_repository_path

    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "docker-compose.yml").write_text(
        "services:\n"
        "  web:\n"
        "    build: .\n"
        "    ports:\n"
        "      - \"6768:80\"\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        AgentTaskService,
        "_run_runtime_deploy_health_check",
        staticmethod(
            lambda **_: {
                "stack": "constructos-ws-default",
                "port": 6768,
                "health_path": "/health",
                "stack_running": True,
                "port_mapped": True,
                "http_200": True,
                "serves_application_root": True,
                "ok": True,
                "error": None,
            }
        ),
    )

    configured = service.apply_project_plugin_config(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="git_delivery",
        enabled=True,
        config={
            "required_checks": {
                "delivery": [
                    "repo_context_present",
                    "git_contract_ok",
                    "qa_handoff_current_cycle_ok",
                    "qa_has_verifiable_artifacts",
                    "lead_deploy_decision_evidence_present",
                    "deploy_execution_evidence_present",
                    "runtime_deploy_health_ok",
                ]
            },
        },
    )
    assert configured["enabled"] is True
    docker_configured = service.apply_project_plugin_config(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="docker_compose",
        enabled=True,
        config={
            "runtime_deploy_health": {
                "required": True,
                "stack": "constructos-ws-default",
                "port": 6768,
                "health_path": "/health",
                "require_http_200": True,
            },
        },
    )
    assert docker_configured["enabled"] is True

    failed = service.verify_delivery_workflow(project_id=project_id, workspace_id=ws_id)
    assert failed["checks"]["qa_handoff_current_cycle_ok"] is False
    assert failed["missing"]["qa_tasks_missing_current_cycle_handoff"] == [
        {"task_id": qa_task.json()["id"], "title": "QA report"}
    ]
    assert failed["ok"] is False

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=qa_task.json()["id"],
            event_type="TaskUpdated",
            payload={
                "last_requested_source": "lead_handoff",
                "last_requested_source_task_id": deploy_task.json()["id"],
                "last_requested_reason": "lead_handoff",
                "last_requested_workflow_scope": "team_mode",
                "last_requested_correlation_id": f"lead:{deploy_task.json()['id']}:{current_deploy_at}",
                "last_requested_trigger_task_id": deploy_task.json()["id"],
                "last_requested_from_status": "In Progress",
                "last_requested_to_status": "In Progress",
                "last_requested_triggered_at": current_deploy_at,
                "last_lead_handoff_token": f"lead:{deploy_task.json()['id']}:{current_deploy_at}",
                "last_lead_handoff_at": current_deploy_at,
                "last_lead_handoff_refs_json": [],
                "last_lead_handoff_deploy_execution": {
                    "executed_at": current_deploy_at,
                    "stack": "constructos-ws-default",
                    "port": 6768,
                    "health_path": "/health",
                    "command": "docker compose -p constructos-ws-default up -d",
                    "manifest_path": "docker-compose.yml",
                    "runtime_type": "dockerfile_build",
                    "runtime_ok": True,
                    "http_url": "http://gateway:6768/health",
                    "http_status": 200,
                },
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": qa_task.json()["id"],
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=qa_task.json()["id"],
            event_type="TaskAutomationRequested",
            payload={
                "requested_at": current_deploy_at,
                "instruction": "Run QA checks.",
                "source": "lead_handoff",
                "source_task_id": deploy_task.json()["id"],
                "reason": "lead_handoff",
                "workflow_scope": "team_mode",
                "trigger_link": f"{deploy_task.json()['id']}->{qa_task.json()['id']}:QA",
                "correlation_id": f"lead:{deploy_task.json()['id']}:{current_deploy_at}",
                "trigger_task_id": deploy_task.json()["id"],
                "from_status": "In Progress",
                "to_status": "In Progress",
                "triggered_at": current_deploy_at,
                "lead_handoff_token": f"lead:{deploy_task.json()['id']}:{current_deploy_at}",
                "lead_handoff_at": current_deploy_at,
                "lead_handoff_refs": [],
                "lead_handoff_deploy_execution": {
                    "executed_at": current_deploy_at,
                    "stack": "constructos-ws-default",
                    "port": 6768,
                    "health_path": "/health",
                    "command": "docker compose -p constructos-ws-default up -d",
                    "manifest_path": "docker-compose.yml",
                    "runtime_type": "dockerfile_build",
                    "runtime_ok": True,
                    "http_url": "http://gateway:6768/health",
                    "http_status": 200,
                },
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": qa_task.json()["id"],
            },
        )
        db.commit()

    passed = service.verify_delivery_workflow(project_id=project_id, workspace_id=ws_id)
    assert passed["checks"]["qa_handoff_current_cycle_ok"] is True
    assert passed["ok"] is True


def test_status_change_trigger_runs_for_system_actor_events(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    target = client.post(
        '/api/tasks',
        json={
            'title': 'System actor target',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Run when source reaches done',
        },
    )
    assert target.status_code == 200
    target_id = target.json()['id']

    source = client.post(
        '/api/tasks',
        json={
            'title': 'System actor source',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Source task',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'enabled': True,
                    'scope': 'self',
                        'to_statuses': ['Done'],
                    'action': 'run_automation',
                    'target_task_id': target_id,
                },
            ],
        },
    )
    assert source.status_code == 200
    source_id = source.json()['id']

    from shared.eventing import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    with SessionLocal() as db:
        completed_at = datetime.now(timezone.utc).isoformat()
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=source_id,
            event_type='TaskCompleted',
            payload={'status': 'Done', 'to_status': 'Done', 'completed_at': completed_at},
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': source_id},
        )
        db.commit()

    status = client.get(f'/api/tasks/{target_id}/automation')
    assert status.status_code == 200
    payload = status.json()
    assert payload['automation_state'] == 'queued'
    assert payload['last_requested_source'] == 'status_change'


def test_policy_checks_verification_inactive_by_default_without_skills(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})

    service = AgentTaskService()
    team = service.verify_team_mode_workflow(project_id=project_id, workspace_id=ws_id)
    delivery = service.verify_delivery_workflow(project_id=project_id, workspace_id=ws_id)

    assert team["active"] is False
    assert team["required_checks"] == []
    assert team["ok"] is True
    assert delivery["active"] is False
    assert delivery["required_checks"] == []
    assert delivery["ok"] is True


def test_agent_service_verify_delivery_workflow_respects_plugin_policy_runtime_deploy_health(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})
    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path / "workspace"))

    patched_project = client.patch(
        f"/api/projects/{project_id}",
        json={"external_refs": [{"url": "https://github.com/example/delivery-demo", "title": "Repo"}]},
    )
    assert patched_project.status_code == 200
    project_name = str(patched_project.json().get("name") or "")

    service = AgentTaskService()
    ensured = service.ensure_team_mode_project(project_id=project_id, workspace_id=ws_id)
    assert ensured["team_mode_contract_complete"] is True

    members = client.get(f"/api/projects/{project_id}/members")
    items = members.json()["items"]
    assert items
    default_assignee = items[0]["user_id"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Dev implementation",
            "status": "In Progress",
            "assignee_id": default_assignee,
            "assigned_agent_code": "dev-a",
            "external_refs": [{"url": "commit:abc1234"}],
        },
    )
    assert dev_task.status_code == 200
    dev_branch_note = client.post(
        "/api/notes",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "task_id": dev_task.json()["id"],
            "title": "Branch evidence",
            "body": f"Task branch used: task/{dev_task.json()['id'][:8]}-implementation",
            "external_refs": [{"url": f"branch:task/{dev_task.json()['id'][:8]}-implementation", "title": "Task branch"}],
        },
    )
    assert dev_branch_note.status_code == 200
    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA validation",
            "status": "In Progress",
            "assignee_id": default_assignee,
            "assigned_agent_code": "qa-a",
        },
    )
    assert qa_task.status_code == 200
    deploy_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Deploy app",
            "status": "Awaiting decision",
            "assignee_id": default_assignee,
            "assigned_agent_code": "lead-a",
            "description": "Deploy to stack constructos-ws-default on port 6768",
        },
    )
    assert deploy_task.status_code == 200

    qa_note = client.post(
        "/api/notes",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "task_id": qa_task.json()["id"],
            "title": "QA report",
            "body": "Pytest run passed and smoke test passed.",
            "external_refs": [{"url": "https://example.com/qa/report/3", "title": "QA report"}],
        },
    )
    assert qa_note.status_code == 200
    deploy_note = client.post(
        "/api/notes",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "task_id": deploy_task.json()["id"],
            "title": "Deploy note",
            "body": "docker compose up -d done; service healthy and running.",
            "external_refs": [
                {"url": "https://example.com/deploy/run/3", "title": "Deploy verification"},
                {"url": "deploy:runtime:static_assets", "title": "Runtime decision"},
                {"url": "deploy:compose:docker-compose.yml", "title": "Compose manifest"},
                {"url": "deploy:command:docker compose -p constructos-ws-default up -d", "title": "Deploy command"},
                {"url": "deploy:health:http://gateway:6768/health:http_200", "title": "Health probe"},
            ],
        },
    )
    assert deploy_note.status_code == 200

    from shared.project_repository import resolve_project_repository_path

    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "docker-compose.yml").write_text(
        "services:\n"
        "  web:\n"
        "    image: nginx:alpine\n"
        "    ports:\n"
        "      - \"6768:80\"\n",
        encoding="utf-8",
    )

    configured = service.apply_project_plugin_config(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="git_delivery",
        enabled=True,
        config={
            "required_checks": {
                "delivery": [
                    "repo_context_present",
                    "git_contract_ok",
                    "qa_has_verifiable_artifacts",
                    "deploy_execution_evidence_present",
                    "runtime_deploy_health_ok",
                ]
            },
        },
    )
    assert configured["enabled"] is True
    docker_configured = service.apply_project_plugin_config(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="docker_compose",
        enabled=True,
        config={
            "runtime_deploy_health": {
                "required": True,
                "stack": "constructos-ws-default",
                "port": 6768,
                "health_path": "/health",
                "require_http_200": False,
            },
        },
    )
    assert docker_configured["enabled"] is True

    monkeypatch.setattr(
        AgentTaskService,
        "_run_runtime_deploy_health_check",
        staticmethod(
            lambda **_: {
                "stack": "constructos-ws-default",
                "port": 6768,
                "health_path": "/health",
                "stack_running": False,
                "port_mapped": False,
                "http_200": False,
                "ok": False,
                "error": "simulated",
            }
        ),
    )
    failed = service.verify_delivery_workflow(project_id=project_id, workspace_id=ws_id)
    assert failed["checks"]["runtime_deploy_health_ok"] is False
    assert "runtime_deploy_health_ok" in failed["required_failed_checks"]
    assert failed["ok"] is False

    monkeypatch.setattr(
        AgentTaskService,
        "_run_runtime_deploy_health_check",
        staticmethod(
            lambda **_: {
                "stack": "constructos-ws-default",
                "port": 6768,
                "health_path": "/health",
                "stack_running": True,
                "port_mapped": True,
                "http_200": True,
                "serves_application_root": True,
                "ok": True,
                "error": None,
            }
        ),
    )
    passed = service.verify_delivery_workflow(project_id=project_id, workspace_id=ws_id)
    assert passed["checks"]["runtime_deploy_health_ok"] is True
    assert passed["required_failed_checks"] == []
    assert passed["ok"] is True


def test_runtime_deploy_health_check_honors_explicit_host_docker_internal(monkeypatch):
    from types import SimpleNamespace
    import urllib.request

    from features.agents.service import AgentTaskService

    def fake_subprocess_run(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "State": "running",
                        "Publishers": [{"PublishedPort": 6768}],
                    }
                ]
            ),
            stderr="",
        )

    class FakeResponse:
        def __init__(self, status: int):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(url, timeout=3):  # noqa: ARG001
        if str(url).startswith("http://host.docker.internal:6768/health"):
            return FakeResponse(status=200)
        raise OSError("connection refused")

    monkeypatch.setattr("features.agents.gates.subprocess.run", fake_subprocess_run)
    monkeypatch.setattr("features.agents.gates.os.path.exists", lambda path: path == "/.dockerenv")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = AgentTaskService._run_runtime_deploy_health_check(
        stack="constructos-ws-default",
        port=6768,
        health_path="/health",
        require_http_200=True,
        host="host.docker.internal",
    )
    assert result["stack_running"] is True
    assert result["port_mapped"] is True
    assert result["http_200"] is True
    assert result["ok"] is True
    assert result["http_url"] == "http://host.docker.internal:6768/health"


def test_runtime_deploy_health_check_honors_explicit_linux_gateway_host(monkeypatch):
    from types import SimpleNamespace
    import urllib.request

    from features.agents.service import AgentTaskService

    def fake_subprocess_run(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "State": "running",
                        "Publishers": [{"PublishedPort": 6768}],
                    }
                ]
            ),
            stderr="",
        )

    class FakeResponse:
        def __init__(self, status: int):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(url, timeout=3):  # noqa: ARG001
        if str(url).startswith("http://172.17.0.1:6768/health"):
            return FakeResponse(status=200)
        raise OSError("connection refused")

    monkeypatch.setattr("features.agents.gates.subprocess.run", fake_subprocess_run)
    monkeypatch.setattr("features.agents.gates.os.path.exists", lambda path: path == "/.dockerenv")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = AgentTaskService._run_runtime_deploy_health_check(
        stack="constructos-ws-default",
        port=6768,
        health_path="/health",
        require_http_200=True,
        host="172.17.0.1",
    )
    assert result["stack_running"] is True
    assert result["port_mapped"] is True
    assert result["http_200"] is True
    assert result["ok"] is True
    assert result["http_url"] == "http://172.17.0.1:6768/health"


def test_runtime_deploy_health_check_prefers_gateway_host_inside_container(monkeypatch):
    from types import SimpleNamespace
    import urllib.request

    from features.agents.service import AgentTaskService

    def fake_subprocess_run(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "State": "running",
                        "Publishers": [{"PublishedPort": 6768}],
                    }
                ]
            ),
            stderr="",
        )

    class FakeResponse:
        def __init__(self, status: int):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *_args, **_kwargs):
            return b'{"status":"ok"}'

    attempted_urls: list[str] = []

    def fake_urlopen(url, timeout=3):  # noqa: ARG001
        attempted_urls.append(str(url))
        if str(url) in {"http://gateway:6768/health", "http://gateway:6768/"}:
            return FakeResponse(status=200)
        raise OSError("connection refused")

    monkeypatch.setattr("features.agents.gates.subprocess.run", fake_subprocess_run)
    monkeypatch.setattr("features.agents.gates.os.path.exists", lambda path: path == "/.dockerenv")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = AgentTaskService._run_runtime_deploy_health_check(
        stack="constructos-ws-default",
        port=6768,
        health_path="/health",
        require_http_200=True,
        host=None,
    )
    assert result["stack_running"] is True
    assert result["port_mapped"] is True
    assert result["http_200"] is True
    assert result["ok"] is True
    assert result["http_url"] == "http://gateway:6768/health"
    assert attempted_urls[:2] == ["http://gateway:6768/health", "http://gateway:6768/"]


def test_runtime_deploy_health_check_rejects_placeholder_runtime_root(monkeypatch):
    from types import SimpleNamespace
    import urllib.request

    from features.agents.service import AgentTaskService

    def fake_subprocess_run(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "State": "running",
                        "Publishers": [{"PublishedPort": 6768}],
                    }
                ]
            ),
            stderr="",
        )

    class FakeResponse:
        def __init__(self, status: int, body: str):
            self.status = status
            self._body = body.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *_args, **_kwargs):
            return self._body

    def fake_urlopen(url, timeout=3):  # noqa: ARG001
        if str(url) == "http://gateway:6768/health":
            return FakeResponse(status=200, body='{"status":"ok"}')
        if str(url) == "http://gateway:6768/":
            return FakeResponse(
                status=200,
                body=(
                    "<h1>Tetris Runtime Ready</h1>"
                    "<p>Service is running on port 6768.</p>"
                    "<p>Health endpoint: /health</p>"
                ),
            )
        raise OSError("connection refused")

    monkeypatch.setattr("features.agents.gates.subprocess.run", fake_subprocess_run)
    monkeypatch.setattr("features.agents.gates.os.path.exists", lambda path: path == "/.dockerenv")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = AgentTaskService._run_runtime_deploy_health_check(
        stack="constructos-ws-default",
        port=6768,
        health_path="/health",
        require_http_200=True,
        host=None,
    )
    assert result["stack_running"] is True
    assert result["port_mapped"] is True
    assert result["http_200"] is True
    assert result["serves_application_root"] is False
    assert result["root_placeholder_detected"] is True


def test_team_lead_completed_transition_is_blocked_when_project_gates_fail(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    lead = team["lead"]

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead finalization",
            "status": "Awaiting decision",
            "assignee_id": lead,
            "assigned_agent_code": "lead-a",
            "description": "Deploy to constructos-ws-default on port 6768.",
        },
    )
    assert lead_task.status_code == 200

    blocked = client.patch(
        f"/api/tasks/{lead_task.json()['id']}",
        json={"status": "Completed"},
    )
    assert blocked.status_code == 409
    assert "Lead Completed transition blocked" in str(blocked.text)


def test_agent_service_ensure_team_mode_project_sets_up_skill_and_roster(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})

    service = AgentTaskService()
    ensured = service.ensure_team_mode_project(
        project_id=project_id,
        workspace_id=ws_id,
    )
    assert ensured["project_id"] == project_id
    assert ensured["workspace_id"] == ws_id
    assert ensured["project_skill_id"] is None
    assert ensured["generated_rule_id"] is None
    assert ensured["team_mode_contract_complete"] is True
    assert ensured["git_delivery"]["enabled"] is True
    assert ensured["git_delivery"]["project_skill_id"] is None
    assert ensured["verification"]["ok"] is False or ensured["verification"]["ok"] is True
    assert ensured["delivery_verification"]["ok"] is False or ensured["delivery_verification"]["ok"] is True
    member_roles = {str(item.get("role") or "").strip() for item in (ensured.get("members", {}).get("items") or [])}
    assert "Owner" in member_roles


def test_agent_service_ensure_team_mode_project_accepts_project_name_ref(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    project_name = bootstrap['projects'][0]['name']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})

    service = AgentTaskService()
    ensured = service.ensure_team_mode_project(
        project_ref=project_name,
        workspace_id=ws_id,
    )
    assert ensured["project_id"] == project_id
    assert ensured["ok"] is True or ensured["ok"] is False
    assert ensured["project_skill_id"] is None
    assert ensured["git_delivery"]["enabled"] is True


def test_agent_service_setup_project_orchestration_runs_staged_setup(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    payload = service.setup_project_orchestration(
        name="Setup Flow Project",
        short_description="Project created through orchestration.",
        primary_starter_key="web_app",
        workspace_id=ws_id,
        enable_team_mode=True,
        enable_docker_compose=True,
        docker_port=6768,
        seed_team_tasks=True,
        command_id="setup-flow-test",
    )

    project_id = str((payload.get("project") or {}).get("id") or "").strip()
    assert payload["contract_version"] == 1
    assert payload["blocking"] is False
    assert project_id
    assert payload["project"]["link"] == f"?tab=projects&project={project_id}"
    assert payload["requested"]["team_mode_enabled"] is True
    assert payload["requested"]["git_delivery_enabled"] is True
    assert payload["effective"]["team_mode_enabled"] is True
    assert payload["effective"]["git_delivery_enabled"] is True
    assert payload["effective"]["docker_compose_enabled"] is True
    assert str((payload.get("user_facing_summary") or {}).get("project_link") or "").strip() == f"?tab=projects&project={project_id}"
    seeded = (((payload.get("seeded_entities") or {}).get("team_mode_tasks") or {}).get("task_ids") or {})
    seeded_ids = {
        str(seeded.get("dev_a") or "").strip(),
        str(seeded.get("dev_b") or "").strip(),
        str(seeded.get("qa_a") or "").strip(),
        str(seeded.get("lead_a") or "").strip(),
    }
    seeded_ids.discard("")
    listed = client.get(
        "/api/tasks",
        params={"workspace_id": ws_id, "project_id": project_id, "limit": 100, "offset": 0},
    )
    assert listed.status_code == 200
    listed_items = listed.json().get("items") if isinstance(listed.json(), dict) else []
    task_by_id = {
        str(item.get("id") or "").strip(): item
        for item in (listed_items or [])
        if isinstance(item, dict)
    }
    for seeded_task_id in seeded_ids:
        row = task_by_id.get(seeded_task_id) or {}
        assert str(row.get("assignee_id") or "").strip()
    steps = {str(item.get("id") or "").strip(): item for item in (payload.get("steps") or [])}
    assert steps["set_plugin_team_mode"]["status"] == "ok"
    assert steps["apply_config_team_mode"]["status"] == "ok"
    assert steps["seed_team_mode_tasks"]["status"] in {"ok", "skipped"}
    if steps["seed_team_mode_tasks"]["status"] == "skipped":
        assert not seeded_ids
    assert steps["verify_team_mode_workflow"]["status"] in {"ok", "error"}
    assert steps["verify_delivery_workflow"]["status"] in {"ok", "error"}


def test_setup_project_orchestration_custom_planned_strategy_skips_starter_artifacts(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    payload = service.setup_project_orchestration(
        name="Custom Planned Starter Project",
        short_description="Skip starter artifacts and keep custom planning mode.",
        primary_starter_key="web_game",
        workspace_id=ws_id,
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=False,
        seed_team_tasks=False,
        kickoff_after_setup=False,
        command_id="setup-custom-planned",
    )

    assert payload["blocking"] is False
    assert payload["requested"]["backlog_strategy"] == "custom_planned"
    assert payload["effective"]["backlog_strategy"] == "custom_planned"
    summary = payload.get("user_facing_summary") if isinstance(payload.get("user_facing_summary"), dict) else {}
    configured = summary.get("configured") if isinstance(summary.get("configured"), dict) else {}
    assert configured.get("backlog_strategy") == "custom_planned"

    steps = {str(item.get("id") or "").strip(): item for item in (payload.get("steps") or [])}
    assert steps["bootstrap_starter_artifacts"]["status"] == "skipped"
    assert "starter_seeded" in str(steps["bootstrap_starter_artifacts"].get("reason") or "")

    project_id = str((payload.get("project") or {}).get("id") or "").strip()
    listed = client.get(
        "/api/tasks",
        params={"workspace_id": ws_id, "project_id": project_id, "limit": 100, "offset": 0},
    )
    assert listed.status_code == 200
    items = listed.json().get("items") if isinstance(listed.json(), dict) else []
    assert items == []


def test_setup_project_orchestration_blocks_kickoff_without_actionable_tasks(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    payload = service.setup_project_orchestration(
        name="Kickoff Backlog Guard Project",
        short_description="Kickoff should stop until custom tasks are created.",
        primary_starter_key="web_game",
        workspace_id=ws_id,
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=False,
        seed_team_tasks=False,
        kickoff_after_setup=True,
        command_id="setup-kickoff-backlog-guard",
    )

    assert payload["blocking"] is True
    steps = {str(item.get("id") or "").strip(): item for item in (payload.get("steps") or [])}
    assert steps["validate_kickoff_backlog_readiness"]["status"] == "error"
    assert steps["dispatch_team_mode_kickoff"]["status"] == "skipped"
    assert "actionable implementation task" in str(steps["validate_kickoff_backlog_readiness"]["error"]).lower()


def test_setup_project_orchestration_starter_seeded_tasks_have_origin_labels(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    payload = service.setup_project_orchestration(
        name="Starter Seeded Origin Labels Project",
        short_description="Starter-generated tasks should carry origin labels.",
        primary_starter_key="web_game",
        workspace_id=ws_id,
        enable_team_mode=False,
        enable_git_delivery=False,
        enable_docker_compose=False,
        seed_team_tasks=True,
        kickoff_after_setup=False,
        command_id="setup-starter-origin-labels",
    )

    assert payload["blocking"] is False
    assert payload["requested"]["backlog_strategy"] == "starter_seeded"
    project_id = str((payload.get("project") or {}).get("id") or "").strip()
    listed = client.get(
        "/api/tasks",
        params={"workspace_id": ws_id, "project_id": project_id, "limit": 100, "offset": 0},
    )
    assert listed.status_code == 200
    items = listed.json().get("items") if isinstance(listed.json(), dict) else []
    assert items
    for item in items:
        labels = [str(label or "").strip() for label in (item.get("labels") or [])]
        assert "starter-seeded" in labels
        assert "starter:web_game" in labels


def test_setup_project_orchestration_blocks_kickoff_when_no_explicit_developer_routing(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    payload = service.setup_project_orchestration(
        name="Kickoff Routing Guard Project",
        short_description="Starter tasks exist but no explicit developer routing.",
        primary_starter_key="web_game",
        workspace_id=ws_id,
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=False,
        seed_team_tasks=True,
        kickoff_after_setup=True,
        command_id="setup-kickoff-routing-guard",
    )

    assert payload["blocking"] is True
    steps = {str(item.get("id") or "").strip(): item for item in (payload.get("steps") or [])}
    assert steps["validate_kickoff_backlog_readiness"]["status"] == "error"
    assert steps["dispatch_team_mode_kickoff"]["status"] == "skipped"
    assert "developer agent slot" in str(steps["validate_kickoff_backlog_readiness"]["error"]).lower()


def test_setup_project_orchestration_summary_includes_split_verification_blocking_and_snapshot(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    payload = service.setup_project_orchestration(
        name="Summary Contract Project",
        short_description="Validate setup/delivery split summary contract.",
        primary_starter_key="web_game",
        workspace_id=ws_id,
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=False,
        seed_team_tasks=False,
        kickoff_after_setup=False,
        command_id="setup-summary-contract",
    )

    summary = payload.get("user_facing_summary") if isinstance(payload.get("user_facing_summary"), dict) else {}
    verification = summary.get("verification") if isinstance(summary.get("verification"), dict) else {}
    assert verification.get("setup_status") in {"PASS", "Needs attention"}
    assert verification.get("delivery_status") in {"PASS", "Needs attention", "Not requested"}
    delivery_ok = verification.get("delivery_ok")
    if delivery_ok is True:
        assert verification.get("delivery_status") == "PASS"
    if delivery_ok is False:
        assert verification.get("delivery_status") == "Needs attention"

    blocking_state = summary.get("blocking_state") if isinstance(summary.get("blocking_state"), dict) else {}
    assert str(blocking_state.get("code") or "").strip()
    assert str(blocking_state.get("message") or "").strip()

    execution_snapshot = summary.get("execution_snapshot") if isinstance(summary.get("execution_snapshot"), dict) else {}
    assert isinstance(execution_snapshot.get("total_tasks"), int)
    assert isinstance(execution_snapshot.get("by_status"), dict)
    assert isinstance(execution_snapshot.get("by_semantic_status"), dict)
    assert "unknown" in execution_snapshot.get("by_semantic_status")

    lifecycle_notice = str(summary.get("lifecycle_notice") or "").strip()
    assert "no active tasks are currently persisted" in lifecycle_notice.lower()


def test_setup_project_orchestration_summary_delivery_status_not_requested_when_git_disabled(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    payload = service.setup_project_orchestration(
        name="Summary Contract No Git Project",
        short_description="Delivery status should be not requested when git is disabled.",
        primary_starter_key="web_game",
        workspace_id=ws_id,
        enable_team_mode=False,
        enable_git_delivery=False,
        enable_docker_compose=False,
        seed_team_tasks=False,
        kickoff_after_setup=False,
        command_id="setup-summary-contract-no-git",
    )

    summary = payload.get("user_facing_summary") if isinstance(payload.get("user_facing_summary"), dict) else {}
    verification = summary.get("verification") if isinstance(summary.get("verification"), dict) else {}
    assert verification.get("delivery_status") == "Not requested"
    assert verification.get("delivery_ok") is None


def test_agent_service_setup_project_orchestration_auto_sets_local_repository_context(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    payload = service.setup_project_orchestration(
        name="Repo Context Project",
        short_description="Project created through orchestration.",
        primary_starter_key="web_app",
        workspace_id=ws_id,
        enable_team_mode=False,
        enable_git_delivery=True,
        enable_docker_compose=False,
        seed_team_tasks=False,
        command_id="setup-repo-context-test",
    )

    assert payload["blocking"] is False
    project_id = str((payload.get("project") or {}).get("id") or "").strip()
    assert project_id

    from shared.models import Project, SessionLocal

    with SessionLocal() as db:
        project_row = db.get(Project, project_id)
        assert project_row is not None
        refs = json.loads(str(project_row.external_refs or "[]"))
    assert isinstance(refs, list)
    repo_urls = [str(item.get("url") or "").strip() for item in refs if isinstance(item, dict)]
    assert any(url.startswith("file://") for url in repo_urls)
    assert any("/home/app/workspace/" in url for url in repo_urls)

    delivery = payload.get("verification", {}).get("delivery", {})
    checks = delivery.get("checks") if isinstance(delivery, dict) else {}
    assert bool(checks.get("repo_context_present")) is True


def test_agent_service_setup_project_orchestration_honors_explicit_event_storming_setting(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    from shared.models import Project, SessionLocal

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    payload = service.setup_project_orchestration(
        name="Event Storming Disabled Setup",
        short_description="Project created with Event Storming disabled.",
        primary_starter_key="web_app",
        workspace_id=ws_id,
        enable_team_mode=True,
        enable_docker_compose=True,
        docker_port=6768,
        seed_team_tasks=False,
        kickoff_after_setup=False,
        expected_event_storming_enabled=False,
        command_id="setup-event-storming-disabled",
    )

    assert payload["blocking"] is False
    project_id = str((payload.get("project") or {}).get("id") or "").strip()
    assert project_id
    steps = {str(item.get("id") or "").strip(): item for item in (payload.get("steps") or [])}
    assert steps["apply_project_event_storming_setting"]["status"] in {"ok", "skipped"}
    summary = payload.get("user_facing_summary") if isinstance(payload.get("user_facing_summary"), dict) else {}
    configured = summary.get("configured") if isinstance(summary.get("configured"), dict) else {}
    assert configured.get("event_storming_enabled") is False

    with SessionLocal() as db:
        project_row = db.get(Project, project_id)
        assert project_row is not None
        assert bool(getattr(project_row, "event_storming_enabled", True)) is False


def test_agent_service_setup_project_orchestration_skips_seeded_team_tasks_when_project_already_has_tasks(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})

    before_list = client.get(
        "/api/tasks",
        params={"workspace_id": ws_id, "project_id": project_id, "limit": 100, "offset": 0},
    )
    assert before_list.status_code == 200
    before_items = before_list.json().get("items") if isinstance(before_list.json(), dict) else []
    before_task_ids = {
        str(item.get("id") or "").strip()
        for item in (before_items or [])
        if isinstance(item, dict)
    }

    preexisting = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Preexisting requested task",
            "status": "Todo",
            "instruction": "Keep the requested task set intact.",
        },
    )
    assert preexisting.status_code == 200
    preexisting_task_id = str(preexisting.json().get("id") or "").strip()
    assert preexisting_task_id

    service = AgentTaskService()
    payload = service.setup_project_orchestration(
        project_id=project_id,
        workspace_id=ws_id,
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=True,
        docker_port=6768,
        seed_team_tasks=True,
        kickoff_after_setup=False,
        command_id="setup-skip-seed-existing-tasks",
    )

    assert payload["blocking"] is False
    steps = {str(item.get("id") or "").strip(): item for item in (payload.get("steps") or [])}
    assert steps["seed_team_mode_tasks"]["status"] == "skipped"
    assert "preserve the requested task set" in str(steps["seed_team_mode_tasks"].get("reason") or "")

    listed = client.get(
        "/api/tasks",
        params={"workspace_id": ws_id, "project_id": project_id, "limit": 100, "offset": 0},
    )
    assert listed.status_code == 200
    items = listed.json().get("items") if isinstance(listed.json(), dict) else []
    task_ids = {str(item.get("id") or "").strip() for item in (items or []) if isinstance(item, dict)}
    assert preexisting_task_id in task_ids
    assert task_ids == before_task_ids | {preexisting_task_id}


def _legacy_test_agent_service_create_task_backfills_exact_three_task_team_mode_topology(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    setup = service.setup_project_orchestration(
        name="Prompt Flow Team Mode Project",
        short_description="Project created through orchestration without seeded tasks.",
        primary_starter_key="web_game",
        workspace_id=ws_id,
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=True,
        docker_port=6768,
        seed_team_tasks=False,
        kickoff_after_setup=False,
        command_id="prompt-flow-team-mode",
    )

    assert setup["blocking"] is False
    project_id = str((setup.get("project") or {}).get("id") or "").strip()
    assert project_id

    team = _ensure_team_mode_member_roles(workspace_id=ws_id, project_id=project_id)
    specification = service.create_specification(
        title="Implement Web Tetris Game",
        workspace_id=ws_id,
        project_id=project_id,
        auth_token="",
        command_id="prompt-flow-spec",
    )
    specification_id = str(specification.get("id") or "").strip()
    assert specification_id

    scheduled_at_utc = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    dev_task = service.create_task(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        title="Build core Tetris gameplay loop",
        status="To do",
        assignee_id=team["dev1"],
        assigned_agent_code="dev-a",
        instruction="Implement the game and hand off to Lead.",
        auth_token="",
        command_id="prompt-flow-dev",
    )
    lead_task = service.create_task(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        title="Coordinate integration and deployment readiness",
        status="Awaiting decision",
        assignee_id=team["lead"],
        assigned_agent_code="lead-a",
        instruction="Coordinate Team Mode execution.",
        recurring_rule="every:5m",
        scheduled_at_utc=scheduled_at_utc,
        auth_token="",
        command_id="prompt-flow-lead",
    )
    qa_task = service.create_task(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        title="Validate gameplay quality and release criteria",
        status="In Progress",
        assignee_id=team["qa"],
        assigned_agent_code="qa-a",
        instruction="Validate the release candidate.",
        auth_token="",
        command_id="prompt-flow-qa",
    )

    dev_task_id = str(dev_task.get("id") or "").strip()
    lead_task_id = str(lead_task.get("id") or "").strip()
    qa_task_id = str(qa_task.get("id") or "").strip()
    listed = service.list_tasks(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        archived=False,
        limit=10,
        offset=0,
        auth_token="",
    )
    items = {str(item.get("id") or "").strip(): item for item in (listed.get("items") or [])}
    assert set(items.keys()) == {dev_task_id, lead_task_id, qa_task_id}

    assert items[dev_task_id]["task_relationships"] == [
        {
            "kind": "delivers_to",
            "task_ids": [lead_task_id],
            "match_mode": "all",
            "statuses": ["Awaiting decision"],
        }
    ]
    assert items[lead_task_id]["task_relationships"] == [
        {
            "kind": "depends_on",
            "task_ids": [dev_task_id],
            "match_mode": "all",
            "statuses": ["Completed"],
        },
        {
            "kind": "depends_on",
            "task_ids": [dev_task_id, qa_task_id],
            "match_mode": "any",
            "statuses": ["Blocked"],
        },
    ]
    assert items[qa_task_id]["task_relationships"] == [
        {
            "kind": "hands_off_to",
            "task_ids": [lead_task_id],
            "match_mode": "all",
            "statuses": ["Completed"],
        },
        {
            "kind": "escalates_to",
            "task_ids": [lead_task_id],
            "match_mode": "any",
            "statuses": ["Awaiting decision", "Blocked"],
        },
    ]

    verification = service.verify_team_mode_workflow(
        project_id=project_id,
        workspace_id=ws_id,
        auth_token="",
    )
    assert verification["ok"] is True
    assert verification["checks"]["role_coverage_present"] is True
    assert verification["checks"]["single_lead_present"] is True
    assert verification["checks"]["human_owner_present"] is True
    assert verification["checks"]["status_semantics_present"] is True


def _legacy_test_agent_service_create_task_backfills_default_team_mode_topology_for_detailed_spec(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    setup = service.setup_project_orchestration(
        name="Detailed Team Mode Project",
        short_description="Project created through orchestration without seeded tasks.",
        primary_starter_key="web_game",
        workspace_id=ws_id,
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=True,
        docker_port=6769,
        seed_team_tasks=False,
        kickoff_after_setup=False,
        command_id="detailed-team-mode",
    )

    assert setup["blocking"] is False
    project_id = str((setup.get("project") or {}).get("id") or "").strip()
    assert project_id

    team = _ensure_team_mode_member_roles(workspace_id=ws_id, project_id=project_id)
    specification = service.create_specification(
        title="Implement Battle City",
        workspace_id=ws_id,
        project_id=project_id,
        auth_token="",
        command_id="battle-city-spec",
    )
    specification_id = str(specification.get("id") or "").strip()
    assert specification_id

    scheduled_at_utc = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    dev_a_task = service.create_task(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        title="Implement map system and player combat",
        status="To do",
        assignee_id=team["dev1"],
        assigned_agent_code="dev-a",
        instruction="Implement the first developer track.",
        auth_token="",
        command_id="battle-city-dev-a",
    )
    dev_b_task = service.create_task(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        title="Implement enemy waves and HUD",
        status="To do",
        assignee_id=team["dev2"],
        assigned_agent_code="dev-b",
        instruction="Implement the second developer track.",
        auth_token="",
        command_id="battle-city-dev-b",
    )
    lead_delivery_task = service.create_task(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        title="Coordinate integration and deployment readiness",
        status="Awaiting decision",
        assignee_id=team["lead"],
        assigned_agent_code="lead-a",
        instruction="Coordinate Team Mode execution.",
        auth_token="",
        command_id="battle-city-lead-delivery",
    )
    lead_oversight_task = service.create_task(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        title="Recurring delivery oversight and blocker triage",
        status="Awaiting decision",
        assignee_id=team["lead"],
        assigned_agent_code="lead-a",
        instruction="Run recurring Lead oversight.",
        execution_triggers=[
            {
                "kind": "schedule",
                "enabled": True,
                "scheduled_at_utc": scheduled_at_utc,
                "recurring_rule": "every:5m",
                "run_on_statuses": ["In Progress"],
                "action": "request_automation",
            }
        ],
        auth_token="",
        command_id="battle-city-lead-oversight",
    )
    qa_task = service.create_task(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        title="Validate gameplay flow and runtime health",
        status="In Progress",
        assignee_id=team["qa"],
        assigned_agent_code="qa-a",
        instruction="Validate the release candidate.",
        auth_token="",
        command_id="battle-city-qa",
    )

    dev_a_task_id = str(dev_a_task.get("id") or "").strip()
    dev_b_task_id = str(dev_b_task.get("id") or "").strip()
    lead_delivery_task_id = str(lead_delivery_task.get("id") or "").strip()
    lead_oversight_task_id = str(lead_oversight_task.get("id") or "").strip()
    qa_task_id = str(qa_task.get("id") or "").strip()
    listed = service.list_tasks(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        archived=False,
        limit=10,
        offset=0,
        auth_token="",
    )
    items = {str(item.get("id") or "").strip(): item for item in (listed.get("items") or [])}
    assert set(items.keys()) == {
        dev_a_task_id,
        dev_b_task_id,
        lead_delivery_task_id,
        lead_oversight_task_id,
        qa_task_id,
    }

    assert items[dev_a_task_id]["task_relationships"] == [
        {
            "kind": "delivers_to",
            "task_ids": [lead_delivery_task_id],
            "match_mode": "all",
            "statuses": ["Awaiting decision"],
        }
    ]
    assert items[dev_b_task_id]["task_relationships"] == [
        {
            "kind": "delivers_to",
            "task_ids": [lead_delivery_task_id],
            "match_mode": "all",
            "statuses": ["Awaiting decision"],
        }
    ]
    assert items[lead_delivery_task_id]["task_relationships"] == [
        {
            "kind": "depends_on",
            "task_ids": [dev_a_task_id, dev_b_task_id],
            "match_mode": "all",
            "statuses": ["Completed"],
        },
        {
            "kind": "depends_on",
            "task_ids": [dev_a_task_id, dev_b_task_id, qa_task_id],
            "match_mode": "any",
            "statuses": ["Blocked"],
        },
    ]
    assert items[qa_task_id]["task_relationships"] == [
        {
            "kind": "hands_off_to",
            "task_ids": [lead_delivery_task_id],
            "match_mode": "all",
            "statuses": ["Completed"],
        },
        {
            "kind": "escalates_to",
            "task_ids": [lead_delivery_task_id],
            "match_mode": "any",
            "statuses": ["Awaiting decision", "Blocked"],
        },
    ]
    assert items[lead_oversight_task_id]["task_relationships"] == []
    oversight_triggers = items[lead_oversight_task_id]["execution_triggers"]
    assert isinstance(oversight_triggers, list)
    assert len(oversight_triggers) == 1
    assert oversight_triggers[0]["kind"] == "schedule"
    assert oversight_triggers[0]["recurring_rule"] == "every:5m"
    assert oversight_triggers[0]["run_on_statuses"] == ["Awaiting decision"]

    verification = service.verify_team_mode_workflow(
        project_id=project_id,
        workspace_id=ws_id,
        auth_token="",
    )
    assert verification["ok"] is True
    assert verification["checks"]["role_coverage_present"] is True
    assert verification["checks"]["single_lead_present"] is True
    assert verification["checks"]["human_owner_present"] is True
    assert verification["checks"]["status_semantics_present"] is True


def test_agent_service_setup_project_orchestration_blocks_kickoff_when_runtime_health_port_missing(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})

    service = AgentTaskService()
    payload = service.setup_project_orchestration(
        project_id=project_id,
        workspace_id=ws_id,
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=True,
        docker_compose_config={
            "runtime_deploy_health": {
                "required": True,
                "stack": "constructos-ws-default",
                "port": None,
                "health_path": "/health",
                "require_http_200": True,
            }
        },
        kickoff_after_setup=True,
    )

    assert payload["blocking"] is True
    assert payload["execution_state"] == "setup_failed"
    steps = {str(item.get("id") or "").strip(): item for item in (payload.get("steps") or [])}
    assert steps["validate_runtime_deploy_health_contract"]["status"] == "error"
    assert steps["dispatch_team_mode_kickoff"]["status"] == "skipped"
    errors = payload.get("errors") or []
    assert any("runtime_deploy_health.port" in str(item) for item in errors)


def test_direct_team_mode_kickoff_queues_implementation_tasks_without_lead_task(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module
    import features.agents.runner as runner_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})
    monkeypatch.setattr(runner_module, "run_queued_automation_once", lambda *args, **kwargs: 0)

    for title, agent_code, description in (
        ("Implement core board and piece mechanics", "dev-a", "Build the Tetris board, tetromino movement, rotation, and collision handling."),
        ("Implement gameplay loop and scoring systems", "dev-b", "Add gravity, input handling, scoring, level progression, and game-over detection."),
        ("Implement web UI and containerized runtime setup", "dev-a", "Build the browser UI and make the app runnable through Docker Compose on port 6768."),
    ):
        created = client.post(
            "/api/tasks",
            json={
                "workspace_id": ws_id,
                "project_id": project_id,
                "title": title,
                "status": "To Do",
                "assignee_id": team["dev1"],
                "assigned_agent_code": agent_code,
                "description": description,
            },
        )
        assert created.status_code == 200

    service = AgentTaskService()
    kickoff = service._dispatch_team_mode_kickoff_after_setup(
        workspace_id=ws_id,
        project_id=project_id,
        auth_token=None,
        command_id="direct-dev-kickoff",
    )

    assert isinstance(kickoff, dict)
    assert kickoff["ok"] is True
    assert kickoff["kickoff_dispatched"] is True
    assert kickoff["queued_by_role"]["Developer"] == 3
    assert kickoff["developer_dispatch_confirmed"] is True

    listed = client.get(f"/api/tasks?workspace_id={ws_id}&project_id={project_id}")
    assert listed.status_code == 200
    items = listed.json().get("items") or []
    developer_items = [item for item in items if str(item.get("assigned_agent_code") or "").strip().startswith("dev-")]
    assert len(developer_items) == 3
    automation_states = {str(item.get("automation_state") or "").strip().lower() for item in developer_items}
    assert automation_states <= {"idle", "queued"}


def test_agent_service_setup_project_orchestration_blocks_docker_without_git(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})

    service = AgentTaskService()
    payload = service.setup_project_orchestration(
        project_id=project_id,
        workspace_id=ws_id,
        enable_team_mode=False,
        enable_git_delivery=False,
        enable_docker_compose=True,
    )

    assert payload["contract_version"] == 1
    assert payload["blocking"] is True
    assert payload["execution_state"] == "setup_failed"
    assert payload["effective"]["docker_compose_enabled"] is False
    step_ids = [str(item.get("id") or "").strip() for item in (payload.get("steps") or [])]
    assert "validate_plugin_dependencies" in step_ids


def test_agent_service_setup_project_orchestration_reports_missing_inputs_for_new_project(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    with pytest.raises(HTTPException) as exc_info:
        service.setup_project_orchestration(
            name="Tetris",
            primary_starter_key="web_game",
            workspace_id=ws_id,
        )

    exc = exc_info.value
    assert exc.status_code == 422
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    assert detail.get("code") == "missing_setup_inputs"
    assert str(detail.get("next_input_key") or "").strip() == "short_description"
    missing = detail.get("missing_inputs") if isinstance(detail.get("missing_inputs"), list) else []
    missing_keys = [str(item.get("key") or "").strip() for item in missing if isinstance(item, dict)]
    assert "short_description" in missing_keys
    assert "enable_team_mode" in missing_keys
    assert str(detail.get("next_question") or "").strip()
    resolved_inputs = detail.get("resolved_inputs") if isinstance(detail.get("resolved_inputs"), dict) else {}
    assert str(resolved_inputs.get("name") or "").strip() == "Tetris"


def test_agent_service_setup_project_orchestration_skips_known_answers_in_missing_inputs(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    with pytest.raises(HTTPException) as exc_info:
        service.setup_project_orchestration(
            name="Tetris",
            primary_starter_key="web_game",
            short_description="Web game",
            workspace_id=ws_id,
            enable_team_mode=True,
        )

    exc = exc_info.value
    assert exc.status_code == 422
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    missing = detail.get("missing_inputs") if isinstance(detail.get("missing_inputs"), list) else []
    missing_keys = [str(item.get("key") or "").strip() for item in missing if isinstance(item, dict)]
    assert "name" not in missing_keys
    assert "short_description" not in missing_keys
    assert "enable_team_mode" not in missing_keys
    assert "enable_docker_compose" in missing_keys
    assert str(detail.get("next_input_key") or "").strip() == "enable_docker_compose"


def test_agent_service_setup_project_orchestration_uses_chat_default_profile_for_new_project(tmp_path, monkeypatch):
    from shared.models import Project, SessionLocal

    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    payload = service.setup_project_orchestration(
        name="Embedding Default Project",
        short_description="Validate setup defaults.",
        primary_starter_key="web_app",
        workspace_id=ws_id,
        enable_team_mode=False,
        enable_git_delivery=False,
        enable_docker_compose=False,
    )

    assert payload["execution_state"] == "setup_complete"
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    project_id = str(project.get("id") or "").strip()
    assert project_id
    with SessionLocal() as db:
        persisted = db.get(Project, project_id)
        assert persisted is not None
        assert persisted.embedding_enabled is True
        assert str(persisted.chat_index_mode or "").strip().upper() == "KG_AND_VECTOR"


def test_agent_service_apply_plugin_config_with_retry_handles_version_mismatch(monkeypatch):
    from features.agents.service import AgentTaskService

    service = AgentTaskService(require_token=False)
    call_state = {"apply_calls": 0, "get_calls": 0}
    expected_versions: list[int | None] = []

    def _fake_get_project_plugin_config(**kwargs):
        call_state["get_calls"] += 1
        if call_state["get_calls"] == 1:
            return {"version": 1}
        return {"version": 2}

    def _fake_apply_project_plugin_config(**kwargs):
        call_state["apply_calls"] += 1
        expected_versions.append(kwargs.get("expected_version"))
        if call_state["apply_calls"] == 1:
            raise HTTPException(status_code=409, detail="Version mismatch for git_delivery")
        return {"plugin_key": "git_delivery", "version": 3, "enabled": True}

    monkeypatch.setattr(service, "get_project_plugin_config", _fake_get_project_plugin_config)
    monkeypatch.setattr(service, "apply_project_plugin_config", _fake_apply_project_plugin_config)

    payload = service._apply_plugin_config_with_retry(
        project_id="p1",
        workspace_id="w1",
        plugin_key="git_delivery",
        config={"required_checks": {"delivery": ["git_contract_ok"]}},
        auth_token=None,
    )

    assert payload["plugin_key"] == "git_delivery"
    assert call_state["apply_calls"] == 2
    assert call_state["get_calls"] == 2
    assert expected_versions == [1, 2]


def test_agent_service_setup_project_orchestration_retries_transient_toggle_error(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})

    service = AgentTaskService()
    original_set_plugin = service.set_project_plugin_enabled
    calls = {"team_mode": 0}

    def _flaky_set_plugin(**kwargs):
        plugin_key = str(kwargs.get("plugin_key") or "").strip()
        if plugin_key == "team_mode":
            calls["team_mode"] += 1
            if calls["team_mode"] == 1:
                raise HTTPException(status_code=503, detail="temporary unavailable")
        return original_set_plugin(**kwargs)

    monkeypatch.setattr(service, "set_project_plugin_enabled", _flaky_set_plugin)

    payload = service.setup_project_orchestration(
        project_id=project_id,
        workspace_id=ws_id,
        enable_team_mode=False,
        enable_git_delivery=False,
        enable_docker_compose=False,
        seed_team_tasks=False,
    )

    steps = {str(item.get("id") or "").strip(): item for item in (payload.get("steps") or [])}
    assert payload["blocking"] is False
    assert steps["set_plugin_team_mode"]["status"] == "ok"
    assert steps["set_plugin_team_mode"]["attempts"] == 2
    assert calls["team_mode"] == 2


def test_agent_service_setup_project_orchestration_returns_blocking_step_error_contract(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})

    service = AgentTaskService()
    original_set_plugin = service.set_project_plugin_enabled

    def _always_fail_set_plugin(**kwargs):
        if str(kwargs.get("plugin_key") or "").strip() == "team_mode":
            raise HTTPException(status_code=500, detail="simulated toggle failure")
        return original_set_plugin(**kwargs)

    monkeypatch.setattr(service, "set_project_plugin_enabled", _always_fail_set_plugin)

    payload = service.setup_project_orchestration(
        project_id=project_id,
        workspace_id=ws_id,
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=False,
        seed_team_tasks=False,
    )

    assert payload["blocking"] is True
    assert payload["execution_state"] == "setup_failed"
    assert isinstance(payload.get("errors"), list) and payload["errors"]
    first_error = payload["errors"][0]
    assert first_error["type"] == "http_error"
    assert first_error["status_code"] == 500
    steps = {str(item.get("id") or "").strip(): item for item in (payload.get("steps") or [])}
    assert steps["set_plugin_team_mode"]["status"] == "error"
    assert "set_plugin_git_delivery" not in steps


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


def test_extract_missing_setup_question_from_nested_error_payload(tmp_path):
    build_client(tmp_path)
    from features.agents import api as agents_api

    error_text = (
        "codex app-server turn failed: tool call failed | "
        "{\"message\":\"Missing required setup inputs for setup_project_orchestration\","
        "\"code\":\"missing_setup_inputs\","
        "\"next_question\":\"Do you want Team Mode for this project?\","
        "\"next_input_key\":\"enable_team_mode\"}"
    )
    question = agents_api._extract_missing_setup_question(error_text)
    assert question == "Do you want Team Mode for this project?"


def test_map_chat_exception_to_response_uses_question_for_missing_inputs(tmp_path):
    build_client(tmp_path)
    from features.agents import api as agents_api

    exc = RuntimeError(
        "{\"code\":\"missing_setup_inputs\",\"missing_inputs\":[{\"key\":\"docker_port\","
        "\"question\":\"Which port should Docker Compose use?\"}]}"
    )
    ok, summary, comment = agents_api._map_chat_exception_to_response(exc)
    assert ok is True
    assert summary == "Which port should Docker Compose use?"
    assert comment is None


def test_agents_chat_setup_flow_asks_single_missing_question_per_turn_and_finishes(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    call_state = {"count": 0}

    def _fake_execute_task_automation(**_kwargs):
        call_state["count"] += 1
        if call_state["count"] == 1:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "missing_setup_inputs",
                        "next_input_key": "name",
                        "next_question": "What should the new project be named?",
                        "missing_inputs": [{"key": "name", "question": "What should the new project be named?"}],
                    }
                )
            )
        if call_state["count"] == 2:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "missing_setup_inputs",
                        "next_input_key": "enable_team_mode",
                        "next_question": "Do you want Team Mode for this project?",
                        "missing_inputs": [
                            {"key": "enable_team_mode", "question": "Do you want Team Mode for this project?"}
                        ],
                    }
                )
            )
        if call_state["count"] == 3:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "missing_setup_inputs",
                        "next_input_key": "docker_port",
                        "next_question": "Which port should Docker Compose use?",
                        "missing_inputs": [{"key": "docker_port", "question": "Which port should Docker Compose use?"}],
                    }
                )
            )
        return AutomationOutcome(
            action='comment',
            summary='[Project: Tetris](?tab=projects&project=proj-123)\n\nKickoff required: Yes',
            comment=None,
            usage=None,
        )

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)
    monkeypatch.setattr(
        agents_api,
        '_classify_chat_instruction_intents',
        lambda **_kwargs: {
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': True,
        },
    )

    session_id = 'setup-flow-regression-1'
    turn1 = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Help me set up a new project.',
            'session_id': session_id,
            'history': [],
        },
    )
    assert turn1.status_code == 200
    body1 = turn1.json()
    assert body1['ok'] is True
    assert body1['summary'] == 'What should the new project be named?'
    assert body1['comment'] is None

    turn2 = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Tetris web game',
            'session_id': session_id,
            'history': [{'role': 'user', 'content': 'Help me set up a new project.'}],
        },
    )
    assert turn2.status_code == 200
    body2 = turn2.json()
    assert body2['ok'] is True
    assert body2['summary'] == 'Do you want Team Mode for this project?'
    assert body2['comment'] is None

    turn3 = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'yes and docker compose',
            'session_id': session_id,
            'history': [{'role': 'user', 'content': 'Tetris web game'}],
        },
    )
    assert turn3.status_code == 200
    body3 = turn3.json()
    assert body3['ok'] is True
    assert body3['summary'] == 'Which port should Docker Compose use?'
    assert body3['comment'] is None

    turn4 = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': '6768',
            'session_id': session_id,
            'history': [{'role': 'user', 'content': 'yes and docker compose'}],
        },
    )
    assert turn4.status_code == 200
    body4 = turn4.json()
    assert body4['ok'] is True
    assert '?tab=projects&project=proj-123' in str(body4['summary'] or '')
    assert 'Kickoff required: Yes' in str(body4['summary'] or '')


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


def test_agents_chat_endpoint_includes_project_knowledge_evidence_for_grounded_lookup(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    captured: dict[str, object] = {}

    def _fake_execute_task_automation(**kwargs):
        captured.update(kwargs)
        return AutomationOutcome(action='comment', summary='The secret number is 99.', comment=None, usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)
    monkeypatch.setattr(
        agents_api,
        '_classify_chat_instruction_intents',
        lambda **_kwargs: {
            'execution_intent': False,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
            'project_knowledge_lookup_intent': False,
            'grounded_answer_required': False,
            'workflow_scope': 'unknown',
            'execution_mode': 'unknown',
            'deploy_requested': False,
            'docker_compose_requested': False,
            'requested_port': None,
            'project_name_provided': False,
            'task_completion_requested': False,
            'reason': 'Classifier missed multilingual factual lookup.',
        },
    )
    monkeypatch.setattr(
        agents_api,
        'search_project_knowledge_query',
        lambda **_kwargs: {
            'project_id': project_id,
            'query': 'what is secret number',
            'mode': 'graph+vector',
            'items': [
                {
                    'entity_type': 'Note',
                    'entity_id': 'note-123',
                    'source_type': 'note.body',
                    'snippet': 'The secret number is 99.',
                    'vector_similarity': 0.91,
                    'final_score': 0.93,
                }
            ],
        },
    )

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'what is secret number',
            'session_id': 'test-session-grounded-lookup',
            'history': [],
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload['ok'] is True
    sent_instruction = str(captured['instruction'])
    assert 'Project knowledge evidence' in sent_instruction
    assert 'The secret number is 99.' in sent_instruction
    assert 'could not verify it from project knowledge' in sent_instruction


def test_agents_chat_endpoint_uses_normalized_multilingual_knowledge_query(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    captured: dict[str, object] = {}
    knowledge_queries: list[str] = []

    def _fake_execute_task_automation(**kwargs):
        captured.update(kwargs)
        return AutomationOutcome(action='comment', summary='The secret number is 99.', comment=None, usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)
    monkeypatch.setattr(
        agents_api,
        '_classify_chat_instruction_intents',
        lambda **_kwargs: {
            'execution_intent': False,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
            'project_knowledge_lookup_intent': False,
            'grounded_answer_required': False,
            'workflow_scope': 'unknown',
            'execution_mode': 'unknown',
            'deploy_requested': False,
            'docker_compose_requested': False,
            'requested_port': None,
            'project_name_provided': False,
            'task_completion_requested': False,
            'reason': 'Classifier missed multilingual factual lookup.',
        },
    )
    monkeypatch.setattr(
        agents_api,
        '_normalize_chat_knowledge_lookup_query',
        lambda **_kwargs: {
            'project_knowledge_lookup_intent': True,
            'grounded_answer_required': True,
            'input_language': 'bs',
            'english_retrieval_query': 'secret number',
            'native_retrieval_query': 'tajni broj',
            'reasoning': 'Bosnian factual lookup normalized to English.',
        },
    )

    def _fake_search_project_knowledge_query(**kwargs):
        knowledge_queries.append(str(kwargs.get('query') or ''))
        query = str(kwargs.get('query') or '')
        if query == 'secret number':
            return {
                'project_id': project_id,
                'query': query,
                'mode': 'graph+vector',
                'items': [
                    {
                        'entity_type': 'Note',
                        'entity_id': 'note-123',
                        'source_type': 'note.body',
                        'snippet': 'The secret number is 99.',
                        'vector_similarity': 0.91,
                        'final_score': 0.93,
                    }
                ],
            }
        return {
            'project_id': project_id,
            'query': query,
            'mode': 'graph+vector',
            'items': [],
        }

    monkeypatch.setattr(agents_api, 'search_project_knowledge_query', _fake_search_project_knowledge_query)

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'mozes li mi reci koji je tajni broj?',
            'session_id': 'test-session-grounded-lookup-bs',
            'history': [],
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload['ok'] is True
    assert 'secret number' in knowledge_queries
    sent_instruction = str(captured['instruction'])
    assert 'Project knowledge evidence' in sent_instruction
    assert 'The secret number is 99.' in sent_instruction


def test_agents_chat_stream_project_setup_starter_returns_immediate_question(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api

    def _unexpected_executor(*args, **kwargs):
        raise AssertionError('execute_task_automation_stream should not run for starter fast-path')

    monkeypatch.setattr(agents_api, 'execute_task_automation_stream', _unexpected_executor)
    monkeypatch.setattr(
        agents_api,
        '_classify_chat_instruction_intents',
        lambda **_: {
            'execution_intent': False,
            'execution_kickoff_intent': False,
            'project_creation_intent': True,
            'workflow_scope': 'unknown',
            'execution_mode': 'setup_only',
            'deploy_requested': False,
            'docker_compose_requested': False,
            'requested_port': None,
            'project_name_provided': False,
            'reason': 'Project setup requested without an explicit project name.',
        },
    )

    res = client.post(
        '/api/agents/chat/stream',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': (
                'Help me set up a new project in chat. '
                'Use setup_project_orchestration and, if inputs are missing, '
                'ask only the next missing question from the tool response.'
            ),
            'session_id': 'starter-fast-path',
            'history': [],
        },
    )
    assert res.status_code == 200
    lines = [line for line in res.text.splitlines() if line.strip()]
    assert lines
    event = json.loads(lines[-1])
    response = event.get('response') if isinstance(event, dict) else {}
    assert isinstance(response, dict)
    assert response.get('ok') is True
    assert response.get('summary') == 'What should the new project be named?'
    assert response.get('comment') is None


def test_agents_chat_stream_setup_flow_asks_single_missing_question_per_turn_and_finishes(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    call_state = {"count": 0}

    def _fake_execute_task_automation_stream(**_kwargs):
        call_state["count"] += 1
        if call_state["count"] == 1:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "missing_setup_inputs",
                        "next_input_key": "name",
                        "next_question": "What should the new project be named?",
                        "missing_inputs": [{"key": "name", "question": "What should the new project be named?"}],
                    }
                )
            )
        if call_state["count"] == 2:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "missing_setup_inputs",
                        "next_input_key": "enable_team_mode",
                        "next_question": "Do you want Team Mode for this project?",
                        "missing_inputs": [
                            {"key": "enable_team_mode", "question": "Do you want Team Mode for this project?"}
                        ],
                    }
                )
            )
        if call_state["count"] == 3:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "missing_setup_inputs",
                        "next_input_key": "docker_port",
                        "next_question": "Which port should Docker Compose use?",
                        "missing_inputs": [{"key": "docker_port", "question": "Which port should Docker Compose use?"}],
                    }
                )
            )
        return AutomationOutcome(
            action='comment',
            summary='[Project: Tetris](?tab=projects&project=proj-123)\n\nKickoff required: Yes',
            comment=None,
            usage=None,
        )

    monkeypatch.setattr(agents_api, 'execute_task_automation_stream', _fake_execute_task_automation_stream)
    monkeypatch.setattr(
        agents_api,
        '_classify_chat_instruction_intents',
        lambda **_kwargs: {
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': True,
        },
    )

    session_id = 'setup-stream-regression-1'

    def _stream_response_summary(payload: dict) -> tuple[str | None, str | None]:
        res = client.post('/api/agents/chat/stream', json=payload)
        assert res.status_code == 200
        lines = [line for line in res.text.splitlines() if line.strip()]
        assert lines
        event = json.loads(lines[-1])
        response = event.get('response') if isinstance(event, dict) else {}
        assert isinstance(response, dict)
        return response.get('summary'), response.get('comment')

    s1, c1 = _stream_response_summary(
        {
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Help me set up a new project.',
            'session_id': session_id,
            'history': [],
        }
    )
    assert s1 == 'What should the new project be named?'
    assert c1 is None

    s2, c2 = _stream_response_summary(
        {
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Tetris web game',
            'session_id': session_id,
            'history': [{'role': 'user', 'content': 'Help me set up a new project.'}],
        }
    )
    assert s2 == 'Do you want Team Mode for this project?'
    assert c2 is None

    s3, c3 = _stream_response_summary(
        {
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'yes and docker compose',
            'session_id': session_id,
            'history': [{'role': 'user', 'content': 'Tetris web game'}],
        }
    )
    assert s3 == 'Which port should Docker Compose use?'
    assert c3 is None

    s4, _c4 = _stream_response_summary(
        {
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': '6768',
            'session_id': session_id,
            'history': [{'role': 'user', 'content': 'yes and docker compose'}],
        }
    )
    assert '?tab=projects&project=proj-123' in str(s4 or '')
    assert 'Kickoff required: Yes' in str(s4 or '')


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
    monkeypatch.setattr(
        agents_api,
        '_classify_chat_instruction_intents',
        lambda **_kwargs: {
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
        },
    )

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
        agents_api,
        '_classify_chat_instruction_intents',
        lambda **_kwargs: {
            'execution_intent': False,
            'execution_kickoff_intent': False,
            'project_creation_intent': True,
        },
    )
    monkeypatch.setattr(
        agents_api,
        '_classify_chat_instruction_intents',
        lambda **_kwargs: {
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
        },
    )
    monkeypatch.setattr(
        agents_api,
        '_classify_chat_instruction_intents',
        lambda **_kwargs: {
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
        },
    )
    monkeypatch.setattr(
        mcp_registry,
        '_get_rows',
        lambda force_refresh=False: [
            {
                'name': 'constructos-tools',
                'display_name': 'Constructos Tools',
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
    assert captured['mcp_servers'] == ['constructos-tools', 'jira', 'github']
    assert captured['timeout_seconds'] == 0


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
        agents_api,
        '_classify_chat_instruction_intents',
        lambda **_kwargs: {
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
        },
    )
    monkeypatch.setattr(
        mcp_registry,
        '_get_rows',
        lambda force_refresh=False: [
            {
                'name': 'constructos-tools',
                'display_name': 'Constructos Tools',
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
    assert captured['mcp_servers'] == ['constructos-tools', 'github']


def test_mcp_registry_honors_disabled_flag_from_config_when_runtime_list_unavailable(monkeypatch):
    from features.agents import mcp_registry

    monkeypatch.setattr(
        mcp_registry,
        "_load_mcp_servers_from_config",
        lambda: {
            "constructos-tools": {"url": "http://localhost:8091/mcp"},
            "github": {"url": "https://api.githubcopilot.com/mcp/", "enabled": False},
            "jira": {"url": "http://jira-mcp:9000/mcp", "enabled": False},
        },
    )
    monkeypatch.setattr(mcp_registry, "_run_codex_mcp_list_json", lambda: [])

    rows = mcp_registry._discover_rows_uncached()
    by_name = {str(row.get("name") or ""): row for row in rows}

    assert by_name["constructos-tools"]["enabled"] is True
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
    monkeypatch.setattr(
        agents_api,
        '_classify_chat_instruction_intents',
        lambda **_kwargs: {
            'execution_intent': False,
            'execution_kickoff_intent': False,
            'project_creation_intent': True,
        },
    )

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
            'mcp_servers': ['constructos-tools'],
        },
    )
    assert patched_mcp.status_code == 200
    patched_payload = patched_mcp.json()
    assert patched_payload['mcp_servers'] == ['constructos-tools']
    assert patched_payload['session_attachment_refs'][0]['path'] == attachment_ref['path']

    listed = client.get(
        '/api/chat/sessions',
        params={'workspace_id': ws_id},
    )
    assert listed.status_code == 200
    sessions = listed.json()
    target = next((item for item in sessions if item.get('id') == session_id), None)
    assert target is not None
    assert target['mcp_servers'] == ['constructos-tools']
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


def test_agents_chat_endpoint_reuses_session_attachment_context_on_resume(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    session_id = 'chat-session-context-reuse-test'

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome
    from shared.models import ChatSession, SessionLocal

    captured: dict[str, object] = {}

    def _fake_execute_task_automation(**kwargs):
        captured.update(kwargs)
        return AutomationOutcome(action='comment', summary='ok', comment=None, usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)
    monkeypatch.setattr(
        agents_api,
        '_load_chat_session_codex_state',
        lambda **_kwargs: ('codex-thread-1', True),
    )

    created = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Create session for attachment reuse',
            'session_id': session_id,
            'history': [],
        },
    )
    assert created.status_code == 200

    uploaded = client.post(
        '/api/attachments/upload',
        data={'workspace_id': ws_id, 'project_id': project_id},
        files={'file': ('session-reuse.txt', BytesIO(b'reused attachment payload text'), 'text/plain')},
    )
    assert uploaded.status_code == 200
    attachment_ref = uploaded.json()

    with SessionLocal() as db:
        session = db.query(ChatSession).filter(ChatSession.workspace_id == ws_id, ChatSession.session_key == session_id).one()
        session.session_attachment_refs = json.dumps(
            [
                {
                    'path': attachment_ref['path'],
                    'name': attachment_ref.get('name') or 'session-reuse.txt',
                    'mime_type': attachment_ref.get('mime_type') or 'text/plain',
                    'size_bytes': attachment_ref.get('size_bytes') or 0,
                    'checksum': 'seeded-checksum',
                    'extraction_status': 'extracted',
                    'extracted_text': 'reused attachment payload text',
                }
            ]
        )
        db.commit()

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Continue with pinned session attachment',
            'session_id': session_id,
            'history': [],
        },
    )
    assert res.status_code == 200
    instruction = str(captured.get('instruction') or '')
    assert 'Attached file context:' in instruction
    assert '(reused from session memory' in instruction
    assert 'reused attachment payload text' not in instruction


def test_metrics_chat_prompt_segments_endpoint_aggregates_usage(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    def _fake_execute_task_automation(**_kwargs):
        return AutomationOutcome(
            action='comment',
            summary='ok',
            comment=None,
            usage={
                'input_tokens': 1200,
                'output_tokens': 80,
                'prompt_mode': 'resume',
                'prompt_segment_chars': {
                    'instruction': 300,
                    'fresh_memory_snapshot': 450,
                },
            },
        )

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)

    created = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Seed metrics',
            'session_id': 'chat-metrics-segment-test',
        },
    )
    assert created.status_code == 200

    metrics = client.get(
        '/api/metrics/chat-prompt-segments',
        params={'workspace_id': ws_id, 'project_id': project_id, 'limit': 20},
    )
    assert metrics.status_code == 200
    payload = metrics.json()
    assert payload['runs_scanned'] >= 1
    assert payload['runs_analyzed'] >= 1
    assert int(payload['prompt_mode_counts'].get('resume') or 0) >= 1
    assert int(payload['segment_totals_chars'].get('instruction') or 0) >= 300
    assert int(payload['segment_totals_chars'].get('fresh_memory_snapshot') or 0) >= 450


def test_metrics_task_automation_prompt_segments_endpoint_aggregates_usage(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created_task = client.post(
        '/api/tasks',
        json={
            'title': 'Task automation metrics seed',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    assert created_task.status_code == 200
    task_id = created_task.json()['id']

    from features.tasks import api as tasks_api
    from features.agents.executor import AutomationOutcome

    def _fake_execute_task_automation_stream(**_kwargs):
        return AutomationOutcome(
            action='comment',
            summary='ok',
            comment='done',
            usage={
                'input_tokens': 1500,
                'output_tokens': 120,
                'prompt_mode': 'resume',
                'prompt_segment_chars': {
                    'instruction': 500,
                    'graph_context': 700,
                },
            },
            codex_session_id='task-metrics-thread-1',
            resume_attempted=True,
            resume_succeeded=True,
            resume_fallback_used=False,
        )

    monkeypatch.setattr(tasks_api, 'execute_task_automation_stream', _fake_execute_task_automation_stream)

    run = client.post(
        f'/api/tasks/{task_id}/automation/stream',
        json={'instruction': 'Seed task prompt metrics'},
    )
    assert run.status_code == 200

    metrics = client.get(
        '/api/metrics/task-automation-prompt-segments',
        params={'workspace_id': ws_id, 'project_id': project_id, 'limit': 20},
    )
    assert metrics.status_code == 200
    payload = metrics.json()
    assert payload['runs_scanned'] >= 1
    assert payload['runs_analyzed'] >= 1
    assert int(payload['prompt_mode_counts'].get('resume') or 0) >= 1
    assert int(payload['segment_totals_chars'].get('instruction') or 0) >= 500
    assert int(payload['segment_totals_chars'].get('graph_context') or 0) >= 700


def test_task_automation_stream_reuses_codex_session_after_non_resume_first_run(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created_task = client.post(
        '/api/tasks',
        json={
            'title': 'Task codex resume carry-over',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    assert created_task.status_code == 200
    task_id = created_task.json()['id']

    from features.tasks import api as tasks_api
    from features.agents.executor import AutomationOutcome

    captured_codex_session_ids: list[str | None] = []

    def _fake_execute_task_automation_stream(**kwargs):
        captured_codex_session_ids.append(kwargs.get('codex_session_id'))
        return AutomationOutcome(
            action='comment',
            summary='ok',
            comment='done',
            usage={
                'prompt_mode': 'full',
                'prompt_segment_chars': {'instruction': 100},
            },
            codex_session_id='task-thread-carry-over-1',
            resume_attempted=False,
            resume_succeeded=False,
            resume_fallback_used=False,
        )

    monkeypatch.setattr(tasks_api, 'execute_task_automation_stream', _fake_execute_task_automation_stream)

    first = client.post(
        f'/api/tasks/{task_id}/automation/stream',
        json={'instruction': 'First run'},
    )
    assert first.status_code == 200

    second = client.post(
        f'/api/tasks/{task_id}/automation/stream',
        json={'instruction': 'Second run'},
    )
    assert second.status_code == 200

    assert len(captured_codex_session_ids) >= 2
    assert captured_codex_session_ids[0] in {None, ''}
    assert captured_codex_session_ids[1] == 'task-thread-carry-over-1'


def test_agents_chat_resume_dedupes_cross_session_updates_between_turns(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    session_id = 'chat-resume-cross-update-dedupe'

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    captured_instructions: list[str] = []

    def _fake_execute_task_automation(**kwargs):
        captured_instructions.append(str(kwargs.get('instruction') or ''))
        return AutomationOutcome(action='comment', summary='ok', comment=None, usage={})

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)
    monkeypatch.setattr(
        agents_api,
        '_load_chat_session_codex_state',
        lambda **_kwargs: ('codex-thread-1', True),
    )
    monkeypatch.setattr(
        agents_api,
        '_load_cross_session_recent_updates',
        lambda **_kwargs: [
            {
                'update_id': 'upd-001',
                'role': 'assistant',
                'content': 'Important change from another session.',
                'source_session_key': 'other-session',
            }
        ],
    )

    first = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'First resume turn',
            'session_id': session_id,
        },
    )
    assert first.status_code == 200

    second = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Second resume turn',
            'session_id': session_id,
        },
    )
    assert second.status_code == 200

    third = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Third resume turn',
            'session_id': session_id,
        },
    )
    assert third.status_code == 200

    assert len(captured_instructions) >= 3
    assert 'Important change from another session.' in captured_instructions[0]
    assert 'Important change from another session.' not in captured_instructions[1]
    assert 'Important change from another session.' not in captured_instructions[2]


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

    captured: dict[str, object] = {}

    def _fake_execute_task_automation_stream(**kwargs):
        captured.update(kwargs)
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
    assert res.headers.get('x-accel-buffering', '').lower() == 'no'
    assert 'no-cache' in str(res.headers.get('cache-control', '')).lower()
    assert captured['timeout_seconds'] == 0
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


def test_agents_chat_stream_persists_failure_context_after_partial_output(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    session_key = 'chat-stream-partial-failure-test'

    from features.agents import api as agents_api

    def _fake_execute_task_automation_stream(**kwargs):
        on_event = kwargs.get('on_event')
        if callable(on_event):
            on_event({'type': 'assistant_text', 'delta': 'Progress before failure.'})
        raise RuntimeError()

    monkeypatch.setattr(agents_api, 'execute_task_automation_stream', _fake_execute_task_automation_stream)

    res = client.post(
        '/api/agents/chat/stream',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Trigger stream failure',
            'session_id': session_key,
        },
    )
    assert res.status_code == 200
    lines = [line for line in (res.text or '').splitlines() if line.strip()]
    assert len(lines) >= 1
    final_payload = json.loads(lines[-1])
    assert str(final_payload.get('type') or '') == 'final'
    response = final_payload.get('response') or {}
    assert response.get('ok') is False
    assert 'Codex failed to complete the request' in str(response.get('summary') or '')
    assert 'RuntimeError' in str(response.get('comment') or '')

    from shared.models import ChatMessage, ChatSession, SessionLocal

    with SessionLocal() as db:
        session_row = (
            db.query(ChatSession)
            .filter(ChatSession.workspace_id == ws_id, ChatSession.session_key == session_key)
            .first()
        )
        assert session_row is not None
        assistant_message = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_row.id, ChatMessage.role == 'assistant')
            .order_by(ChatMessage.created_at.desc())
            .first()
        )
        assert assistant_message is not None
        content = str(assistant_message.content or '')
        assert 'Progress before failure.' in content
        assert 'Codex failed to complete the request' in content
        assert 'RuntimeError' in content


def test_agents_chat_execution_kickoff_dispatches_team_lead_and_skips_long_run(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    members = client.get(f"/api/projects/{project_id}/members")
    assert members.status_code == 200
    lead = team["lead"]

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead kickoff task",
            "status": "To do",
            "assignee_id": lead,
            "assigned_agent_code": "lead-a",
            "instruction": "Lead coordination task.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    from features.agents import api as agents_api

    def _should_not_run_long_automation(**_kwargs):
        raise AssertionError("execute_task_automation should not run for execution kickoff dispatch")

    monkeypatch.setattr(agents_api, "execute_task_automation", _should_not_run_long_automation)
    monkeypatch.setattr(
        agents_api,
        "_classify_chat_instruction_intents",
        lambda **_kwargs: {
            "execution_intent": True,
            "execution_kickoff_intent": True,
            "project_creation_intent": False,
        },
    )

    kicked = client.post(
        "/api/agents/chat",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "instruction": 'Start implementation of "Demo 99" project.',
        },
    )
    assert kicked.status_code == 200
    payload = kicked.json()
    assert payload["action"] == "comment"
    assert "kickoff" in str(payload["summary"] or "").lower()

    automation_status = client.get(f"/api/tasks/{lead_task_id}/automation")
    assert automation_status.status_code == 200
    status_payload = automation_status.json()
    assert status_payload["automation_state"] in {"queued", "running", "completed"}
    assert status_payload["last_requested_source"] in {"manual", "schedule", None}

    from shared.models import Notification, SessionLocal

    with SessionLocal() as db:
        created = (
            db.query(Notification)
            .filter(
                Notification.workspace_id == ws_id,
                Notification.project_id == project_id,
                Notification.user_id == bootstrap["current_user"]["id"],
            )
            .order_by(Notification.created_at.desc())
            .first()
        )
        assert created is not None
        assert "kickoff dispatched" in str(created.message or "").lower()


def test_team_mode_kickoff_success_queues_highest_priority_developer_work(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    from shared.models import Project, SessionLocal

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.automation_max_parallel_tasks = 1
        db.commit()

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead kickoff task",
            "status": "To do",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Lead coordination task.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    low_dev = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Low priority developer task",
            "status": "To do",
            "priority": "Low",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement low priority task.",
        },
    )
    assert low_dev.status_code == 200
    low_dev_id = low_dev.json()["id"]

    high_dev = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "High priority developer task",
            "status": "To do",
            "priority": "High",
            "assignee_id": team["dev2"],
            "assigned_agent_code": "dev-b",
            "instruction": "Implement high priority task.",
        },
    )
    assert high_dev.status_code == 200
    high_dev_id = high_dev.json()["id"]

    from features.agents.executor import AutomationOutcome
    from features.agents.runner import QueuedAutomationRun, _record_automation_success

    _record_automation_success(
        QueuedAutomationRun(
            task_id=lead_task_id,
            workspace_id=ws_id,
            project_id=project_id,
            title="Lead kickoff task",
            description="",
            status="To do",
            instruction=f"Team Mode kickoff for project {project_id}.",
            request_source="manual",
            is_scheduled_run=False,
            trigger_task_id=None,
            trigger_from_status=None,
            trigger_to_status=None,
            triggered_at=None,
            actor_user_id=team["lead"],
            execution_kickoff_intent=True,
            workflow_scope="team_mode",
            execution_mode="kickoff_only",
        ),
        outcome=AutomationOutcome(
            action="comment",
            summary="Kickoff dispatch completed.",
            comment="Lead reviewed the queue and dispatched the first developer task.",
        ),
    )

    high_status = client.get(f"/api/tasks/{high_dev_id}/automation")
    assert high_status.status_code == 200
    high_payload = high_status.json()
    assert high_payload["automation_state"] in {"queued", "running", "completed"}
    assert high_payload["last_requested_source"] == "lead_kickoff_dispatch"
    high_dispatch = high_payload.get("last_dispatch_decision") or {}
    assert high_dispatch.get("source") == "lead_kickoff_dispatch"
    assert high_dispatch.get("priority") == "High"
    assert high_dispatch.get("slot") == "dev-b"

    low_status = client.get(f"/api/tasks/{low_dev_id}/automation")
    assert low_status.status_code == 200
    low_payload = low_status.json()
    assert low_payload["automation_state"] == "idle"


def test_team_mode_kickoff_success_detects_alternate_lead_first_instruction_wording(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    from shared.models import Project, SessionLocal

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.automation_max_parallel_tasks = 1
        db.commit()

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead kickoff task",
            "status": "To do",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Lead coordination task.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer kickoff task",
            "status": "To do",
            "priority": "High",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement the kickoff task.",
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    from features.agents.executor import AutomationOutcome
    from features.agents.runner import QueuedAutomationRun, _record_automation_success

    _record_automation_success(
        QueuedAutomationRun(
            task_id=lead_task_id,
            workspace_id=ws_id,
            project_id=project_id,
            title="Lead kickoff task",
            description="",
            status="To do",
            instruction=(
                f"Kickoff execution for the Demo project in lead-first mode. "
                "Review project state, request/coordinate Developer work on the active Dev task, "
                "then manage QA handoff and deployment readiness."
            ),
            request_source="manual",
            is_scheduled_run=False,
            trigger_task_id=None,
            trigger_from_status=None,
            trigger_to_status=None,
            triggered_at=None,
            actor_user_id=team["lead"],
            execution_kickoff_intent=True,
            workflow_scope="team_mode",
            execution_mode="kickoff_only",
        ),
        outcome=AutomationOutcome(
            action="comment",
            summary="Kickoff dispatch completed.",
            comment="Lead reviewed the queue and dispatched the first developer task.",
        ),
    )

    dev_status = client.get(f"/api/tasks/{dev_task_id}/automation")
    assert dev_status.status_code == 200
    dev_payload = dev_status.json()
    assert dev_payload["automation_state"] in {"queued", "running", "completed"}
    assert dev_payload["last_requested_source"] == "lead_kickoff_dispatch"


def test_team_mode_kickoff_can_dispatch_description_only_developer_task(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    from shared.models import Project, SessionLocal

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.automation_max_parallel_tasks = 1
        db.commit()

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead kickoff task",
            "status": "To do",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Lead coordination task.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Description only developer task",
            "status": "To do",
            "priority": "High",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "description": "Implement the playable Tetris gameplay loop and responsive UI.",
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]
    assert dev_task.json()["instruction"] == "Implement the playable Tetris gameplay loop and responsive UI."

    from features.agents.executor import AutomationOutcome
    from features.agents.runner import QueuedAutomationRun, _record_automation_success

    _record_automation_success(
        QueuedAutomationRun(
            task_id=lead_task_id,
            workspace_id=ws_id,
            project_id=project_id,
            title="Lead kickoff task",
            description="",
            status="To do",
            instruction="Kickoff Team Mode execution for the project.",
            request_source="manual",
            is_scheduled_run=False,
            trigger_task_id=None,
            trigger_from_status=None,
            trigger_to_status=None,
            triggered_at=None,
            actor_user_id=team["lead"],
            execution_kickoff_intent=True,
            workflow_scope="team_mode",
            execution_mode="kickoff_only",
        ),
        outcome=AutomationOutcome(
            action="comment",
            summary="Kickoff dispatch completed.",
            comment="Lead dispatched the first Developer task.",
        ),
    )

    dev_status = client.get(f"/api/tasks/{dev_task_id}/automation")
    assert dev_status.status_code == 200
    payload = dev_status.json()
    assert payload["automation_state"] in {"queued", "running", "completed"}
    assert payload["last_requested_source"] == "lead_kickoff_dispatch"


def test_team_mode_developer_completion_backfills_next_developer_task(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    from shared.models import Project, SessionLocal

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.automation_max_parallel_tasks = 1
        db.commit()

    active_dev = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Active developer task",
            "status": "In Progress",
            "priority": "High",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement the active task.",
            "external_refs": [
                {
                    "url": "https://example.invalid/commit/abc1234",
                    "label": "task/abc1234-implement-active",
                }
            ],
        },
    )
    assert active_dev.status_code == 200
    active_dev_id = active_dev.json()["id"]

    waiting_dev = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Waiting developer task",
            "status": "To do",
            "priority": "Low",
            "assignee_id": team["dev2"],
            "assigned_agent_code": "dev-b",
            "instruction": "Implement the waiting task.",
        },
    )
    assert waiting_dev.status_code == 200
    waiting_dev_id = waiting_dev.json()["id"]

    from features.agents.executor import AutomationOutcome
    import features.agents.runner as runner_module
    from features.agents.runner import QueuedAutomationRun, _record_automation_success

    before_sha = "1111111111111111111111111111111111111111"
    after_sha = "2222222222222222222222222222222222222222"
    original_inspect_handoff = runner_module._inspect_committed_task_branch_handoff
    original_merge_to_main = runner_module._merge_current_task_branch_to_main
    original_merge_to_main = runner_module._merge_current_task_branch_to_main
    original_merge_to_main = runner_module._merge_current_task_branch_to_main
    original_merge_to_main = runner_module._merge_current_task_branch_to_main
    original_merge_to_main = runner_module._merge_current_task_branch_to_main
    original_merge_to_main = runner_module._merge_current_task_branch_to_main

    def _fake_inspect_handoff(git_evidence):
        result = original_inspect_handoff(git_evidence)
        result.update(
            {
                "branch_name": "task/abc1234-implement-active",
                "branch_exists": True,
                "branch_head_sha": after_sha,
                "main_head_sha": before_sha,
                "branch_differs_from_main": True,
                "after_head_sha": after_sha,
                "after_on_task_branch": True,
                "after_is_dirty": False,
            }
        )
        return result

    def _fake_merge_to_main(**_kwargs):
        return {
            "ok": True,
            "merge_sha": after_sha,
            "merged_at": "2026-03-16T15:00:00Z",
            "external_refs": [
                {"url": f"commit:{after_sha}", "title": "task commit"},
                {"url": "task/merged-increment", "title": "task branch"},
                {"url": f"merge:main:{after_sha}", "title": "merged to main"},
            ],
        }

    runner_module._inspect_committed_task_branch_handoff = _fake_inspect_handoff
    runner_module._merge_current_task_branch_to_main = _fake_merge_to_main
    try:
        _record_automation_success(
            QueuedAutomationRun(
                task_id=active_dev_id,
                workspace_id=ws_id,
                project_id=project_id,
                title="Active developer task",
                description="",
                status="In Progress",
                instruction="Implement the active task.",
                request_source="manual",
                is_scheduled_run=False,
                trigger_task_id=None,
                trigger_from_status=None,
                trigger_to_status=None,
                triggered_at=None,
                actor_user_id=team["dev1"],
            ),
            outcome=AutomationOutcome(
                action="comment",
                summary="Implemented on task branch task/abc1234-implement-active with commit 2222222.",
                comment=None,
                execution_outcome_contract={
                    "contract_version": 1,
                    "files_changed": ["src/game/tetris.ts"],
                    "tests_run": False,
                    "tests_passed": False,
                    "commit_sha": after_sha,
                    "branch": "task/abc1234-implement-active",
                    "artifacts": [],
                },
                usage={
                    "git_evidence": {
                        "repo_root": str(tmp_path / "repo-placeholder"),
                        "task_branch": "task/abc1234-implement-active",
                        "before": {"head_sha": before_sha},
                        "after": {"head_sha": after_sha, "on_task_branch": True, "is_dirty": False},
                    }
                },
            ),
        )
    finally:
        runner_module._inspect_committed_task_branch_handoff = original_inspect_handoff
        runner_module._merge_current_task_branch_to_main = original_merge_to_main
        runner_module._merge_current_task_branch_to_main = original_merge_to_main

    active_status = client.get(f"/api/tasks/{active_dev_id}")
    assert active_status.status_code == 200
    active_payload = active_status.json()
    assert active_payload["status"] == "In Progress"
    assert active_payload["assigned_agent_code"] == "lead-a"
    assert active_payload["assignee_id"] == team["lead"]

    waiting_status = client.get(f"/api/tasks/{waiting_dev_id}/automation")
    assert waiting_status.status_code == 200
    waiting_payload = waiting_status.json()
    assert waiting_payload["automation_state"] in {"queued", "running", "completed"}
    assert waiting_payload["last_requested_source"] == "runner_orchestrator"
    waiting_dispatch = waiting_payload.get("last_dispatch_decision") or {}
    assert waiting_dispatch.get("source") == "runner_orchestrator"
    assert waiting_dispatch.get("priority") == "Low"
    assert waiting_dispatch.get("slot") == "dev-b"


def test_team_mode_developer_completion_enters_human_review_when_project_requires_code_review(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    plugin_payload = client.get(f"/api/projects/{project_id}/plugins/team_mode")
    assert plugin_payload.status_code == 200
    config = plugin_payload.json()["config"]
    config["review_policy"] = {"require_code_review": True}
    applied = client.post(
        f"/api/projects/{project_id}/plugins/team_mode/apply",
        json={"config": config, "enabled": True},
    )
    assert applied.status_code == 200

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer implementation with required review",
            "status": "In Progress",
            "priority": "High",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement the gameplay changes on the task branch.",
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    from features.agents.executor import AutomationOutcome
    import features.agents.runner as runner_module
    from features.agents.runner import QueuedAutomationRun, _record_automation_success

    before_sha = "1111111111111111111111111111111111111111"
    after_sha = "2222222222222222222222222222222222222222"
    original_inspect_handoff = runner_module._inspect_committed_task_branch_handoff
    original_merge_to_main = runner_module._merge_current_task_branch_to_main

    def _fake_inspect_handoff(git_evidence):
        result = original_inspect_handoff(git_evidence)
        result.update(
            {
                "branch_name": "task/dev-review-required",
                "branch_exists": True,
                "branch_head_sha": after_sha,
                "main_head_sha": before_sha,
                "branch_ahead_of_main": True,
                "branch_differs_from_main": True,
                "after_head_sha": after_sha,
                "after_on_task_branch": True,
                "after_is_dirty": False,
            }
        )
        return result

    def _fake_merge_to_main(**_kwargs):
        return {
            "ok": True,
            "merge_sha": after_sha,
            "merged_at": "2026-03-16T15:00:00Z",
            "external_refs": [
                {"url": f"commit:{after_sha}", "title": "task commit"},
                {"url": "task/merged-increment", "title": "task branch"},
                {"url": f"merge:main:{after_sha}", "title": "merged to main"},
            ],
        }

    runner_module._inspect_committed_task_branch_handoff = _fake_inspect_handoff
    runner_module._merge_current_task_branch_to_main = _fake_merge_to_main
    try:
        _record_automation_success(
            QueuedAutomationRun(
                task_id=dev_task_id,
                workspace_id=ws_id,
                project_id=project_id,
                title="Developer implementation with required review",
                description="",
                status="In Progress",
                instruction="Implement the gameplay changes on the task branch.",
                request_source="manual",
                is_scheduled_run=False,
                trigger_task_id=None,
                trigger_from_status=None,
                trigger_to_status=None,
                triggered_at=None,
                actor_user_id=team["dev1"],
            ),
            outcome=AutomationOutcome(
                action="comment",
                summary="Implemented on task branch task/dev-review-required with commit 2222222.",
                comment=None,
                execution_outcome_contract={
                    "contract_version": 1,
                    "files_changed": ["src/game/tetris.ts"],
                    "tests_run": False,
                    "tests_passed": False,
                    "commit_sha": after_sha,
                    "branch": "task/dev-review-required",
                    "artifacts": [],
                },
                usage={
                    "git_evidence": {
                        "repo_root": str(tmp_path / "repo-placeholder"),
                        "task_branch": "task/dev-review-required",
                        "before": {"head_sha": before_sha},
                        "after": {"head_sha": after_sha, "on_task_branch": True, "is_dirty": False},
                    }
                },
            ),
        )
    finally:
        runner_module._inspect_committed_task_branch_handoff = original_inspect_handoff
        runner_module._merge_current_task_branch_to_main = original_merge_to_main

    task_payload = client.get(f"/api/tasks/{dev_task_id}").json()
    assert task_payload["status"] == "In Review"
    assert task_payload["assignee_id"] == "00000000-0000-0000-0000-000000000001"
    assert task_payload["assigned_agent_code"] is None


def test_team_mode_developer_completion_assigns_configured_reviewer_when_present(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    reviewer_id = team["lead"]

    plugin_payload = client.get(f"/api/projects/{project_id}/plugins/team_mode")
    assert plugin_payload.status_code == 200
    config = plugin_payload.json()["config"]
    config["review_policy"] = {
        "require_code_review": True,
        "reviewer_user_id": reviewer_id,
    }
    applied = client.post(
        f"/api/projects/{project_id}/plugins/team_mode/apply",
        json={"config": config, "enabled": True},
    )
    assert applied.status_code == 200

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer implementation with configured reviewer",
            "status": "In Progress",
            "priority": "High",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement the gameplay changes on the task branch.",
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    from features.agents.executor import AutomationOutcome
    import features.agents.runner as runner_module
    from features.agents.runner import QueuedAutomationRun, _record_automation_success

    before_sha = "1111111111111111111111111111111111111111"
    after_sha = "2222222222222222222222222222222222222222"
    original_inspect_handoff = runner_module._inspect_committed_task_branch_handoff
    original_merge_to_main = runner_module._merge_current_task_branch_to_main

    def _fake_inspect_handoff(git_evidence):
        result = original_inspect_handoff(git_evidence)
        result.update(
            {
                "branch_name": "task/dev-configured-reviewer",
                "branch_exists": True,
                "branch_head_sha": after_sha,
                "main_head_sha": before_sha,
                "branch_ahead_of_main": True,
                "branch_differs_from_main": True,
                "after_head_sha": after_sha,
                "after_on_task_branch": True,
                "after_is_dirty": False,
            }
        )
        return result

    def _fake_merge_to_main(**_kwargs):
        return {
            "ok": True,
            "merge_sha": after_sha,
            "merged_at": "2026-03-16T15:00:00Z",
            "external_refs": [],
        }

    runner_module._inspect_committed_task_branch_handoff = _fake_inspect_handoff
    runner_module._merge_current_task_branch_to_main = _fake_merge_to_main
    try:
        _record_automation_success(
            QueuedAutomationRun(
                task_id=dev_task_id,
                workspace_id=ws_id,
                project_id=project_id,
                title="Developer implementation with configured reviewer",
                description="",
                status="In Progress",
                instruction="Implement the gameplay changes on the task branch.",
                request_source="manual",
                is_scheduled_run=False,
                trigger_task_id=None,
                trigger_from_status=None,
                trigger_to_status=None,
                triggered_at=None,
                actor_user_id=team["dev1"],
            ),
            outcome=AutomationOutcome(
                action="comment",
                summary="Implemented on task branch task/dev-configured-reviewer with commit 2222222.",
                comment=None,
                execution_outcome_contract={
                    "contract_version": 1,
                    "files_changed": ["src/game/tetris.ts"],
                    "tests_run": False,
                    "tests_passed": False,
                    "commit_sha": after_sha,
                    "branch": "task/dev-configured-reviewer",
                    "artifacts": [],
                },
                usage={
                    "git_evidence": {
                        "repo_root": str(tmp_path / "repo-placeholder"),
                        "task_branch": "task/dev-configured-reviewer",
                        "before": {"head_sha": before_sha},
                        "after": {"head_sha": after_sha, "on_task_branch": True, "is_dirty": False},
                    }
                },
            ),
        )
    finally:
        runner_module._inspect_committed_task_branch_handoff = original_inspect_handoff
        runner_module._merge_current_task_branch_to_main = original_merge_to_main

    task_payload = client.get(f"/api/tasks/{dev_task_id}").json()
    assert task_payload["status"] == "In Review"
    assert task_payload["assignee_id"] == reviewer_id
    assert task_payload["assigned_agent_code"] is None


def test_team_mode_review_approval_requeues_task_to_developer_for_merge(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Reviewable implementation task",
            "status": "In Review",
            "priority": "High",
            "assignee_id": "00000000-0000-0000-0000-000000000001",
            "assigned_agent_code": None,
            "instruction": "Continue implementation workflow after review.",
        },
    )
    assert task.status_code == 200
    task_id = task.json()["id"]

    patched = client.patch(
        f"/api/tasks/{task_id}",
        json={
            "review_source_assignee_id": team["dev1"],
            "review_source_assigned_agent_code": "dev-a",
            "review_next_lead_assignee_id": team["lead"],
            "review_next_lead_assigned_agent_code": "lead-a",
            "review_required": True,
            "review_status": "pending",
        },
    )
    assert patched.status_code == 200

    approved = client.post(f"/api/tasks/{task_id}/review", json={"action": "approve"})
    assert approved.status_code == 200
    payload = approved.json()
    assert payload["status"] == "In Progress"
    assert payload["assigned_agent_code"] == "dev-a"
    assert payload["assignee_id"] == team["dev1"]

    refreshed = client.get(f"/api/tasks/{task_id}")
    assert refreshed.status_code == 200
    refreshed_payload = refreshed.json()
    assert refreshed_payload["status"] == "In Progress"
    assert refreshed_payload["assigned_agent_code"] == "dev-a"
    assert refreshed_payload["assignee_id"] == team["dev1"]

    automation = client.get(f"/api/tasks/{task_id}/automation")
    assert automation.status_code == 200
    automation_payload = automation.json()
    assert automation_payload["automation_state"] in {"queued", "running", "completed"}
    assert automation_payload["last_requested_source"] == "review_approved"


def test_patch_task_to_in_review_reassigns_human_reviewer_when_code_review_required(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    plugin_payload = client.get(f"/api/projects/{project_id}/plugins/team_mode")
    assert plugin_payload.status_code == 200
    config = plugin_payload.json()["config"]
    config["review_policy"] = {
        "require_code_review": True,
        "reviewer_user_id": "00000000-0000-0000-0000-000000000001",
    }
    applied = client.post(
        f"/api/projects/{project_id}/plugins/team_mode/apply",
        json={"config": config, "enabled": True},
    )
    assert applied.status_code == 200

    task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Manual review routing patch",
            "status": "In Progress",
            "priority": "High",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Ship implementation and route through required review.",
        },
    )
    assert task.status_code == 200
    task_id = task.json()["id"]

    moved = client.patch(f"/api/tasks/{task_id}", json={"status": "In Review"})
    assert moved.status_code == 200
    payload = moved.json()
    assert payload["status"] == "In Review"
    assert payload["assignee_id"] == "00000000-0000-0000-0000-000000000001"
    assert payload["assigned_agent_code"] is None
    assert payload["review_required"] is True
    assert payload["review_status"] == "pending"
    assert payload["review_source_assignee_id"] is not None
    assert payload["review_source_assigned_agent_code"] == "dev-a"


def test_team_mode_review_approved_completion_merges_without_reentering_review(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    plugin_payload = client.get(f"/api/projects/{project_id}/plugins/team_mode")
    assert plugin_payload.status_code == 200
    config = plugin_payload.json()["config"]
    config["review_policy"] = {"require_code_review": True}
    applied = client.post(
        f"/api/projects/{project_id}/plugins/team_mode/apply",
        json={"config": config, "enabled": True},
    )
    assert applied.status_code == 200

    review_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Approved review merge handoff",
            "status": "In Review",
            "priority": "High",
            "assignee_id": "00000000-0000-0000-0000-000000000001",
            "assigned_agent_code": None,
            "instruction": "Finalize the already approved branch merge handoff.",
        },
    )
    assert review_task.status_code == 200
    dev_task_id = review_task.json()["id"]

    patched = client.patch(
        f"/api/tasks/{dev_task_id}",
        json={
            "review_source_assignee_id": team["dev1"],
            "review_source_assigned_agent_code": "dev-a",
            "review_required": True,
            "review_status": "pending",
        },
    )
    assert patched.status_code == 200
    approved = client.post(f"/api/tasks/{dev_task_id}/review", json={"action": "approve"})
    assert approved.status_code == 200
    approved_payload = approved.json()
    assert approved_payload["status"] == "In Progress"
    assert approved_payload["review_status"] == "approved"

    from features.agents.executor import AutomationOutcome
    import features.agents.runner as runner_module
    from features.agents.runner import QueuedAutomationRun, _record_automation_success

    before_sha = "1111111111111111111111111111111111111111"
    after_sha = "2222222222222222222222222222222222222222"
    original_inspect_handoff = runner_module._inspect_committed_task_branch_handoff
    original_merge_to_main = runner_module._merge_current_task_branch_to_main
    merge_calls: list[dict[str, object]] = []

    def _fake_inspect_handoff(git_evidence):
        result = original_inspect_handoff(git_evidence)
        result.update(
            {
                "branch_name": "task/review-approved-merge",
                "branch_exists": True,
                "branch_head_sha": after_sha,
                "main_head_sha": before_sha,
                "branch_ahead_of_main": True,
                "branch_differs_from_main": True,
                "after_head_sha": after_sha,
                "after_on_task_branch": True,
                "after_is_dirty": False,
            }
        )
        return result

    def _fake_merge_to_main(**kwargs):
        merge_calls.append(dict(kwargs))
        return {
            "ok": True,
            "merge_sha": after_sha,
            "merged_at": "2026-03-16T15:00:00Z",
            "external_refs": [
                {"url": f"commit:{after_sha}", "title": "task commit"},
                {"url": "task/review-approved-merge", "title": "task branch"},
                {"url": f"merge:main:{after_sha}", "title": "merged to main"},
            ],
        }

    runner_module._inspect_committed_task_branch_handoff = _fake_inspect_handoff
    runner_module._merge_current_task_branch_to_main = _fake_merge_to_main
    try:
        _record_automation_success(
            QueuedAutomationRun(
                task_id=dev_task_id,
                workspace_id=ws_id,
                project_id=project_id,
                title="Approved review merge handoff",
                description="",
                status="In Progress",
                instruction="Finalize the already approved branch merge handoff.",
                request_source="review_approved",
                is_scheduled_run=False,
                trigger_task_id=None,
                trigger_from_status=None,
                trigger_to_status=None,
                triggered_at=None,
                actor_user_id=team["dev1"],
            ),
            outcome=AutomationOutcome(
                action="comment",
                summary="Merged the approved task branch into main.",
                comment=None,
                execution_outcome_contract={
                    "contract_version": 1,
                    "files_changed": ["src/gameplay/score.ts"],
                    "tests_run": False,
                    "tests_passed": False,
                    "commit_sha": after_sha,
                    "branch": "task/review-approved-merge",
                    "artifacts": [],
                },
                usage={
                    "git_evidence": {
                        "repo_root": str(tmp_path / "repo-placeholder"),
                        "task_branch": "task/review-approved-merge",
                        "before": {"head_sha": before_sha},
                        "after": {"head_sha": after_sha, "on_task_branch": True, "is_dirty": False},
                    }
                },
            ),
        )
    finally:
        runner_module._inspect_committed_task_branch_handoff = original_inspect_handoff
        runner_module._merge_current_task_branch_to_main = original_merge_to_main

    assert len(merge_calls) == 1
    task_payload = client.get(f"/api/tasks/{dev_task_id}").json()
    assert task_payload["status"] != "In Review"
    assert task_payload["review_status"] == "approved"


def test_merge_to_main_rejects_review_required_task_without_approval(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    plugin_payload = client.get(f"/api/projects/{project_id}/plugins/team_mode")
    assert plugin_payload.status_code == 200
    config = plugin_payload.json()["config"]
    config["review_policy"] = {"require_code_review": True}
    applied = client.post(
        f"/api/projects/{project_id}/plugins/team_mode/apply",
        json={"config": config, "enabled": True},
    )
    assert applied.status_code == 200

    task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Pending review merge guard",
            "status": "In Progress",
            "priority": "High",
            "instruction": "This branch should not merge without approval.",
            "external_refs": [
                {"url": "task/pending-review-guard", "title": "task branch"},
            ],
        },
    )
    assert task.status_code == 200
    task_id = task.json()["id"]

    patched = client.patch(
        f"/api/tasks/{task_id}",
        json={
            "review_required": True,
            "review_status": "pending",
        },
    )
    assert patched.status_code == 200

    from features.agents.runner import _merge_current_task_branch_to_main
    from shared.models import SessionLocal

    with SessionLocal() as db:
        result = _merge_current_task_branch_to_main(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            task_id=task_id,
            actor_user_id="00000000-0000-0000-0000-000000000001",
        )

    assert result["ok"] is False
    assert "approved human review" in str(result["error"])


def test_team_mode_merged_increment_completes_after_developer_merge_without_lead_handoff(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Merged increment implementation task",
            "status": "In Progress",
            "priority": "High",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "delivery_mode": "merged_increment",
            "instruction": "Implement the merged increment on the task branch.",
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    from features.agents.executor import AutomationOutcome
    import features.agents.runner as runner_module
    from features.agents.runner import QueuedAutomationRun, _record_automation_success

    before_sha = "1111111111111111111111111111111111111111"
    after_sha = "2222222222222222222222222222222222222222"
    original_inspect_handoff = runner_module._inspect_committed_task_branch_handoff
    original_merge_to_main = runner_module._merge_current_task_branch_to_main

    def _fake_inspect_handoff(git_evidence):
        result = original_inspect_handoff(git_evidence)
        result.update(
            {
                "branch_name": "task/merged-increment",
                "branch_exists": True,
                "branch_head_sha": after_sha,
                "main_head_sha": before_sha,
                "branch_differs_from_main": True,
                "after_head_sha": after_sha,
                "after_on_task_branch": True,
                "after_is_dirty": False,
            }
        )
        return result

    def _fake_merge_to_main(**_kwargs):
        return {
            "ok": True,
            "merge_sha": after_sha,
            "merged_at": "2026-03-16T15:00:00Z",
            "external_refs": [
                {"url": f"commit:{after_sha}", "title": "task commit"},
                {"url": "task/merged-increment", "title": "task branch"},
                {"url": f"merge:main:{after_sha}", "title": "merged to main"},
            ],
        }

    runner_module._inspect_committed_task_branch_handoff = _fake_inspect_handoff
    runner_module._merge_current_task_branch_to_main = _fake_merge_to_main
    try:
        _record_automation_success(
            QueuedAutomationRun(
                task_id=dev_task_id,
                workspace_id=ws_id,
                project_id=project_id,
                title="Merged increment implementation task",
                description="",
                status="In Progress",
                instruction="Implement the merged increment on the task branch.",
                request_source="manual",
                is_scheduled_run=False,
                trigger_task_id=None,
                trigger_from_status=None,
                trigger_to_status=None,
                triggered_at=None,
                actor_user_id=team["dev1"],
            ),
            outcome=AutomationOutcome(
                action="comment",
                summary="Implemented on task branch task/merged-increment with commit 2222222.",
                comment=None,
                execution_outcome_contract={
                    "contract_version": 1,
                    "files_changed": ["src/gameplay/score.ts"],
                    "tests_run": False,
                    "tests_passed": False,
                    "commit_sha": after_sha,
                    "branch": "task/merged-increment",
                    "artifacts": [],
                },
                usage={
                    "git_evidence": {
                        "repo_root": str(tmp_path / "repo-placeholder"),
                        "task_branch": "task/merged-increment",
                        "before": {"head_sha": before_sha},
                        "after": {"head_sha": after_sha, "on_task_branch": True, "is_dirty": False},
                    }
                },
            ),
        )
    finally:
        runner_module._inspect_committed_task_branch_handoff = original_inspect_handoff
        runner_module._merge_current_task_branch_to_main = original_merge_to_main

    task_payload = client.get(f"/api/tasks/{dev_task_id}").json()
    assert task_payload["status"] == "Completed"
    assert task_payload["assigned_agent_code"] == "dev-a"

    automation_payload = client.get(f"/api/tasks/{dev_task_id}/automation").json()
    assert automation_payload["last_requested_source"] not in {"developer_handoff", "review_approved"}


def test_team_mode_developer_completion_does_not_auto_queue_separate_lead_task(tmp_path):
    import features.agents.runner as runner_module

    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead integration task",
            "status": "Awaiting decision",
            "priority": "High",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Review the Developer handoff and continue the Lead cycle.",
            "task_relationships": [
                {"kind": "depends_on", "task_ids": [], "statuses": ["Completed"]},
            ],
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer implementation task",
            "status": "In Progress",
            "priority": "High",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement the gameplay changes on the task branch.",
            "task_relationships": [
                {"kind": "delivers_to", "task_ids": [lead_task_id], "statuses": ["Awaiting decision"]},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    patched_lead = client.patch(
        f"/api/tasks/{lead_task_id}",
        json={
            "task_relationships": [
                {"kind": "depends_on", "task_ids": [dev_task_id], "statuses": ["Completed"]},
            ],
        },
    )
    assert patched_lead.status_code == 200

    from features.agents.executor import AutomationOutcome
    from features.agents.runner import QueuedAutomationRun, _record_automation_success

    before_sha = "1111111111111111111111111111111111111111"
    after_sha = "2222222222222222222222222222222222222222"

    original_inspect_handoff = runner_module._inspect_committed_task_branch_handoff

    def _fake_inspect_handoff(git_evidence):
        result = original_inspect_handoff(git_evidence)
        result.update(
            {
                "branch_name": "task/dev-gameplay",
                "branch_exists": True,
                "branch_head_sha": after_sha,
                "main_head_sha": before_sha,
                "branch_differs_from_main": True,
                "after_head_sha": after_sha,
                "after_on_task_branch": True,
                "after_is_dirty": False,
            }
        )
        return result

    runner_module._inspect_committed_task_branch_handoff = _fake_inspect_handoff

    try:
        _record_automation_success(
            QueuedAutomationRun(
                task_id=dev_task_id,
                workspace_id=ws_id,
                project_id=project_id,
                title="Developer implementation task",
                description="",
                status="In Progress",
                instruction="Implement the gameplay changes on the task branch.",
                request_source="manual",
                is_scheduled_run=False,
                trigger_task_id=None,
                trigger_from_status=None,
                trigger_to_status=None,
                triggered_at=None,
                actor_user_id=team["dev1"],
            ),
            outcome=AutomationOutcome(
                action="comment",
                summary="Implemented on task branch task/dev-gameplay with commit 2222222.",
                comment=None,
                execution_outcome_contract={
                    "contract_version": 1,
                    "files_changed": ["src/gameplay/tetris.ts"],
                    "tests_run": False,
                    "tests_passed": False,
                    "commit_sha": after_sha,
                    "branch": "task/dev-gameplay",
                    "artifacts": [],
                },
                usage={
                    "git_evidence": {
                        "repo_root": str(tmp_path / "repo-placeholder"),
                        "task_branch": "task/dev-gameplay",
                        "before": {"head_sha": before_sha},
                        "after": {"head_sha": after_sha, "on_task_branch": True, "is_dirty": False},
                    }
                },
            ),
        )
    finally:
        runner_module._inspect_committed_task_branch_handoff = original_inspect_handoff

    lead_status = client.get(f"/api/tasks/{lead_task_id}/automation")
    assert lead_status.status_code == 200
    lead_payload = lead_status.json()
    assert lead_payload["automation_state"] == "idle"
    assert lead_payload.get("last_requested_source") in {None, ""}


def test_runner_resolves_team_mode_role_from_assigned_agent_code_without_human_assignee(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    import features.agents.runner as runner_module
    from shared.models import SessionLocal

    with SessionLocal() as db:
        resolved = runner_module._resolve_assignee_project_role(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            assignee_id="",
            assigned_agent_code="lead-a",
            task_labels=None,
            task_status="In Progress",
        )
    assert resolved == "Lead"


def test_runner_does_not_promote_unchanged_developer_branch_as_commit_evidence(tmp_path, monkeypatch):
    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome
    from features.agents.runner import QueuedAutomationRun, _record_automation_success
    from shared.models import SessionLocal
    from shared.eventing_rebuild import rebuild_state

    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path / "workspace"))
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead task",
            "status": "Awaiting decision",
            "priority": "High",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]
    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer task",
            "status": "In Progress",
            "priority": "High",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement gameplay on the task branch.",
            "task_relationships": [
                {"kind": "delivers_to", "task_ids": [lead_task_id], "statuses": ["Awaiting decision"]},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    original_inspect_handoff = runner_module._inspect_committed_task_branch_handoff
    unchanged_sha = "1111111111111111111111111111111111111111"

    def _fake_inspect_handoff(git_evidence):
        result = original_inspect_handoff(git_evidence)
        result.update(
            {
                "branch_name": "task/dev-gameplay",
                "branch_exists": True,
                "branch_head_sha": unchanged_sha,
                "main_head_sha": unchanged_sha,
                "branch_differs_from_main": False,
                "after_head_sha": unchanged_sha,
                "after_on_task_branch": True,
                "after_is_dirty": True,
            }
        )
        return result

    runner_module._inspect_committed_task_branch_handoff = _fake_inspect_handoff
    try:
        with pytest.raises(RuntimeError, match="Developer handoff is not committed on the task branch yet"):
            _record_automation_success(
                QueuedAutomationRun(
                    task_id=dev_task_id,
                    workspace_id=ws_id,
                    project_id=project_id,
                    title="Developer task",
                description="",
                status="In Progress",
                instruction="Implement gameplay on the task branch.",
                request_source="manual",
                is_scheduled_run=False,
                trigger_task_id=None,
                trigger_from_status=None,
                trigger_to_status=None,
                triggered_at=None,
                actor_user_id=team["dev1"],
            ),
            outcome=AutomationOutcome(
                action="comment",
                summary="Implemented gameplay files locally.",
                comment=None,
                execution_outcome_contract={
                    "contract_version": 1,
                    "files_changed": ["index.html", "styles.css", "game.js"],
                    "tests_run": False,
                    "tests_passed": False,
                    "commit_sha": None,
                    "branch": "task/dev-gameplay",
                    "artifacts": [],
                },
                usage={
                    "git_evidence": {
                        "repo_root": str(tmp_path / "repo-placeholder"),
                        "task_branch": "task/dev-gameplay",
                        "before": {"head_sha": unchanged_sha},
                        "after": {"head_sha": unchanged_sha, "on_task_branch": True, "is_dirty": True},
                    }
                },
                ),
            )
    finally:
        runner_module._inspect_committed_task_branch_handoff = original_inspect_handoff

    with SessionLocal() as db:
        state, _ = rebuild_state(db, "Task", dev_task_id)
    ref_urls = {
        str(item.get("url") or "")
        for item in (state.get("external_refs") or [])
        if isinstance(item, dict)
    }
    assert "commit:1111111111111111111111111111111111111111" not in ref_urls
    assert "task/dev-gameplay" not in ref_urls


def test_team_mode_happy_path_rearms_blocked_lead_after_developer_handoff(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_resp = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Blocked lead rearm project',
            'custom_statuses': ['To do', 'In Progress', 'In Review', 'Awaiting decision', 'Blocked', 'Completed'],
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead integration task",
            "status": "Blocked",
            "priority": "High",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Review the Developer handoff and continue the Lead cycle.",
            "task_relationships": [
                {"kind": "depends_on", "task_ids": [], "statuses": ["Awaiting decision"]},
            ],
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer implementation task",
            "status": "Completed",
            "priority": "High",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Developer handoff is ready for review.",
            "external_refs": [
                {"url": "merge:main:abc1234", "title": "merged to main"},
            ],
            "task_relationships": [
                {"kind": "delivers_to", "task_ids": [lead_task_id], "statuses": ["Completed"]},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA validation task",
            "status": "To do",
            "priority": "High",
            "assignee_id": team["qa"],
            "assigned_agent_code": "qa-a",
            "instruction": "Validate the handoff after Lead review.",
        },
    )
    assert qa_task.status_code == 200
    qa_task_id = qa_task.json()["id"]

    patched_lead = client.patch(
        f"/api/tasks/{lead_task_id}",
        json={
            "task_relationships": [
                {"kind": "depends_on", "task_ids": [dev_task_id], "statuses": ["Completed"]},
                {"kind": "depends_on", "task_ids": [dev_task_id, qa_task_id], "match_mode": "any", "statuses": ["Blocked"]},
            ],
        },
    )
    assert patched_lead.status_code == 200
    assert client.patch(
        f"/api/tasks/{qa_task_id}",
        json={
            "task_relationships": [
                {"kind": "hands_off_to", "task_ids": [lead_task_id], "statuses": ["In Progress"]},
                {"kind": "escalates_to", "task_ids": [lead_task_id], "statuses": ["Awaiting decision", "Blocked"]},
            ],
        },
    ).status_code == 200

    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=dev_task_id,
            event_type="TaskAutomationCompleted",
            payload={
                "completed_at": "2026-03-11T01:10:00Z",
                "action": "comment",
                "summary": "Developer handoff ready.",
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": dev_task_id,
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=lead_task_id,
            event_type="TaskAutomationRequested",
            payload={
                "requested_at": "2026-03-11T01:05:00Z",
                "instruction": "Review the Developer handoff and continue the Lead cycle.",
                "source": "manual",
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": lead_task_id,
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=lead_task_id,
            event_type="TaskAutomationCompleted",
            payload={
                "completed_at": "2026-03-11T01:06:00Z",
                "action": "comment",
                "summary": "Lead blocked earlier.",
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": lead_task_id,
            },
        )
        db.commit()

    from shared.models import SessionLocal as SessionLocal2
    from features.agents.runner import _rearm_blocked_team_mode_lead_tasks

    with SessionLocal2() as db:
        rearmed = _rearm_blocked_team_mode_lead_tasks(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
        )
        db.commit()

    assert rearmed >= 1

    lead_task_status = client.get(f"/api/tasks/{lead_task_id}")
    assert lead_task_status.status_code == 200
    assert lead_task_status.json()["status"] == "In Progress"


def test_single_lead_scheduled_task_is_dispatch_ready_after_developer_handoff(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_resp = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Recurring lead dispatch project',
            'custom_statuses': ['To do', 'In Progress', 'In Review', 'Awaiting decision', 'Blocked', 'Completed'],
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer implementation task",
            "status": "Completed",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Developer handoff is ready.",
            "external_refs": [
                {"url": "merge:main:abc1234", "title": "merged to main"},
            ],
        },
    )
    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Single recurring Lead task",
            "status": "Awaiting decision",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Coordinate the lead cycle.",
            "task_type": "scheduled_instruction",
            "scheduled_instruction": "Coordinate the lead cycle.",
            "scheduled_at_utc": "2026-03-10T08:00:00Z",
            "recurring_rule": "every:5m",
            "execution_triggers": [
                {
                    "kind": "schedule",
                    "enabled": True,
                    "scheduled_at_utc": "2026-03-10T08:00:00Z",
                    "recurring_rule": "every:5m",
                    "run_on_statuses": ["Awaiting decision"],
                    "action": "request_automation",
                }
            ],
        },
    )
    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA validation task",
            "status": "To do",
            "assignee_id": team["qa"],
            "assigned_agent_code": "qa-a",
            "instruction": "Validate release quality.",
        },
    )
    assert dev_task.status_code == 200
    assert lead_task.status_code == 200
    assert qa_task.status_code == 200
    dev_task_id = dev_task.json()["id"]
    lead_task_id = lead_task.json()["id"]
    qa_task_id = qa_task.json()["id"]

    assert client.patch(
        f"/api/tasks/{dev_task_id}",
        json={
            "task_relationships": [
                {"kind": "delivers_to", "task_ids": [lead_task_id], "statuses": ["Completed"]}
            ]
        },
    ).status_code == 200
    assert client.patch(
        f"/api/tasks/{lead_task_id}",
        json={
            "task_relationships": [
                {"kind": "depends_on", "task_ids": [dev_task_id], "statuses": ["Completed"]},
                {
                    "kind": "depends_on",
                    "task_ids": [dev_task_id, qa_task_id],
                    "match_mode": "any",
                    "statuses": ["Blocked"],
                },
            ]
        },
    ).status_code == 200
    assert client.patch(
        f"/api/tasks/{qa_task_id}",
        json={
            "task_relationships": [
                {"kind": "hands_off_to", "task_ids": [lead_task_id], "statuses": ["In Progress"]},
                {"kind": "escalates_to", "task_ids": [lead_task_id], "statuses": ["Awaiting decision", "Blocked"]},
            ]
        },
    ).status_code == 200

    from shared.models import SessionLocal
    from features.agents.runner import _build_team_mode_dispatch_candidates

    with SessionLocal() as db:
        candidates, _candidate_map = _build_team_mode_dispatch_candidates(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
        )
    lead_candidates = [item for item in candidates if item["id"] == lead_task_id]
    assert len(lead_candidates) == 1
    assert lead_candidates[0]["dispatch_ready"] is True


def test_team_mode_happy_path_rearms_blocked_lead_when_any_dependency_clause_is_satisfied(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_resp = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Blocked lead any-clause project',
            'custom_statuses': ['To do', 'In Progress', 'In Review', 'Awaiting decision', 'Blocked', 'Completed'],
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead integration task",
            "status": "Blocked",
            "priority": "High",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Review the Developer handoff and continue the Lead cycle.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer implementation task",
            "status": "Completed",
            "priority": "High",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Developer handoff is ready for review.",
            "external_refs": [
                {"url": "merge:main:abc1234", "title": "merged to main"},
            ],
            "task_relationships": [
                {"kind": "delivers_to", "task_ids": [lead_task_id], "statuses": ["Completed"]},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA validation task",
            "status": "To do",
            "priority": "High",
            "assignee_id": team["qa"],
            "assigned_agent_code": "qa-a",
            "instruction": "Validate gameplay quality.",
            "task_relationships": [
                {"kind": "hands_off_to", "task_ids": [lead_task_id], "statuses": ["In Progress"]},
            ],
        },
    )
    assert qa_task.status_code == 200
    qa_task_id = qa_task.json()["id"]

    patched_lead = client.patch(
        f"/api/tasks/{lead_task_id}",
        json={
            "task_relationships": [
                {"kind": "depends_on", "task_ids": [dev_task_id], "statuses": ["Completed"]},
                {"kind": "depends_on", "task_ids": [dev_task_id, qa_task_id], "statuses": ["Blocked"], "match_mode": "any"},
            ],
        },
    )
    assert patched_lead.status_code == 200

    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=dev_task_id,
            event_type="TaskAutomationCompleted",
            payload={
                "completed_at": "2026-03-11T01:10:00Z",
                "action": "comment",
                "summary": "Developer handoff ready.",
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": dev_task_id,
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=lead_task_id,
            event_type="TaskAutomationRequested",
            payload={
                "requested_at": "2026-03-11T01:05:00Z",
                "instruction": "Review the Developer handoff and continue the Lead cycle.",
                "source": "manual",
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": lead_task_id,
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=lead_task_id,
            event_type="TaskAutomationCompleted",
            payload={
                "completed_at": "2026-03-11T01:06:00Z",
                "action": "comment",
                "summary": "Lead blocked earlier.",
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": lead_task_id,
            },
        )
        db.commit()

    from features.agents.runner import queue_team_mode_happy_path_once

    queued = queue_team_mode_happy_path_once(limit=20)
    assert queued == 0

    lead_task_status = client.get(f"/api/tasks/{lead_task_id}")
    assert lead_task_status.status_code == 200
    assert lead_task_status.json()["status"] == "In Progress"


def test_team_mode_happy_path_does_not_rearm_blocked_lead_after_failed_deploy_health(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead deploy task",
            "status": "Blocked",
            "priority": "High",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Retry deploy after a healthy build.",
            "task_relationships": [
                {"kind": "depends_on", "task_ids": [], "statuses": ["Completed"]},
            ],
            "external_refs": [
                {"url": "deploy:command:docker compose -p constructos-ws-default up -d", "title": "Deploy command"},
                {"url": "deploy:health:http://gateway:6768/health:http_000", "title": "Failed health probe"},
            ],
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer handoff task",
            "status": "Completed",
            "priority": "High",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Developer handoff is ready.",
            "external_refs": [
                {"url": "merge:main:abc1234", "title": "merged to main"},
            ],
            "task_relationships": [
                {"kind": "delivers_to", "task_ids": [lead_task_id], "statuses": ["Awaiting decision"]},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    patched_lead = client.patch(
        f"/api/tasks/{lead_task_id}",
        json={
            "task_relationships": [
                {"kind": "depends_on", "task_ids": [dev_task_id], "statuses": ["Completed"]},
            ],
        },
    )
    assert patched_lead.status_code == 200

    from features.agents.runner import queue_team_mode_happy_path_once

    queued = queue_team_mode_happy_path_once(limit=20)
    assert queued == 0

    lead_task_status = client.get(f"/api/tasks/{lead_task_id}")
    assert lead_task_status.status_code == 200
    assert lead_task_status.json()["status"] == "Blocked"


def test_merge_ready_developer_branches_to_main_keeps_task_active_after_merge(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    os.environ["AGENT_CODEX_WORKDIR"] = str(tmp_path / "workspace")

    project = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Merge closeout test',
            'custom_statuses': ['To do', 'In Progress', 'In Review', 'Awaiting decision', 'Blocked', 'Completed'],
        },
    )
    assert project.status_code == 200
    project_id = project.json()['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    from shared.project_repository import ensure_project_repository_initialized
    from features.agents.runner import _merge_ready_developer_branches_to_main
    from shared.models import SessionLocal
    import subprocess

    repo_root = ensure_project_repository_initialized(project_name='Merge closeout test', project_id=project_id)
    subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=repo_root, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=repo_root, check=True)
    (repo_root / 'README.md').write_text('base\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'README.md'], cwd=repo_root, check=True)
    subprocess.run(['git', 'commit', '-m', 'Initial'], cwd=repo_root, check=True)
    subprocess.run(['git', 'checkout', '-b', 'task/dev-merged-branch'], cwd=repo_root, check=True)
    (repo_root / 'game.js').write_text('export const ready = true;\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'game.js'], cwd=repo_root, check=True)
    subprocess.run(['git', 'commit', '-m', 'Developer branch'], cwd=repo_root, check=True)
    branch_sha = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(['git', 'checkout', 'main'], cwd=repo_root, check=True)
    subprocess.run(['git', 'merge', '--no-ff', '--no-edit', 'task/dev-merged-branch'], cwd=repo_root, check=True)

    dev_task = client.post(
        '/api/tasks',
        json={
            'title': 'Merged developer task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Lead deploy-ready task.',
            'external_refs': [
                {'url': f'commit:{branch_sha}', 'title': 'commit evidence'},
                {'url': 'task/dev-merged-branch', 'title': 'task branch evidence'},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()['id']

    with SessionLocal() as db:
        result = _merge_ready_developer_branches_to_main(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            actor_user_id=team['lead'],
        )
        assert result['ok'] is True
        assert dev_task_id in (result.get('merged_task_ids') or [])
        db.commit()

    refreshed = client.get(f'/api/tasks/{dev_task_id}')
    assert refreshed.status_code == 200
    refreshed_payload = refreshed.json()
    assert refreshed_payload['status'] == 'In Progress'
    ref_urls = {
        str(item.get('url') or '')
        for item in (refreshed_payload.get('external_refs') or [])
        if isinstance(item, dict)
    }
    assert any(url.startswith('merge:main:') for url in ref_urls)


def test_manual_team_mode_lead_request_infers_developer_handoff_source(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead review task",
            "status": "Awaiting decision",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Review the completed Developer handoff.",
            "task_relationships": [
                {"kind": "depends_on", "task_ids": [], "statuses": ["Awaiting decision"]},
            ],
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer completed handoff",
            "status": "Completed",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Developer handoff is ready for review.",
            "task_relationships": [
                {"kind": "delivers_to", "task_ids": [lead_task_id], "statuses": ["Awaiting decision"]},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    patched_lead = client.patch(
        f"/api/tasks/{lead_task_id}",
        json={
            "task_relationships": [
                {"kind": "depends_on", "task_ids": [dev_task_id], "statuses": ["Awaiting decision"]},
            ],
        },
    )
    assert patched_lead.status_code == 200

    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    completed_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=dev_task_id,
            event_type="TaskAutomationCompleted",
            payload={"completed_at": completed_at},
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": dev_task_id,
            },
        )
        db.commit()

    run_res = client.post(
        f"/api/tasks/{lead_task_id}/automation/run",
        json={
            "instruction": "Review the completed Developer handoff.",
            "execution_intent": True,
            "execution_kickoff_intent": False,
            "project_creation_intent": False,
            "workflow_scope": "team_mode",
            "execution_mode": "resume_execution",
            "task_completion_requested": False,
            "classifier_reason": "test override",
        },
    )
    assert run_res.status_code == 200

    lead_status = client.get(f"/api/tasks/{lead_task_id}/automation")
    assert lead_status.status_code == 200
    payload = lead_status.json()
    assert payload["last_requested_source"] == "developer_handoff"
    assert payload["last_requested_source_task_id"] == dev_task_id


def test_manual_team_mode_developer_request_infers_lead_kickoff_dispatch_source(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead kickoff task",
            "status": "To do",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Lead kickoff coordination.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer kickoff task",
            "status": "To do",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement the first Team Mode task.",
            "task_relationships": [
                {"kind": "delivers_to", "task_ids": [lead_task_id], "statuses": ["Awaiting decision"]},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    kickoff_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=lead_task_id,
            event_type="TaskAutomationRequested",
            payload={
                "requested_at": kickoff_at,
                "instruction": "Team Mode kickoff for the project. Dispatch-only run.",
                "source": "manual",
                "execution_intent": True,
                "execution_kickoff_intent": True,
                "project_creation_intent": False,
                "workflow_scope": "team_mode",
                "execution_mode": "kickoff_only",
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": lead_task_id,
            },
        )
        db.commit()

    run_res = client.post(
        f"/api/tasks/{dev_task_id}/automation/run",
        json={
            "instruction": "Implement the first Team Mode task.",
            "execution_intent": True,
            "execution_kickoff_intent": False,
            "project_creation_intent": False,
            "workflow_scope": "team_mode",
            "execution_mode": "resume_execution",
            "task_completion_requested": False,
            "classifier_reason": "test override",
        },
    )
    assert run_res.status_code == 200
    assert run_res.json().get("skipped") is not True

    dev_status = client.get(f"/api/tasks/{dev_task_id}/automation")
    assert dev_status.status_code == 200
    payload = dev_status.json()
    assert payload["last_requested_source"] == "lead_kickoff_dispatch"
    assert payload["last_requested_source_task_id"] == lead_task_id

    graph_res = client.get(f"/api/projects/{project_id}/task-dependency-graph")
    assert graph_res.status_code == 200
    graph_payload = graph_res.json()
    edge_map = {
        (str(item.get("source_entity_id") or ""), str(item.get("target_entity_id") or "")): item
        for item in (graph_payload.get("edges") or [])
    }
    lead_to_dev = edge_map[(lead_task_id, dev_task_id)]
    assert lead_to_dev["runtime_dependency"] is True
    assert any(str(channel.get("source") or "") == "lead_kickoff_dispatch" for channel in (lead_to_dev.get("channels") or []))


def test_manual_team_mode_fresh_lead_request_defaults_to_kickoff_even_with_generic_instruction(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_resp = client.post(
        '/api/projects',
        json={
            'workspace_id': ws_id,
            'name': 'Fresh lead kickoff default project',
            'custom_statuses': ['To do', 'In Progress', 'In Review', 'Awaiting decision', 'Blocked', 'Completed'],
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead kickoff default task",
            "status": "To do",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Coordinate implementation and deployment readiness.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer kickoff target",
            "status": "To do",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement gameplay scope.",
            "task_relationships": [
                {"kind": "delivers_to", "task_ids": [lead_task_id], "statuses": ["Awaiting decision"]},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA kickoff target",
            "status": "To do",
            "assignee_id": team["qa"],
            "assigned_agent_code": "qa-a",
            "instruction": "Validate release quality.",
            "task_relationships": [
                {"kind": "hands_off_to", "task_ids": [lead_task_id], "statuses": ["In Progress"]},
            ],
        },
    )
    assert qa_task.status_code == 200

    patched_lead = client.patch(
        f"/api/tasks/{lead_task_id}",
        json={
            "task_relationships": [
                {"kind": "depends_on", "task_ids": [dev_task_id], "statuses": ["Awaiting decision"]},
            ],
        },
    )
    assert patched_lead.status_code == 200

    queued = client.post(f"/api/tasks/{lead_task_id}/automation/run", json={})
    assert queued.status_code == 200

    lead_status = client.get(f"/api/tasks/{lead_task_id}/automation")
    assert lead_status.status_code == 200
    lead_payload = lead_status.json()
    assert lead_payload["last_requested_execution_kickoff_intent"] is True
    assert lead_payload["last_requested_execution_mode"] == "kickoff_only"

    assert lead_payload["last_requested_source"] == "manual"
    assert "Team Mode kickoff for project" in str(lead_payload.get("last_requested_instruction") or "")


def test_lead_deploy_contract_is_runner_controlled_after_merge_evidence():
    from features.agents.runner import _build_lead_deploy_instruction_contract

    instruction = _build_lead_deploy_instruction_contract(
        stack="constructos-ws-default",
        port_text="6768",
        health_path="/health",
        has_merge_to_main=True,
    )

    assert "Do NOT run `docker compose` manually from the task environment." in instruction
    assert "runner owns actual deploy execution" in instruction
    assert "Do NOT block this Lead response merely because runner-controlled deploy has not happened yet" in instruction
    assert "Execute deploy for stack" not in instruction


def test_qa_runtime_validation_contract_forbids_manual_compose():
    from features.agents.runner import _build_qa_runtime_validation_contract

    instruction = _build_qa_runtime_validation_contract(
        stack="constructos-ws-default",
        port_text="6768",
        health_path="/health",
    )

    assert "Do NOT run `docker compose` manually" in instruction
    assert "Treat the latest Lead deploy snapshot" in instruction
    assert "http://gateway:6768/health" in instruction


def test_translate_compose_manifest_for_host_runtime_rewrites_relative_bind_sources(tmp_path):
    from features.agents import runner as runner_module

    manifest_path = tmp_path / "docker-compose.yml"
    manifest_path.write_text(
        "services:\n"
        "  app:\n"
        "    build:\n"
        "      context: .\n"
        "    volumes:\n"
        "      - ./:/usr/share/nginx/html:ro\n"
        "      - ./nginx.constructos.conf:/etc/nginx/conf.d/default.conf:ro\n"
        "    healthcheck:\n"
        "      test: [\"CMD\", \"wget\", \"-qO-\", \"http://localhost:6768/health\"]\n"
        "      interval: 10s\n",
        encoding="utf-8",
    )

    translated = runner_module._translate_compose_manifest_for_host_runtime(
        manifest_path=manifest_path,
        repo_root_host=Path("/host/workspace/repos/tetris"),
    )

    content = translated.read_text(encoding="utf-8")
    assert "context: ." in content
    assert "/host/workspace/repos/tetris/:/usr/share/nginx/html:ro" in content
    assert "/host/workspace/repos/tetris/nginx.constructos.conf:/etc/nginx/conf.d/default.conf:ro" in content
    assert "http://127.0.0.1:6768/health" in content
    assert "http://localhost:6768/health" not in content


def test_manual_team_mode_qa_request_infers_lead_handoff_source(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead release handoff",
            "status": "Awaiting decision",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Hand off the validated release to QA.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA release validation",
            "status": "In Progress",
            "assignee_id": team["qa"],
            "assigned_agent_code": "qa-a",
            "instruction": "Validate the Lead handoff.",
            "task_relationships": [
                {"kind": "hands_off_to", "task_ids": [lead_task_id], "statuses": ["In Progress"]},
            ],
        },
    )
    assert qa_task.status_code == 200
    qa_task_id = qa_task.json()["id"]

    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    handoff_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=lead_task_id,
            event_type="TaskUpdated",
            payload={
                "last_lead_handoff_token": f"lead:{lead_task_id}:{handoff_at}",
                "last_lead_handoff_at": handoff_at,
                "last_deploy_execution": {
                    "executed_at": handoff_at,
                    "stack": "constructos-ws-default",
                    "port": 6768,
                    "health_path": "/health",
                    "runtime_ok": True,
                },
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": lead_task_id,
            },
        )
        db.commit()

    run_res = client.post(
        f"/api/tasks/{qa_task_id}/automation/run",
        json={
            "instruction": "Validate the Lead handoff.",
            "execution_intent": True,
            "execution_kickoff_intent": False,
            "project_creation_intent": False,
            "workflow_scope": "team_mode",
            "execution_mode": "resume_execution",
            "task_completion_requested": False,
            "classifier_reason": "test override",
        },
    )
    assert run_res.status_code == 200

    qa_status = client.get(f"/api/tasks/{qa_task_id}/automation")
    assert qa_status.status_code == 200
    payload = qa_status.json()
    assert payload["last_requested_source"] == "lead_handoff"
    assert payload["last_requested_source_task_id"] == lead_task_id

    graph_res = client.get(f"/api/projects/{project_id}/task-dependency-graph")
    assert graph_res.status_code == 200
    graph_payload = graph_res.json()
    edge_map = {
        (str(item.get("source_entity_id") or ""), str(item.get("target_entity_id") or "")): item
        for item in (graph_payload.get("edges") or [])
    }
    lead_to_qa = edge_map[(lead_task_id, qa_task_id)]
    assert lead_to_qa["runtime_dependency"] is True
    assert int(lead_to_qa["lead_handoffs_total"]) >= 1
    assert any(str(channel.get("source") or "") == "lead_handoff" for channel in (lead_to_qa.get("channels") or []))


def test_manual_team_mode_qa_request_without_lead_handoff_is_skipped(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead release handoff",
            "status": "Awaiting decision",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Hand off the validated release to QA.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = str(lead_task.json()["id"])

    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA release validation",
            "status": "In Progress",
            "assignee_id": team["qa"],
            "assigned_agent_code": "qa-a",
            "instruction": "Validate the Lead handoff.",
            "task_relationships": [
                {"kind": "hands_off_to", "task_ids": [lead_task_id], "statuses": ["In Progress"]},
            ],
        },
    )
    assert qa_task.status_code == 200
    qa_task_id = str(qa_task.json()["id"])

    run_res = client.post(
        f"/api/tasks/{qa_task_id}/automation/run",
        json={
            "instruction": "Validate the Lead handoff.",
            "execution_intent": True,
            "execution_kickoff_intent": False,
            "project_creation_intent": False,
            "workflow_scope": "team_mode",
            "execution_mode": "resume_execution",
            "task_completion_requested": False,
            "classifier_reason": "test override",
        },
    )
    assert run_res.status_code == 200
    payload = run_res.json()
    assert payload.get("skipped") is True
    assert "explicit Lead handoff" in str(payload.get("reason") or "")

    qa_status = client.get(f"/api/tasks/{qa_task_id}/automation")
    assert qa_status.status_code == 200
    automation = qa_status.json()
    assert automation["automation_state"] == "idle"
    assert automation.get("last_requested_source_task_id") in {None, ""}


def test_manual_team_mode_same_task_qa_request_infers_handoff_config(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Single-task QA validation",
            "status": "In Progress",
            "assignee_id": team["qa"],
            "assigned_agent_code": "qa-a",
            "instruction": "Validate the deployed change on the same task.",
        },
    )
    assert task.status_code == 200
    task_id = task.json()["id"]

    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    handoff_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=task_id,
            event_type="TaskUpdated",
            payload={
                "last_lead_handoff_token": f"lead:{task_id}:{handoff_at}",
                "last_lead_handoff_at": handoff_at,
                "last_lead_handoff_deploy_execution": {
                    "executed_at": handoff_at,
                    "stack": "constructos-app",
                    "port": 6768,
                    "health_path": "/health",
                    "runtime_ok": True,
                },
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": task_id,
            },
        )
        db.commit()

    run_res = client.post(
        f"/api/tasks/{task_id}/automation/run",
        json={
            "instruction": "Validate the deployed change on the same task.",
            "execution_intent": True,
            "execution_kickoff_intent": False,
            "project_creation_intent": False,
            "workflow_scope": "team_mode",
            "execution_mode": "resume_execution",
            "task_completion_requested": False,
            "classifier_reason": "test override",
        },
    )
    assert run_res.status_code == 200
    payload = run_res.json()
    assert payload["ok"] is True
    assert payload["automation_state"] == "queued"

    automation_payload = client.get(f"/api/tasks/{task_id}/automation").json()
    assert automation_payload["last_requested_source"] == "lead_handoff"


def test_manual_team_mode_same_task_qa_request_skips_without_handoff_config(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Single-task QA should wait",
            "status": "In Progress",
            "assignee_id": team["qa"],
            "assigned_agent_code": "qa-a",
            "instruction": "Validate the deployed change on the same task.",
        },
    )
    assert task.status_code == 200
    task_id = task.json()["id"]

    run_res = client.post(
        f"/api/tasks/{task_id}/automation/run",
        json={
            "instruction": "Validate the deployed change on the same task.",
            "execution_intent": True,
            "execution_kickoff_intent": False,
            "project_creation_intent": False,
            "workflow_scope": "team_mode",
            "execution_mode": "resume_execution",
            "task_completion_requested": False,
            "classifier_reason": "test override",
        },
    )
    assert run_res.status_code == 200
    payload = run_res.json()
    assert payload["ok"] is True
    assert payload["skipped"] is True
    assert "Lead handoff" in str(payload["reason"] or "")


def test_team_mode_orchestrator_skips_duplicate_completed_handoff_request(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead follow-up task",
            "status": "Awaiting decision",
            "priority": "High",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Continue the Lead cycle.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = str(lead_task.json()["id"])

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Developer handoff",
            "status": "Completed",
            "priority": "High",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Developer handoff is ready.",
            "external_refs": [
                {"url": "merge:main:abc1234", "title": "merged to main"},
            ],
            "task_relationships": [
                {"kind": "delivers_to", "task_ids": [lead_task_id], "statuses": ["Awaiting decision"]},
            ],
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = str(dev_task.json()["id"])

    client.patch(
        f"/api/tasks/{lead_task_id}",
        json={
            "task_relationships": [
                {"kind": "depends_on", "task_ids": [dev_task_id], "statuses": ["Completed"]},
            ],
        },
    )

    from shared.core import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID
    from features.agents.runner import _queue_team_mode_dispatches

    requested_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=lead_task_id,
            event_type="TaskAutomationRequested",
            payload={
                "requested_at": requested_at,
                "instruction": "Continue the Lead cycle.",
                "source": "runner_orchestrator",
                "source_task_id": dev_task_id,
                "workflow_scope": "team_mode",
                "execution_intent": True,
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": lead_task_id,
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=lead_task_id,
            event_type="TaskAutomationCompleted",
            payload={"completed_at": requested_at},
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": ws_id,
                "project_id": project_id,
                "task_id": lead_task_id,
            },
        )
        db.commit()

    from shared.models import SessionLocal as SessionLocal2

    with SessionLocal2() as db:
        queued = _queue_team_mode_dispatches(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            source="runner_orchestrator",
            source_task_id=dev_task_id,
            allowed_roles={"Lead"},
        )
        db.commit()

    assert queued == 0

    lead_status = client.get(f"/api/tasks/{lead_task_id}/automation")
    assert lead_status.status_code == 200
    payload = lead_status.json()
    assert payload["automation_state"] == "completed"
    assert payload["last_requested_source"] == "runner_orchestrator"
    assert payload["last_requested_source_task_id"] == dev_task_id


def test_direct_lead_kickoff_completion_dispatches_only_ungated_developer_tasks(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    from shared.models import Project, SessionLocal

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.automation_max_parallel_tasks = 2
        db.commit()

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead kickoff task",
            "status": "To do",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Lead coordination task.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    qa_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "QA validation task",
            "status": "To do",
            "assignee_id": team["qa"],
            "assigned_agent_code": "qa-a",
            "instruction": "Validate the build.",
        },
    )
    assert qa_task.status_code == 200
    qa_task_id = qa_task.json()["id"]

    ready_dev = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Ready developer task",
            "status": "To do",
            "priority": "High",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement the ready task.",
        },
    )
    assert ready_dev.status_code == 200
    ready_dev_id = ready_dev.json()["id"]

    gated_dev = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Dependency-gated developer task",
            "status": "To do",
            "priority": "High",
            "assignee_id": team["dev2"],
            "assigned_agent_code": "dev-b",
            "instruction": "Implement the gated task after QA blocker.",
            "task_relationships": [
                {
                    "kind": "depends_on",
                    "match_mode": "all",
                    "task_ids": [qa_task_id],
                    "statuses": ["Blocked"],
                }
            ],
        },
    )
    assert gated_dev.status_code == 200
    gated_dev_id = gated_dev.json()["id"]

    from features.agents.executor import AutomationOutcome
    from features.agents.runner import QueuedAutomationRun, _record_automation_success

    _record_automation_success(
        QueuedAutomationRun(
            task_id=lead_task_id,
            workspace_id=ws_id,
            project_id=project_id,
            title="Lead kickoff task",
            description="",
            status="To do",
            instruction=f"Team Mode kickoff for project {project_id}.",
            request_source="manual",
            is_scheduled_run=False,
            trigger_task_id=None,
            trigger_from_status=None,
            trigger_to_status=None,
            triggered_at=None,
            actor_user_id=team["lead"],
            execution_kickoff_intent=True,
            workflow_scope="team_mode",
            execution_mode="kickoff_only",
        ),
        outcome=AutomationOutcome(
            action="comment",
            summary="Kickoff dispatch completed.",
            comment="Lead reviewed the queue and dispatched the first developer task.",
        ),
    )

    ready_status = client.get(f"/api/tasks/{ready_dev_id}/automation")
    assert ready_status.status_code == 200
    ready_payload = ready_status.json()
    assert ready_payload["automation_state"] in {"queued", "running", "completed"}
    assert ready_payload.get("last_requested_source") == "lead_kickoff_dispatch"

    gated_status = client.get(f"/api/tasks/{gated_dev_id}/automation")
    assert gated_status.status_code == 200
    gated_payload = gated_status.json()
    assert gated_payload["automation_state"] == "idle"
    assert gated_payload.get("last_dispatch_decision") is None or gated_payload.get("last_dispatch_decision") == {}


def test_agents_chat_execution_intent_without_kickoff_does_not_dispatch_team_mode_kickoff(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead execution-intent kickoff task",
            "status": "To do",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Lead coordination task.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    from features.agents import api as agents_api

    from features.agents.executor import AutomationOutcome
    monkeypatch.setattr(
        agents_api,
        "execute_task_automation",
        lambda **_kwargs: AutomationOutcome(action="comment", summary="regular execution path", comment=None, usage=None),
    )
    monkeypatch.setattr(
        agents_api,
        "_classify_chat_instruction_intents",
        lambda **_kwargs: {
            "execution_intent": True,
            "execution_kickoff_intent": False,
            "project_creation_intent": False,
            "workflow_scope": "team_mode",
            "execution_mode": "resume_execution",
            "deploy_requested": False,
            "docker_compose_requested": False,
            "requested_port": None,
        },
    )

    kicked = client.post(
        "/api/agents/chat",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "instruction": "Continue implementation on Demo 99.",
        },
    )
    assert kicked.status_code == 200
    payload = kicked.json()
    assert payload["action"] == "comment"
    assert "kickoff" not in str(payload["summary"] or "").lower()

    automation_status = client.get(f"/api/tasks/{lead_task_id}/automation")
    assert automation_status.status_code == 200
    status_payload = automation_status.json()
    assert status_payload["automation_state"] == "idle"
    assert status_payload["last_requested_source"] in {None, ""}


def test_agents_chat_kickoff_requires_runnable_implementation_task(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Dev kickoff deterministic task",
            "status": "In Progress",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement deterministic kickoff validation for Dev dispatch.",
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    from features.agents import api as agents_api
    monkeypatch.setattr(
        agents_api,
        "_classify_chat_instruction_intents",
        lambda **_kwargs: {
            "execution_intent": True,
            "execution_kickoff_intent": True,
            "project_creation_intent": False,
            "workflow_scope": "team_mode",
            "execution_mode": "kickoff_only",
            "deploy_requested": False,
            "docker_compose_requested": False,
            "requested_port": None,
        },
    )

    kicked = client.post(
        "/api/agents/chat",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "instruction": "Start implementation",
        },
    )
    assert kicked.status_code == 200
    payload = kicked.json()
    assert payload["action"] in {"comment", "queued"}
    assert "kickoff" in str(payload["summary"] or "").lower()

    automation_status = client.get(f"/api/tasks/{dev_task_id}/automation")
    assert automation_status.status_code == 200
    status_payload = automation_status.json()
    assert status_payload["last_requested_source"] in {None, "", "manual", "lead_kickoff_dispatch"}


def test_agents_chat_kickoff_is_idempotent_when_lead_already_running(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead kickoff idempotency task",
            "status": "To do",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Lead coordination task.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    queued = client.post(
        f"/api/tasks/{lead_task_id}/automation/run",
        json={
            "instruction": "Team Mode kickoff for project test.\nDispatch-only run.",
            "execution_intent": True,
            "execution_kickoff_intent": True,
            "project_creation_intent": False,
            "workflow_scope": "team_mode",
            "execution_mode": "kickoff_only",
        },
    )
    assert queued.status_code == 200

    from features.agents import api as agents_api
    monkeypatch.setattr(
        agents_api,
        "_classify_chat_instruction_intents",
        lambda **_kwargs: {
            "execution_intent": True,
            "execution_kickoff_intent": True,
            "project_creation_intent": False,
        },
    )

    kicked = client.post(
        "/api/agents/chat",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "instruction": "kickoff",
        },
    )
    assert kicked.status_code == 200
    payload = kicked.json()
    assert payload["action"] == "comment"
    assert "already in progress" in str(payload["summary"] or "").lower()

    automation_status = client.get(f"/api/tasks/{lead_task_id}/automation")
    assert automation_status.status_code == 200
    status_payload = automation_status.json()
    assert status_payload["automation_state"] in {"queued", "running", "completed"}


def test_team_mode_kickoff_instruction_is_rejected_for_non_lead_task(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    dev_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Dev task kickoff guard",
            "status": "In Progress",
            "assignee_id": team["dev1"],
            "assigned_agent_code": "dev-a",
            "instruction": "Implement core gameplay engine.",
        },
    )
    assert dev_task.status_code == 200
    dev_task_id = dev_task.json()["id"]

    queued = client.post(
        f"/api/tasks/{dev_task_id}/automation/run",
        json={
            "instruction": f"Team Mode kickoff for project {project_id}.\nDispatch-only run.",
            "execution_intent": True,
            "execution_kickoff_intent": True,
            "project_creation_intent": False,
            "workflow_scope": "team_mode",
            "execution_mode": "kickoff_only",
        },
    )
    assert queued.status_code == 200
    payload = queued.json()
    assert bool(payload.get("skipped")) is True
    assert "lead-only" in str(payload.get("reason") or "").lower()

    status_payload = client.get(f"/api/tasks/{dev_task_id}/automation").json()
    assert status_payload["automation_state"] == "idle"
    assert status_payload["last_requested_source"] in {"", None}


def test_agents_chat_kickoff_promotes_plugin_policy_to_execution_mode(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    baseline_policy = client.post(
        "/api/project-rules",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Plugin Policy",
            "body": json.dumps(
                {
                    "mode": "setup",
                    "required_checks": {
                        "team_mode": [],
                        "delivery": [],
                    },
                    "runtime_deploy_health": {
                        "required": False,
                    },
                }
            ),
        },
    )
    assert baseline_policy.status_code == 200

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead deploy kickoff policy promotion task",
            "status": "To do",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "description": "Deploy target stack constructos-ws-default on port 6768 with /health.",
            "instruction": "Lead coordination task.",
        },
    )
    assert lead_task.status_code == 200

    from features.agents import api as agents_api

    monkeypatch.setattr(
        agents_api,
        "_classify_chat_instruction_intents",
        lambda **_kwargs: {
            "execution_intent": True,
            "execution_kickoff_intent": True,
            "project_creation_intent": False,
        },
    )

    kicked = client.post(
        "/api/agents/chat",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "instruction": "Start implementation",
        },
    )
    assert kicked.status_code == 200
    payload = kicked.json()
    assert payload["action"] == "comment"
    assert "kickoff" in str(payload["summary"] or "").lower()

    git_plugin_cfg = client.get(f"/api/projects/{project_id}/plugins/git_delivery")
    assert git_plugin_cfg.status_code == 200
    plugin_payload = git_plugin_cfg.json()
    assert plugin_payload["plugin_key"] == "git_delivery"
    assert plugin_payload["enabled"] is True
    config = plugin_payload.get("config") if isinstance(plugin_payload, dict) else {}
    assert isinstance(config, dict)
    required_checks = config.get("required_checks")
    assert isinstance(required_checks, dict)
    delivery_checks = required_checks.get("delivery")
    assert isinstance(delivery_checks, list)
    assert "git_contract_ok" in delivery_checks
    docker_plugin_cfg = client.get(f"/api/projects/{project_id}/plugins/docker_compose")
    assert docker_plugin_cfg.status_code == 200
    docker_payload = docker_plugin_cfg.json()
    assert docker_payload["plugin_key"] == "docker_compose"
    assert docker_payload["enabled"] is True
    runtime = (docker_payload.get("config") if isinstance(docker_payload, dict) else {}).get("runtime_deploy_health")
    assert isinstance(runtime, dict)
    assert runtime.get("port") == 6768


def test_runtime_deploy_target_resolver_parses_markdown_backtick_port(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead deploy orchestration",
            "status": "In Progress",
            "instruction": "Coordinate deployment.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    deploy_note = client.post(
        "/api/notes",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "task_id": lead_task_id,
            "title": "Deployment Intent",
            "body": "- Stack: `constructos-ws-default`\n- Port: `6768`\n- Health path: `/health`",
        },
    )
    assert deploy_note.status_code == 200

    from features.agents import api as agents_api
    from shared.models import SessionLocal

    with SessionLocal() as db:
        stack, port, health_path = agents_api._resolve_runtime_deploy_target_from_project_artifacts(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
        )

    assert stack == "constructos-ws-default"
    assert port == 6768
    assert health_path == "/health"


def test_resolve_project_repository_host_path_translates_task_app_workspace_bind(monkeypatch):
    from shared import project_repository as project_repo

    project_repo._resolve_container_bind_source.cache_clear()
    monkeypatch.setattr(project_repo, "resolve_workspace_root", lambda: Path("/home/app/workspace"))

    def fake_check_output(cmd, env=None, text=None, stderr=None):
        assert cmd[:3] == ["/usr/bin/docker-real", "inspect", "task-app"]
        return json.dumps(
            [
                {
                    "Destination": "/home/app/workspace",
                    "Source": "/srv/constructos/workspace",
                }
            ]
        )

    monkeypatch.setattr(project_repo.subprocess, "check_output", fake_check_output)

    host_repo = project_repo.resolve_project_repository_host_path(project_name="Tetris", project_id=None)

    assert host_repo == Path("/srv/constructos/workspace/.constructos/repos/tetris")
    project_repo._resolve_container_bind_source.cache_clear()


def test_resolve_project_repository_host_path_falls_back_when_bind_lookup_fails(monkeypatch):
    from shared import project_repository as project_repo

    project_repo._resolve_container_bind_source.cache_clear()
    monkeypatch.setattr(project_repo, "resolve_workspace_root", lambda: Path("/home/app/workspace"))

    def fake_check_output(*_args, **_kwargs):
        raise project_repo.subprocess.CalledProcessError(returncode=1, cmd=["docker", "inspect"])

    monkeypatch.setattr(project_repo.subprocess, "check_output", fake_check_output)

    host_repo = project_repo.resolve_project_repository_host_path(project_name="Tetris", project_id=None)

    assert host_repo == Path("/home/app/workspace/.constructos/repos/tetris")
    project_repo._resolve_container_bind_source.cache_clear()


def test_agents_chat_kickoff_is_processed_immediately_without_schedule_tick(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead immediate kickoff task",
            "status": "To do",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Lead coordination task.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    from features.agents import api as agents_api
    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome

    monkeypatch.setattr(
        agents_api,
        "_classify_chat_instruction_intents",
        lambda **_kwargs: {
            "execution_intent": True,
            "execution_kickoff_intent": True,
            "project_creation_intent": False,
        },
    )
    monkeypatch.setattr(
        runner_module,
        "execute_task_automation",
        lambda **_kwargs: AutomationOutcome(action="comment", summary="Kickoff dispatch done", comment=None, usage=None),
    )

    kicked = client.post(
        "/api/agents/chat",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "instruction": "Start implementation",
        },
    )
    assert kicked.status_code == 200
    assert "kickoff" in str(kicked.json().get("summary") or "").lower()

    runner_module.run_queued_automation_once(limit=1)
    status_payload = client.get(f"/api/tasks/{lead_task_id}/automation").json()
    assert status_payload["automation_state"] == "completed"


def test_verify_delivery_workflow_rejects_legacy_evaluation_mode_config(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})
    svc_module._PROJECT_POLICY_CHECKS_LLM_EVAL_CACHE.clear()

    def _fake_run_structured_codex_prompt(**kwargs):
        raise AssertionError(f"LLM policy evaluation should not be called in core deterministic mode: {kwargs}")

    monkeypatch.setattr(svc_module, "run_structured_codex_prompt", _fake_run_structured_codex_prompt)

    patched_project = client.patch(
        f"/api/projects/{project_id}",
        json={"description": "repository process branch commit workflow"},
    )
    assert patched_project.status_code == 200

    service = AgentTaskService()
    with pytest.raises(HTTPException) as exc:
        service.apply_project_plugin_config(
            project_id=project_id,
            workspace_id=ws_id,
            plugin_key="git_delivery",
            enabled=True,
            config={"evaluation": {"mode": "hybrid"}},
        )
    assert exc.value.status_code == 409
    detail = exc.value.detail if isinstance(exc.value.detail, dict) else {}
    errors = detail.get("errors") if isinstance(detail.get("errors"), list) else []
    assert any(str(err.get("path") or "") == "evaluation" for err in errors if isinstance(err, dict))


def test_verify_delivery_workflow_core_mode_uses_runtime_checks_only(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", {project_id})
    svc_module._PROJECT_POLICY_CHECKS_LLM_EVAL_CACHE.clear()

    monkeypatch.setattr(
        svc_module,
        "run_structured_codex_prompt",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError(f"LLM policy evaluation should not be called in core deterministic mode: {kwargs}")
        ),
    )

    service = AgentTaskService()
    service.apply_project_plugin_config(
        project_id=project_id,
        workspace_id=ws_id,
        plugin_key="git_delivery",
        enabled=True,
        config={
            "required_checks": {"delivery": ["repo_context_present"]},
        },
    )
    result = service.verify_delivery_workflow(project_id=project_id, workspace_id=ws_id)
    assert isinstance(result["checks"]["repo_context_present"], bool)
    assert isinstance(result["checks"]["runtime_deploy_health_ok"], bool)
    assert "repo_context_present" in result["required_checks"]
    assert "runtime_deploy_health_ok" in result["required_checks"]
    assert isinstance(result["ok"], bool)


def test_project_checks_verify_endpoint_returns_payload(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    project_id = bootstrap['projects'][0]['id']

    response = client.get(f"/api/projects/{project_id}/checks/verify")
    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == project_id
    assert "team_mode" in payload
    assert "delivery" in payload
    assert "catalog" in payload
    assert "ok" in payload


def test_agents_chat_stream_execution_kickoff_dispatches_team_lead_and_skips_long_run(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead stream kickoff",
            "status": "To do",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Lead stream coordination.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    from features.agents import api as agents_api

    def _should_not_run_stream(**_kwargs):
        raise AssertionError("execute_task_automation_stream should not run for execution kickoff dispatch")

    monkeypatch.setattr(agents_api, "execute_task_automation_stream", _should_not_run_stream)
    monkeypatch.setattr(
        agents_api,
        "_classify_chat_instruction_intents",
        lambda **_kwargs: {
            "execution_intent": True,
            "execution_kickoff_intent": True,
            "project_creation_intent": False,
        },
    )

    kicked = client.post(
        "/api/agents/chat/stream",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "instruction": 'Start implementation of "Demo 99" project.',
        },
    )
    assert kicked.status_code == 200
    lines = [line for line in (kicked.text or "").splitlines() if line.strip()]
    assert len(lines) >= 1
    final_payload = json.loads(lines[-1])
    assert str(final_payload.get("type") or "") == "final"
    response = final_payload.get("response") or {}
    assert "kickoff" in str(response.get("summary") or "").lower()

    automation_status = client.get(f"/api/tasks/{lead_task_id}/automation")
    assert automation_status.status_code == 200
    status_payload = automation_status.json()
    assert status_payload["automation_state"] in {"queued", "running", "completed"}
    assert status_payload["last_requested_source"] == "manual"


def test_agents_chat_execution_kickoff_uses_session_project_when_project_omitted(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    session_id = 'chat-kickoff-session-project-fallback'

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    lead_task = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Lead fallback kickoff task",
            "status": "To do",
            "assignee_id": team["lead"],
            "assigned_agent_code": "lead-a",
            "instruction": "Lead fallback coordination task.",
        },
    )
    assert lead_task.status_code == 200
    lead_task_id = lead_task.json()["id"]

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    monkeypatch.setattr(
        agents_api,
        "execute_task_automation",
        lambda **_: AutomationOutcome(action="comment", summary="seeded", comment=None, usage=None),
    )
    monkeypatch.setattr(
        agents_api,
        "_classify_chat_instruction_intents",
        lambda **_kwargs: {
            "execution_intent": True,
            "execution_kickoff_intent": True,
            "project_creation_intent": False,
        },
    )

    seeded = client.post(
        "/api/agents/chat",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "session_id": session_id,
            "instruction": "Seed session in project context",
        },
    )
    assert seeded.status_code == 200

    kicked = client.post(
        "/api/agents/chat",
        json={
            "workspace_id": ws_id,
            "session_id": session_id,
            "instruction": "start implementation",
        },
    )
    assert kicked.status_code == 200
    payload = kicked.json()
    assert "kickoff" in str(payload.get("summary") or "").lower()

    automation_status = client.get(f"/api/tasks/{lead_task_id}/automation")
    assert automation_status.status_code == 200
    status_payload = automation_status.json()
    assert status_payload["automation_state"] in {"queued", "running", "completed"}
    assert status_payload["last_requested_source"] == "manual"


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
    assert calls[0]['timeout_seconds'] == 0
    assert calls[1]['allow_mutations'] is True
    assert "[Compacted conversation context]" in calls[1]['instruction']
    assert calls[1]['timeout_seconds'] == 0


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


def test_agents_chat_endpoint_injects_execution_mandate_for_begin_with_implementation(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    captured = {}

    def _fake_execute_task_automation(**kwargs):
        captured.update(kwargs)
        return AutomationOutcome(action='comment', summary='ok', comment=None, usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)
    monkeypatch.setattr(
        agents_api,
        '_classify_chat_instruction_intents',
        lambda **_kwargs: {
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
        },
    )

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Begin with implementation',
            'allow_mutations': True,
            'history': [],
        },
    )
    assert res.status_code == 200
    assert 'Execution intent detected for this project.' in captured['instruction']
    assert 'Completion contract for execution kickoff' in captured['instruction']
    assert 'Run tests/validation and include concrete results.' in captured['instruction']


def test_agents_chat_endpoint_does_not_inject_execution_mandate_for_create_project_prompt(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

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
            'instruction': 'Create project and begin implementation',
            'allow_mutations': True,
            'history': [],
        },
    )
    assert res.status_code == 200
    assert 'Execution intent detected for this project.' not in captured['instruction']


def test_agents_chat_ignores_stale_project_id_for_project_creation_intent(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome

    captured = {}

    def _fake_execute_task_automation(**kwargs):
        captured.update(kwargs)
        return AutomationOutcome(action='comment', summary='ok', comment=None, usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)
    monkeypatch.setattr(
        agents_api,
        '_classify_chat_instruction_intents',
        lambda **_kwargs: {
            'execution_intent': False,
            'execution_kickoff_intent': False,
            'project_creation_intent': True,
        },
    )

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': '11111111-1111-1111-1111-111111111111',
            'instruction': 'Create a new project with 5 tasks',
            'allow_mutations': True,
            'history': [],
        },
    )
    assert res.status_code == 200
    assert captured.get('project_id') is None


def test_agents_chat_returns_404_for_stale_project_id_when_not_creation_intent(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': '11111111-1111-1111-1111-111111111111',
            'instruction': 'Continue implementation',
            'allow_mutations': True,
            'history': [],
        },
    )
    assert res.status_code == 404
    assert 'Project not found' in res.text


def test_execution_evidence_violations_detect_missing_task_evidence_for_execution_statuses(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    project_id = bootstrap['projects'][0]['id']
    user_id = bootstrap['current_user']['id']

    from features.agents import api as agents_api
    from shared.models import CommandExecution, SessionLocal

    started = datetime.now(timezone.utc) - timedelta(seconds=5)
    with SessionLocal() as db:
        db.add(
            CommandExecution(
                command_id="test-exec-evidence-1",
                command_name="Task.Patch",
                user_id=user_id,
                response_json=json.dumps(
                    {
                        "id": "task-1",
                        "project_id": project_id,
                        "title": "Implement endpoint",
                            "status": "Completed",
                        "external_refs": [],
                    }
                ),
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        violations = agents_api._collect_execution_evidence_violations(
            db=db,
            user_id=user_id,
            project_id=project_id,
            run_started_at=started,
        )
    assert len(violations) == 1
    assert violations[0]["task_id"] == "task-1"


def test_execution_evidence_violations_accept_linked_note_without_external_ref(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    user_id = bootstrap['current_user']['id']

    from features.agents import api as agents_api
    from shared.models import CommandExecution, Note, SessionLocal

    started = datetime.now(timezone.utc) - timedelta(seconds=5)
    with SessionLocal() as db:
        db.add(
            CommandExecution(
                command_id="test-exec-evidence-2",
                command_name="Task.Patch",
                user_id=user_id,
                response_json=json.dumps(
                    {
                        "id": "task-2",
                        "project_id": project_id,
                        "title": "Implement endpoint",
                        "status": "Completed",
                        "external_refs": [],
                    }
                ),
                created_at=datetime.now(timezone.utc),
            )
        )
        db.add(
            Note(
                workspace_id=ws_id,
                project_id=project_id,
                task_id="task-2",
                title="Implementation Evidence",
                body="Smoke passed.",
                created_by=user_id,
                updated_by=user_id,
            )
        )
        db.commit()

        violations = agents_api._collect_execution_evidence_violations(
            db=db,
            user_id=user_id,
            project_id=project_id,
            run_started_at=started,
        )
    assert violations == []


def test_agents_chat_execution_intent_fails_contract_when_task_evidence_missing(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    user_id = bootstrap['current_user']['id']

    from features.agents import api as agents_api
    from features.agents.executor import AutomationOutcome
    from shared.models import CommandExecution, SessionLocal

    seq = {"n": 0}

    def _fake_execute_task_automation(**kwargs):
        seq["n"] += 1
        with SessionLocal() as db:
            db.add(
                CommandExecution(
                    command_id=f"test-exec-evidence-run-{seq['n']}",
                    command_name="Task.Patch",
                    user_id=user_id,
                    response_json=json.dumps(
                        {
                            "id": f"task-{seq['n']}",
                            "project_id": project_id,
                            "title": "Dev task",
                            "status": "In Review",
                            "external_refs": [],
                        }
                    ),
                    created_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        return AutomationOutcome(action='comment', summary='Execution done', comment='status moved', usage=None)

    monkeypatch.setattr(agents_api, 'execute_task_automation', _fake_execute_task_automation)
    monkeypatch.setattr(
        agents_api,
        '_classify_chat_instruction_intents',
        lambda **_kwargs: {
            'execution_intent': True,
            'execution_kickoff_intent': False,
            'project_creation_intent': False,
        },
    )

    res = client.post(
        '/api/agents/chat',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Begin with implementation',
            'allow_mutations': True,
            'history': [],
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload['ok'] is False
    assert 'Execution incomplete' in payload['summary']
    assert 'evidence' in str(payload['comment']).lower()


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


def test_create_task_infers_scheduled_type_from_schedule_fields(tmp_path):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']
    project_id = client.get('/api/bootstrap').json()['projects'][0]['id']
    due_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Inferred scheduled',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Leave progress note',
            'scheduled_at_utc': due_at,
            'recurring_rule': 'every:1d',
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload['task_type'] == 'scheduled_instruction'
    assert payload['recurring_rule'] == 'every:1d'


def test_create_task_rejects_schedule_fields_with_manual_task_type(tmp_path):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']
    project_id = client.get('/api/bootstrap').json()['projects'][0]['id']

    res = client.post(
        '/api/tasks',
        json={
            'title': 'Manual with recurring',
            'workspace_id': ws_id,
            'project_id': project_id,
            'task_type': 'manual',
            'recurring_rule': 'every:1d',
        },
    )
    assert res.status_code == 422
    assert 'manual' in res.text and 'scheduled_instruction' in res.text


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
    moved = client.patch(f'/api/tasks/{task_id}', json={'status': 'In Progress'})
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
    moved = client.patch(f'/api/tasks/{task_id}', json={'status': 'In Progress'})
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
    assert schedule_trigger.get('run_on_statuses') == ['To Do']

    from features.agents.runner import queue_due_scheduled_tasks_once

    queued = queue_due_scheduled_tasks_once(limit=10)
    assert queued >= 1

    status = client.get(f'/api/tasks/{task_id}/automation').json()
    assert status['automation_state'] in {'queued', 'running', 'completed'}


def test_team_mode_scheduled_lead_task_can_autorun_on_awaiting_decision_schedule(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    due_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    lead_assignee_id = team["lead"]

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Team Mode Lead Scheduled',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'assignee_id': lead_assignee_id,
            'assigned_agent_code': 'lead-a',
            'task_type': 'scheduled_instruction',
            'scheduled_instruction': 'Lead oversight cycle',
            'scheduled_at_utc': due_at,
            'recurring_rule': 'every:5m',
            'execution_triggers': [
                {
                    'kind': 'schedule',
                    'enabled': True,
                    'scheduled_at_utc': due_at,
                    'run_on_statuses': ['Awaiting decision'],
                    'recurring_rule': 'every:5m',
                },
            ],
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    from features.agents.runner import queue_due_scheduled_tasks_once

    queued = queue_due_scheduled_tasks_once(limit=10)
    assert queued >= 1

    status = client.get(f'/api/tasks/{task_id}/automation').json()
    assert status['automation_state'] in {'queued', 'running', 'completed'}
    assert status['last_requested_source'] == 'schedule'


def test_team_mode_happy_path_queue_respects_plugin_policy_mode(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    plugin_rule = client.post(
        '/api/project-rules',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Plugin Policy',
            'body': json.dumps({'mode': 'setup'}),
        },
    )
    assert plugin_rule.status_code == 200

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Lead kickoff task gated by setup mode',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Coordinate team kickoff.',
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    from features.agents.runner import queue_team_mode_happy_path_once

    queued_setup = queue_team_mode_happy_path_once(limit=20)
    assert queued_setup == 0
    status_setup = client.get(f"/api/tasks/{task_id}/automation").json()
    assert status_setup['automation_state'] == 'idle'

    updated = client.patch(
        f"/api/project-rules/{plugin_rule.json()['id']}",
        json={'body': json.dumps({'mode': 'execution'})},
    )
    assert updated.status_code == 200

    kickoff = client.post(
        f"/api/tasks/{task_id}/automation/run",
        json={
            "instruction": "Start implementation.",
            "execution_intent": True,
            "execution_kickoff_intent": True,
            "project_creation_intent": False,
            "workflow_scope": "team_mode",
            "execution_mode": "kickoff_only",
        },
    )
    assert kickoff.status_code == 200

    queued_execution = queue_team_mode_happy_path_once(limit=20)
    assert queued_execution >= 0
    status_execution = client.get(f"/api/tasks/{task_id}/automation").json()
    assert status_execution['automation_state'] in {'queued', 'running', 'completed'}


def test_team_mode_happy_path_defers_qa_until_lead_handoff(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    plugin_rule = client.post(
        '/api/project-rules',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Plugin Policy',
            'body': json.dumps({'mode': 'execution'}),
        },
    )
    assert plugin_rule.status_code == 200

    lead_task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead orchestration',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Coordinate merge and deploy handoff.',
        },
    )
    assert lead_task.status_code == 200
    qa_task = client.post(
        '/api/tasks',
        json={
            'title': 'QA validation',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': team['qa'],
            'assigned_agent_code': 'qa-a',
            'instruction': 'Run validation on deployed app.',
        },
    )
    assert qa_task.status_code == 200

    from features.agents.runner import queue_team_mode_happy_path_once

    kickoff = client.post(
        f"/api/tasks/{lead_task.json()['id']}/automation/run",
        json={'instruction': 'Start lead orchestration.'},
    )
    assert kickoff.status_code == 200

    queued = queue_team_mode_happy_path_once(limit=20)
    assert queued >= 0

    lead_status = client.get(f"/api/tasks/{lead_task.json()['id']}/automation").json()
    qa_status = client.get(f"/api/tasks/{qa_task.json()['id']}/automation").json()
    assert lead_status['automation_state'] in {'queued', 'running', 'completed'}
    assert qa_status['automation_state'] == 'idle'


def test_queue_team_mode_happy_path_once_does_not_auto_requeue_plain_lead_task(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    plugin_rule = client.post(
        '/api/project-rules',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Plugin Policy',
            'body': json.dumps({'mode': 'execution'}),
        },
    )
    assert plugin_rule.status_code == 200

    lead_task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead coordination task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Coordinate team execution.',
        },
    )
    assert lead_task.status_code == 200
    task_id = lead_task.json()['id']

    from shared.eventing import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    completed_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=task_id,
            event_type='TaskAutomationCompleted',
            payload={'completed_at': completed_at, 'summary': 'Lead cycle complete.'},
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': task_id},
        )
        db.commit()

    from features.agents.runner import queue_team_mode_happy_path_once

    queued = queue_team_mode_happy_path_once(limit=20)
    assert queued == 0

    status_payload = client.get(f'/api/tasks/{task_id}/automation').json()
    assert status_payload['automation_state'] == 'completed'


def test_runner_skips_duplicate_team_mode_progress_comment_when_state_fingerprint_is_unchanged(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", ws_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {ws_id})
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_PROJECT_IDS", set())

    service = AgentTaskService()
    setup = service.setup_project_orchestration(
        name="Progress Fingerprint Project",
        short_description="Regression coverage for repeated lead progress comments.",
        workspace_id=ws_id,
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=False,
        seed_team_tasks=False,
        kickoff_after_setup=False,
        command_id="progress-fingerprint-project",
    )
    project_id = str((setup.get("project") or {}).get("id") or "").strip()
    assert project_id

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)
    specification = service.create_specification(
        title="Fingerprint Spec",
        workspace_id=ws_id,
        project_id=project_id,
        auth_token="",
        command_id="progress-fingerprint-spec",
    )
    specification_id = str(specification.get("id") or "").strip()
    assert specification_id

    dev_task = service.create_task(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        title="Developer task",
        status="In Progress",
        assignee_id=team["dev1"],
        assigned_agent_code="dev-a",
        instruction="Implement work.",
        auth_token="",
        command_id="progress-fingerprint-dev",
    )
    lead_task = service.create_task(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        title="Lead task",
        status="Awaiting decision",
        assignee_id=team["lead"],
        assigned_agent_code="lead-a",
        instruction="Lead the cycle.",
        auth_token="",
        command_id="progress-fingerprint-lead",
    )
    qa_task = service.create_task(
        workspace_id=ws_id,
        project_id=project_id,
        specification_id=specification_id,
        title="QA task",
        status="In Progress",
        assignee_id=team["qa"],
        assigned_agent_code="qa-a",
        instruction="Validate output.",
        auth_token="",
        command_id="progress-fingerprint-qa",
    )

    dev_task_id = str(dev_task.get("id") or "").strip()
    lead_task_id = str(lead_task.get("id") or "").strip()
    qa_task_id = str(qa_task.get("id") or "").strip()
    assert dev_task_id and lead_task_id and qa_task_id

    from features.agents.runner import _should_persist_team_mode_progress_comment
    from shared.eventing import append_event, rebuild_state
    from shared.models import SessionLocal
    from features.tasks.domain import EVENT_UPDATED as TASK_EVENT_UPDATED
    from shared.settings import AGENT_SYSTEM_USER_ID

    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=dev_task_id,
            event_type=TASK_EVENT_UPDATED,
            payload={'status': 'Blocked'},
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': dev_task_id},
        )
        db.commit()

    with SessionLocal() as db:
        lead_state, _ = rebuild_state(db, 'Task', lead_task_id)
        should_persist, fingerprint = _should_persist_team_mode_progress_comment(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            task_id=lead_task_id,
            state=lead_state,
            assignee_role='Lead',
        )
        assert should_persist is True
        assert fingerprint

        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=lead_task_id,
            event_type=TASK_EVENT_UPDATED,
            payload={
                'last_progress_comment_fingerprint': fingerprint,
                'last_progress_comment_at': datetime.now(timezone.utc).isoformat(),
            },
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': lead_task_id},
        )
        db.commit()

        refreshed_state, _ = rebuild_state(db, 'Task', lead_task_id)
        should_persist_again, fingerprint_again = _should_persist_team_mode_progress_comment(
            db=db,
            workspace_id=ws_id,
            project_id=project_id,
            task_id=lead_task_id,
            state=refreshed_state,
            assignee_role='Lead',
        )
        assert fingerprint_again == fingerprint
        assert should_persist_again is False


def test_team_mode_closeout_completes_remaining_tasks_when_delivery_is_green(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    plugin_rule = client.post(
        '/api/project-rules',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Plugin Policy',
            'body': json.dumps({'mode': 'execution'}),
        },
    )
    assert plugin_rule.status_code == 200

    dev_task = client.post(
        '/api/tasks',
        json={
            'title': 'Dev task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Review',
            'assignee_id': team['dev1'],
            'assigned_agent_code': 'dev-a',
            'instruction': 'Dev done, ready for closeout.',
            'external_refs': [{'url': 'commit:deadbeef1'}, {'url': 'merge:main:deadbeef1'}],
        },
    )
    assert dev_task.status_code == 200
    lead_task = client.post(
        '/api/tasks',
        json={
            'title': 'Lead deploy task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Awaiting decision',
            'assignee_id': team['lead'],
            'assigned_agent_code': 'lead-a',
            'instruction': 'Lead deploy complete.',
        },
    )
    assert lead_task.status_code == 200
    qa_task = client.post(
        '/api/tasks',
        json={
            'title': 'QA task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Completed',
            'assignee_id': team['qa'],
            'assigned_agent_code': 'qa-a',
            'instruction': 'QA already done.',
        },
    )
    assert qa_task.status_code == 200

    from features.agents.service import AgentTaskService

    def _delivery_ok(self, *, project_id: str, auth_token=None, workspace_id=None):
        return {
            "ok": True,
            "checks": {
                "repo_context_present": True,
                "git_contract_ok": True,
                "compose_manifest_present": True,
                "lead_deploy_decision_evidence_present": True,
                "qa_handoff_current_cycle_ok": True,
                "deploy_serves_application_root": True,
                "qa_has_verifiable_artifacts": True,
                "deploy_execution_evidence_present": True,
                "runtime_deploy_health_ok": True,
            },
        }

    monkeypatch.setattr(AgentTaskService, "verify_delivery_workflow", _delivery_ok)

    from features.agents.runner import closeout_team_mode_tasks_once

    closed = closeout_team_mode_tasks_once(limit=20)
    assert closed >= 2

    dev_view = client.get(f"/api/tasks/{dev_task.json()['id']}").json()
    lead_view = client.get(f"/api/tasks/{lead_task.json()['id']}").json()
    qa_view = client.get(f"/api/tasks/{qa_task.json()['id']}").json()
    assert isinstance(dev_view.get("completed_at"), str) and dev_view["completed_at"]
    assert isinstance(lead_view.get("completed_at"), str) and lead_view["completed_at"]
    assert qa_view["status"] == "Completed"


def test_closeout_team_mode_tasks_once_skips_running_qa_task(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _configure_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    qa_task = client.post(
        '/api/tasks',
        json={
            'title': 'QA task still running',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': team['qa'],
            'assigned_agent_code': 'qa-a',
            'instruction': 'Run QA checks.',
        },
    )
    assert qa_task.status_code == 200
    task_id = qa_task.json()['id']

    from shared.eventing import append_event
    from shared.models import SessionLocal
    from shared.settings import AGENT_SYSTEM_USER_ID

    started_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type='Task',
            aggregate_id=task_id,
            event_type='TaskAutomationStarted',
            payload={'started_at': started_at},
            metadata={'actor_id': AGENT_SYSTEM_USER_ID, 'workspace_id': ws_id, 'project_id': project_id, 'task_id': task_id},
        )
        db.commit()

    from features.agents.service import AgentTaskService

    def _delivery_ok(self, *, project_id: str, auth_token=None, workspace_id=None):
        return {
            'ok': True,
            'checks': {
                'repo_context_present': True,
                'git_contract_ok': True,
                'compose_manifest_present': True,
                'lead_deploy_decision_evidence_present': True,
                'qa_handoff_current_cycle_ok': True,
                'deploy_serves_application_root': True,
                'qa_has_verifiable_artifacts': True,
                'deploy_execution_evidence_present': True,
            },
        }

    monkeypatch.setattr(AgentTaskService, 'verify_delivery_workflow', _delivery_ok)

    from features.agents.runner import closeout_team_mode_tasks_once

    _ = closeout_team_mode_tasks_once(limit=20)

    qa_view = client.get(f'/api/tasks/{task_id}').json()
    qa_status = client.get(f'/api/tasks/{task_id}/automation').json()
    assert qa_view['status'] == 'In Progress'
    assert qa_status['automation_state'] == 'running'


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
    moved = client.patch(f'/api/tasks/{task_id}', json={'status': 'In Progress'})
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
    assert payload['last_requested_trigger_task_id'] == task_id
    assert payload['last_requested_from_status'] == 'To Do'
    assert payload['last_requested_to_status'] == 'Done'
    assert isinstance(payload.get('last_requested_triggered_at'), str)
    assert payload['last_requested_triggered_at']


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


def test_runner_passes_status_change_trigger_metadata_to_executor(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    source = client.post(
        '/api/tasks',
        json={
            'title': 'Metadata source',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    assert source.status_code == 200
    source_id = source.json()['id']

    target = client.post(
        '/api/tasks',
        json={
            'title': 'Metadata target',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Capture metadata',
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

    import features.agents.runner as runner_module
    from features.agents.executor import AutomationOutcome

    captured: dict[str, str | None] = {}

    def capture_executor(**kwargs):
        captured['trigger_task_id'] = kwargs.get('trigger_task_id')
        captured['trigger_from_status'] = kwargs.get('trigger_from_status')
        captured['trigger_to_status'] = kwargs.get('trigger_to_status')
        captured['trigger_timestamp'] = kwargs.get('trigger_timestamp')
        return AutomationOutcome(action='comment', summary='Captured metadata.', comment='ok')

    monkeypatch.setattr(runner_module, "execute_task_automation", capture_executor)
    processed = runner_module.run_queued_automation_once(limit=5)
    assert processed >= 1

    assert captured['trigger_task_id'] == source_id
    assert captured['trigger_from_status'] == 'To Do'
    assert captured['trigger_to_status'] == 'Done'
    assert isinstance(captured.get('trigger_timestamp'), str)
    assert captured['trigger_timestamp']

    automation = client.get(f'/api/tasks/{target_id}/automation')
    assert automation.status_code == 200
    payload = automation.json()
    assert payload['automation_state'] == 'completed'
    assert payload['last_requested_trigger_task_id'] == source_id
    assert payload['last_requested_from_status'] == 'To Do'
    assert payload['last_requested_to_status'] == 'Done'
    assert isinstance(payload.get('last_requested_triggered_at'), str)
    assert payload['last_requested_triggered_at']


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
    assert payload['last_requested_trigger_task_id'] == source_id
    assert payload['last_requested_from_status'] == 'To Do'
    assert payload['last_requested_to_status'] == 'Done'
    assert isinstance(payload.get('last_requested_triggered_at'), str)
    assert payload['last_requested_triggered_at']


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


def test_task_patch_rejects_external_status_trigger_self_reference(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Self external guard task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Initial instruction',
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    patched = client.patch(
        f'/api/tasks/{task_id}',
        json={
            'instruction': 'Should fail due to self external selector',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'scope': 'external',
                    'to_statuses': ['Done'],
                    'selector': {'task_ids': [task_id]},
                }
            ],
        },
    )
    assert patched.status_code == 422
    assert 'cannot include the same task id' in str(patched.json().get('detail') or '')


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


def test_status_change_triggers_queue_pending_requests_when_target_is_busy(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    source_a = client.post(
        '/api/tasks',
        json={
            'title': 'Busy queue source A',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    source_b = client.post(
        '/api/tasks',
        json={
            'title': 'Busy queue source B',
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
            'title': 'Busy queue target',
            'workspace_id': ws_id,
            'project_id': project_id,
            'instruction': 'Audit status change',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'enabled': True,
                    'scope': 'external',
                    'match_mode': 'any',
                    'selector': {'task_ids': [source_a_id, source_b_id]},
                    'to_statuses': ['Done'],
                },
            ],
        },
    )
    assert target.status_code == 200
    target_id = target.json()['id']

    complete_a = client.post(f'/api/tasks/{source_a_id}/complete')
    complete_b = client.post(f'/api/tasks/{source_b_id}/complete')
    assert complete_a.status_code == 200
    assert complete_b.status_code == 200

    queued = client.get(f'/api/tasks/{target_id}/automation')
    assert queued.status_code == 200
    queued_payload = queued.json()
    assert queued_payload['automation_state'] == 'queued'
    assert int(queued_payload.get('automation_pending_requests') or 0) >= 1

    from features.agents.runner import run_queued_automation_once

    first_processed = run_queued_automation_once(limit=10)
    assert first_processed >= 1
    after_first = client.get(f'/api/tasks/{target_id}/automation')
    assert after_first.status_code == 200
    after_first_payload = after_first.json()
    assert after_first_payload['automation_state'] == 'queued'

    second_processed = run_queued_automation_once(limit=10)
    assert second_processed >= 1
    after_second = client.get(f'/api/tasks/{target_id}/automation')
    assert after_second.status_code == 200
    after_second_payload = after_second.json()
    assert after_second_payload['automation_state'] == 'completed'
    assert int(after_second_payload.get('automation_pending_requests') or 0) == 0


def test_runner_reconciles_satisfied_external_status_triggers_for_team_mode(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    team = _enable_team_mode_for_project(client, ws_id=ws_id, project_id=project_id)

    members = client.get(f"/api/projects/{project_id}/members")
    assert members.status_code == 200
    qa_assignee_id = next(item for item in members.json()["items"] if item["role"] == "QAAgent")["user_id"]
    dev_assignee_id = next(item for item in members.json()["items"] if item["role"] == "DeveloperAgent")["user_id"]

    qa_task = client.post(
        '/api/tasks',
        json={
            'title': 'QA blocked source',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'Blocked',
            'assignee_id': qa_assignee_id,
            'instruction': 'Record blocked reason',
        },
    )
    assert qa_task.status_code == 200
    qa_task_id = qa_task.json()['id']

    bug_task = client.post(
        '/api/tasks',
        json={
            'title': 'Dev bug fix task',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
            'assignee_id': dev_assignee_id,
            'instruction': 'Fix QA-reported bug and attach commit evidence.',
            'execution_triggers': [
                {
                    'kind': 'status_change',
                    'enabled': True,
                    'scope': 'external',
                    'selector': {'task_ids': [qa_task_id]},
                    'to_statuses': ['Blocked'],
                    'action': 'request_automation',
                }
            ],
        },
    )
    assert bug_task.status_code == 200
    bug_task_id = bug_task.json()['id']

    from features.agents.runner import queue_satisfied_external_status_triggers_once

    queued = queue_satisfied_external_status_triggers_once(limit=20)
    assert queued >= 1

    automation = client.get(f'/api/tasks/{bug_task_id}/automation')
    assert automation.status_code == 200
    payload = automation.json()
    assert payload['automation_state'] == 'queued'
    assert payload.get('last_requested_source') == 'trigger_reconcile'
    assert payload.get('last_requested_trigger_task_id') == qa_task_id


def test_create_task_requires_project_id(tmp_path):
    client = build_client(tmp_path)
    ws_id = client.get('/api/bootstrap').json()['workspaces'][0]['id']
    res = client.post('/api/tasks', json={'title': 'No project', 'workspace_id': ws_id})
    assert res.status_code == 422


def test_create_task_accepts_status_on_create(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post(
        '/api/tasks',
        json={
            'title': 'REST create with explicit status',
            'workspace_id': ws_id,
            'project_id': project_id,
            'status': 'In Progress',
        },
    )
    assert created.status_code == 200
    assert created.json()['status'] == 'In Progress'


def test_create_task_rejects_unresolvable_non_uuid_assignee_id(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    created_project = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Invalid Assignee Project'})
    assert created_project.status_code == 200
    project_id = created_project.json()['id']

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Task with invalid assignee',
            'workspace_id': ws_id,
            'project_id': project_id,
            'assignee_id': 'Tr1n1ty',
        },
    )
    assert created.status_code == 422
    assert created.json()['detail'] == 'assignee_id must be a project-member user_id UUID or resolvable member username/full name'


def test_create_task_resolves_member_username_assignee_id(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    current_user = bootstrap['current_user']

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Task with username assignee',
            'workspace_id': ws_id,
            'project_id': project_id,
            'assignee_id': current_user['username'],
        },
    )
    assert created.status_code == 200
    assert created.json()['assignee_id'] == current_user['id']


def test_create_task_returns_aggregate_fallback_when_view_unavailable(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    import features.tasks.command_handlers as task_handlers

    monkeypatch.setattr(task_handlers, "load_task_view", lambda db, task_id: None)

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Fallback task response',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload['title'] == 'Fallback task response'
    assert payload['workspace_id'] == ws_id
    assert payload['project_id'] == project_id
    assert payload['status'] == 'To Do'


def test_patch_task_rejects_unresolvable_non_uuid_assignee_id(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Patch invalid assignee',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    patched = client.patch(
        f'/api/tasks/{task_id}',
        json={
            'assignee_id': 'Tr1n1ty',
        },
    )
    assert patched.status_code == 422
    assert patched.json()['detail'] == 'assignee_id must be a project-member user_id UUID or resolvable member username/full name'


def test_patch_task_resolves_member_full_name_assignee_id(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    current_user = bootstrap['current_user']

    created = client.post(
        '/api/tasks',
        json={
            'title': 'Patch assignee by full name',
            'workspace_id': ws_id,
            'project_id': project_id,
        },
    )
    assert created.status_code == 200
    task_id = created.json()['id']

    patched = client.patch(
        f'/api/tasks/{task_id}',
        json={
            'assignee_id': current_user['full_name'],
        },
    )
    assert patched.status_code == 200
    assert patched.json()['assignee_id'] == current_user['id']


def test_create_note_returns_aggregate_fallback_when_view_unavailable(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    import features.notes.command_handlers as note_handlers

    monkeypatch.setattr(note_handlers, "load_note_view", lambda db, note_id: None)

    created = client.post(
        '/api/notes',
        json={
            'title': 'Fallback note response',
            'workspace_id': ws_id,
            'project_id': project_id,
            'body': 'hello',
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload['title'] == 'Fallback note response'
    assert payload['workspace_id'] == ws_id
    assert payload['project_id'] == project_id
    assert payload['body'] == 'hello'


def test_create_task_group_returns_aggregate_fallback_when_view_unavailable(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    import features.task_groups.command_handlers as task_group_handlers

    monkeypatch.setattr(task_group_handlers, "load_task_group_view", lambda db, group_id: None)

    created = client.post(
        '/api/task-groups',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'name': 'Fallback Task Group',
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload['name'] == 'Fallback Task Group'
    assert payload['workspace_id'] == ws_id
    assert payload['project_id'] == project_id


def test_create_note_group_returns_aggregate_fallback_when_view_unavailable(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    import features.note_groups.command_handlers as note_group_handlers

    monkeypatch.setattr(note_group_handlers, "load_note_group_view", lambda db, group_id: None)

    created = client.post(
        '/api/note-groups',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'name': 'Fallback Note Group',
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload['name'] == 'Fallback Note Group'
    assert payload['workspace_id'] == ws_id
    assert payload['project_id'] == project_id


def test_create_project_rule_returns_aggregate_fallback_when_view_unavailable(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    import features.rules.command_handlers as rule_handlers

    monkeypatch.setattr(rule_handlers, "load_project_rule_view", lambda db, rule_id: None)

    created = client.post(
        '/api/project-rules',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Fallback Rule',
            'body': 'Rule body',
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload['title'] == 'Fallback Rule'
    assert payload['workspace_id'] == ws_id
    assert payload['project_id'] == project_id


def test_create_project_rule_plugin_policy_body_is_stored_as_provided(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post(
        '/api/project-rules',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Plugin Policy',
            'body': '{"required_checks":{"delivery":["git_contract_ok"]},"runtime_deploy_health":{"required":false}}',
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload['title'] == 'Plugin Policy'
    assert payload['body'] == '{"required_checks":{"delivery":["git_contract_ok"]},"runtime_deploy_health":{"required":false}}'


def test_create_project_rule_plugin_policy_allows_arbitrary_json_shape(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    created = client.post(
        '/api/project-rules',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Plugin Policy',
            'body': '{"required_checks":["invalid"],"runtime_deploy_health":{"required":false}}',
        },
    )
    assert created.status_code == 200
    assert created.json()['body'] == '{"required_checks":["invalid"],"runtime_deploy_health":{"required":false}}'


def test_create_project_rule_plugin_policy_creates_distinct_rules_without_upsert(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    first = client.post(
        '/api/project-rules',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Plugin Policy',
            'body': '{"runtime_deploy_health":{"required":false}}',
        },
    )
    assert first.status_code == 200
    first_payload = first.json()

    second = client.post(
        '/api/project-rules',
        json={
            'workspace_id': ws_id,
            'project_id': project_id,
            'title': 'Plugin Policy',
            'body': '{"runtime_deploy_health":{"required":true,"port":6768}}',
        },
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload['id'] != first_payload['id']
    assert second_payload['body'] == '{"runtime_deploy_health":{"required":true,"port":6768}}'

    listed = client.get(f'/api/project-rules?workspace_id={ws_id}&project_id={project_id}')
    assert listed.status_code == 200
    plugin_rules = [
        row for row in listed.json().get('items', [])
        if str(row.get('title', '')).strip().lower() == 'plugin policy'
    ]
    assert len(plugin_rules) == 2


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


def test_project_plugin_config_endpoints_validate_and_apply(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    project_id = bootstrap['projects'][0]['id']

    get_team_mode = client.get(f'/api/projects/{project_id}/plugins/team_mode')
    assert get_team_mode.status_code == 200
    team_mode_payload = get_team_mode.json()
    assert team_mode_payload['plugin_key'] == 'team_mode'
    assert team_mode_payload['enabled'] is False
    assert team_mode_payload['version'] == 0
    assert isinstance(team_mode_payload['config'], dict)

    invalid_validation = client.post(
        f'/api/projects/{project_id}/plugins/team_mode/validate',
        json={'draft_config': {}},
    )
    assert invalid_validation.status_code == 200
    invalid_validation_payload = invalid_validation.json()
    assert invalid_validation_payload['plugin_key'] == 'team_mode'
    assert invalid_validation_payload['blocking'] is True
    error_paths = {str(item.get('path') or '').strip() for item in invalid_validation_payload.get('errors', [])}
    assert 'workflow.statuses' in error_paths or 'workflow' in error_paths

    apply_git_delivery = client.post(
        f'/api/projects/{project_id}/plugins/git_delivery/apply',
        json={
            'config': {
                'required_checks': {
                    'delivery': ['git_contract_ok'],
                },
            },
            'enabled': True,
        },
    )
    assert apply_git_delivery.status_code == 200
    apply_git_delivery_payload = apply_git_delivery.json()
    assert apply_git_delivery_payload['plugin_key'] == 'git_delivery'
    assert apply_git_delivery_payload['enabled'] is True
    assert apply_git_delivery_payload['version'] >= 1
    assert apply_git_delivery_payload['compiled_policy']['required_checks']['delivery'] == ['git_contract_ok']

    apply_docker_compose = client.post(
        f'/api/projects/{project_id}/plugins/docker_compose/apply',
        json={
            'config': {
                'runtime_deploy_health': {
                    'required': True,
                    'stack': 'constructos-app',
                    'port': 8080,
                    'health_path': '/health',
                },
            },
            'enabled': True,
        },
    )
    assert apply_docker_compose.status_code == 200
    apply_docker_payload = apply_docker_compose.json()
    assert apply_docker_payload['plugin_key'] == 'docker_compose'
    assert apply_docker_payload['enabled'] is True
    assert apply_docker_payload['version'] >= 1
    assert apply_docker_payload['compiled_policy']['runtime_deploy_health']['stack'] == 'constructos-app'

    disable_git_delivery = client.post(
        f'/api/projects/{project_id}/plugins/git_delivery/enabled',
        json={'enabled': False},
    )
    assert disable_git_delivery.status_code == 200
    assert disable_git_delivery.json()['enabled'] is False


def test_project_plugin_config_get_recomputes_compiled_policy_when_stored_snapshot_is_stale(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']

    apply_git_delivery = client.post(
        f'/api/projects/{project_id}/plugins/git_delivery/apply',
        json={
            'config': {
                'required_checks': {
                    'delivery': ['repo_context_present'],
                },
            },
            'enabled': True,
        },
    )
    assert apply_git_delivery.status_code == 200

    from shared.models import ProjectPluginConfig, SessionLocal

    with SessionLocal() as db:
        row = db.execute(
            select(ProjectPluginConfig).where(
                ProjectPluginConfig.workspace_id == ws_id,
                ProjectPluginConfig.project_id == project_id,
                ProjectPluginConfig.plugin_key == 'git_delivery',
                ProjectPluginConfig.is_deleted == False,  # noqa: E712
            )
        ).scalar_one()
        row.compiled_policy_json = json.dumps(
            {
                'version': 1,
                'required_checks': {'delivery': ['repo_context_present']},
                'available_checks': {'delivery': {'repo_context_present': 'x'}},
                'runtime_deploy_health': {'required': True, 'stack': 'legacy'},
            }
        )
        db.add(row)
        db.commit()

    get_git_delivery = client.get(f'/api/projects/{project_id}/plugins/git_delivery')
    assert get_git_delivery.status_code == 200
    payload = get_git_delivery.json()
    compiled = payload['compiled_policy']
    assert compiled['required_checks']['delivery'] == ['repo_context_present']
    assert 'runtime_deploy_health' not in compiled


def test_project_plugin_config_get_fills_defaults_when_config_is_empty_object(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    project_id = bootstrap['projects'][0]['id']
    actor_id = bootstrap['current_user']['id']

    from shared.models import ProjectPluginConfig, SessionLocal

    with SessionLocal() as db:
        row = db.execute(
            select(ProjectPluginConfig).where(
                ProjectPluginConfig.workspace_id == ws_id,
                ProjectPluginConfig.project_id == project_id,
                ProjectPluginConfig.plugin_key == 'team_mode',
                ProjectPluginConfig.is_deleted == False,  # noqa: E712
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProjectPluginConfig(
                workspace_id=ws_id,
                project_id=project_id,
                plugin_key='team_mode',
                enabled=True,
                version=1,
                schema_version=1,
                config_json='{}',
                compiled_policy_json='{}',
                last_validation_errors_json='[]',
                created_by=actor_id,
                updated_by=actor_id,
            )
        else:
            row.enabled = True
            row.config_json = '{}'
            row.compiled_policy_json = '{}'
        db.add(row)
        db.commit()

    get_team_mode = client.get(f'/api/projects/{project_id}/plugins/team_mode')
    assert get_team_mode.status_code == 200
    payload = get_team_mode.json()
    assert payload['plugin_key'] == 'team_mode'
    assert payload['enabled'] is True
    team = payload['config'].get('team') if isinstance(payload.get('config'), dict) else None
    assert isinstance(team, dict)
    agents = team.get('agents')
    assert isinstance(agents, list)
    assert len(agents) == 4


def test_project_git_delivery_repository_endpoints_return_branch_tree_and_file_preview(tmp_path):
    import subprocess

    from shared.project_repository import ensure_project_repository_initialized

    os.environ["AGENT_CODEX_WORKDIR"] = str(tmp_path)
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    created = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Repository Inspector'})
    assert created.status_code == 200
    project = created.json()
    project_id = project['id']
    project_name = project['name']

    repo_root = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    (repo_root / 'src').mkdir(parents=True, exist_ok=True)
    (repo_root / 'README.md').write_text('# Repository Inspector\n', encoding='utf-8')
    (repo_root / 'src' / 'app.ts').write_text('export const enabled = true\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'README.md', 'src/app.ts'], cwd=str(repo_root), check=True, capture_output=True, text=True)
    subprocess.run(['git', 'commit', '-m', 'Add repository inspector fixtures'], cwd=str(repo_root), check=True, capture_output=True, text=True)
    subprocess.run(['git', 'checkout', '-b', 'task/demo-branch'], cwd=str(repo_root), check=True, capture_output=True, text=True)
    (repo_root / 'notes.txt').write_text('branch notes\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'notes.txt'], cwd=str(repo_root), check=True, capture_output=True, text=True)
    subprocess.run(['git', 'commit', '-m', 'Add branch notes'], cwd=str(repo_root), check=True, capture_output=True, text=True)
    subprocess.run(['git', 'checkout', 'main'], cwd=str(repo_root), check=True, capture_output=True, text=True)

    summary = client.get(f'/api/projects/{project_id}/git-delivery/repository')
    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload['available'] is True
    assert summary_payload['branch_count'] >= 2
    assert summary_payload['default_branch'] == 'main'

    branches = client.get(f'/api/projects/{project_id}/git-delivery/repository/branches')
    assert branches.status_code == 200
    branch_rows = branches.json()['branches']
    branch_names = {row['name'] for row in branch_rows}
    assert 'main' in branch_names
    assert 'task/demo-branch' in branch_names

    tree_root = client.get(f'/api/projects/{project_id}/git-delivery/repository/tree', params={'ref': 'main'})
    assert tree_root.status_code == 200
    root_entries = tree_root.json()['entries']
    assert any(entry['path'] == 'README.md' and entry['kind'] == 'file' for entry in root_entries)
    assert any(entry['path'] == 'src' and entry['kind'] == 'directory' for entry in root_entries)

    tree_src = client.get(f'/api/projects/{project_id}/git-delivery/repository/tree', params={'ref': 'main', 'path': 'src'})
    assert tree_src.status_code == 200
    assert any(entry['path'] == 'src/app.ts' for entry in tree_src.json()['entries'])

    file_preview = client.get(
        f'/api/projects/{project_id}/git-delivery/repository/file',
        params={'ref': 'main', 'path': 'src/app.ts'},
    )
    assert file_preview.status_code == 200
    file_payload = file_preview.json()
    assert file_payload['previewable'] is True
    assert file_payload['binary'] is False
    assert 'export const enabled = true' in file_payload['content']


def test_project_git_delivery_repository_diff_endpoint_returns_branch_patch(tmp_path):
    import subprocess

    from shared.project_repository import ensure_project_repository_initialized

    os.environ["AGENT_CODEX_WORKDIR"] = str(tmp_path)
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    ws_id = bootstrap['workspaces'][0]['id']
    created = client.post('/api/projects', json={'workspace_id': ws_id, 'name': 'Repository Diff Inspector'})
    assert created.status_code == 200
    project = created.json()
    project_id = project['id']
    project_name = project['name']

    repo_root = ensure_project_repository_initialized(project_name=project_name, project_id=project_id)
    (repo_root / 'src').mkdir(parents=True, exist_ok=True)
    (repo_root / 'README.md').write_text('# Repository Diff Inspector\n', encoding='utf-8')
    (repo_root / 'src' / 'app.ts').write_text('export const enabled = true\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'README.md', 'src/app.ts'], cwd=str(repo_root), check=True, capture_output=True, text=True)
    subprocess.run(['git', 'commit', '-m', 'Add baseline files'], cwd=str(repo_root), check=True, capture_output=True, text=True)

    subprocess.run(['git', 'checkout', '-b', 'task/demo-diff'], cwd=str(repo_root), check=True, capture_output=True, text=True)
    (repo_root / 'src' / 'app.ts').write_text('export const enabled = true\nexport const review = "required"\n', encoding='utf-8')
    (repo_root / 'notes.txt').write_text('branch notes\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'src/app.ts', 'notes.txt'], cwd=str(repo_root), check=True, capture_output=True, text=True)
    subprocess.run(['git', 'commit', '-m', 'Add review changes'], cwd=str(repo_root), check=True, capture_output=True, text=True)
    subprocess.run(['git', 'checkout', 'main'], cwd=str(repo_root), check=True, capture_output=True, text=True)

    response = client.get(
        f'/api/projects/{project_id}/git-delivery/repository/diff',
        params={'base_ref': 'main', 'head_ref': 'task/demo-diff'},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload['base_ref'] == 'main'
    assert payload['head_ref'] == 'task/demo-diff'
    assert payload['compare_mode'] == 'merge_base'
    assert payload['files_changed'] == 2
    assert payload['insertions'] == 2
    assert payload['deletions'] == 0
    assert payload['patch_truncated'] is False
    assert 'diff --git a/notes.txt b/notes.txt' in payload['patch']
    assert 'diff --git a/src/app.ts b/src/app.ts' in payload['patch']

    files = payload['files']
    assert any(item['path'] == 'notes.txt' and item['status'] == 'added' and item['additions'] == 1 for item in files)
    assert any(
        item['path'] == 'src/app.ts' and item['status'] == 'modified' and item['additions'] == 1 and item['deletions'] == 0
        for item in files
    )
