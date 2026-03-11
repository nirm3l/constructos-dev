import json
import os
from importlib import reload
from pathlib import Path

from fastapi.testclient import TestClient


def build_client(tmp_path: Path, monkeypatch) -> TestClient:
    db_file = tmp_path / "test.db"
    home_dir = tmp_path / "home"
    codex_home_root = tmp_path / "codex-home"
    home_dir.mkdir(parents=True, exist_ok=True)
    codex_home_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AGENT_RUNNER_ENABLED", "false")
    monkeypatch.setenv("AGENT_CODEX_HOME_ROOT", str(codex_home_root))
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.setenv("EVENTSTORE_URI", "")
    import main

    main = reload(main)
    main.bootstrap_data()
    client = TestClient(main.app)
    login = client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'})
    assert login.status_code == 200
    return client


def _write_auth_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"auth_mode": "chatgpt", "access_token": "test-token"}, ensure_ascii=True),
        encoding="utf-8",
    )


def _create_member_session(client: TestClient, *, workspace_id: str) -> None:
    created = client.post(
        '/api/admin/users',
        json={
            'workspace_id': workspace_id,
            'username': 'member1',
            'full_name': 'Member One',
            'role': 'Member',
        },
    )
    assert created.status_code == 200
    temp_password = created.json()["temporary_password"]
    logout = client.post('/api/auth/logout')
    assert logout.status_code == 200
    login = client.post('/api/auth/login', json={'username': 'member1', 'password': temp_password})
    assert login.status_code == 200
    change_password = client.post(
        '/api/auth/change-password',
        json={'current_password': temp_password, 'new_password': 'MemberPassword123'},
    )
    assert change_password.status_code == 200


def test_codex_auth_status_reports_none_without_host_or_override(tmp_path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)

    response = client.get('/api/agents/codex-auth')

    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is False
    assert payload["effective_source"] == "none"
    assert payload["host_auth_available"] is False
    assert payload["override_available"] is False
    assert payload["scope"] == "system"
    assert payload["target_actor_username"] == "codex-bot"


def test_codex_auth_status_prefers_system_override_and_delete_falls_back_to_host(tmp_path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)

    import features.agents.codex_auth as codex_auth

    host_auth_path = Path(os.environ["HOME"]) / ".codex" / "auth.json"
    override_auth_path = codex_auth.resolve_system_override_auth_path()
    _write_auth_file(host_auth_path)
    _write_auth_file(override_auth_path)

    before_delete = client.get('/api/agents/codex-auth')
    assert before_delete.status_code == 200
    assert before_delete.json()["effective_source"] == "system_override"
    assert before_delete.json()["host_auth_available"] is True
    assert before_delete.json()["override_available"] is True

    deleted = client.delete('/api/agents/codex-auth/override')
    assert deleted.status_code == 200
    payload = deleted.json()
    assert payload["effective_source"] == "host_mount"
    assert payload["host_auth_available"] is True
    assert payload["override_available"] is False


def test_codex_auth_device_start_endpoint_returns_manager_status(tmp_path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)
    import features.agents.api as agents_api

    monkeypatch.setattr(
        agents_api,
        "start_device_auth_session",
        lambda _requested_by_user_id=None: {
            "configured": False,
            "effective_source": "none",
            "host_auth_available": False,
            "override_available": False,
            "override_updated_at": None,
            "scope": "system",
            "target_actor_user_id": "00000000-0000-0000-0000-000000000099",
            "target_actor_username": "codex-bot",
            "login_session": {
                "id": "session-1",
                "status": "pending",
                "started_at": "2026-03-11T10:00:00Z",
                "updated_at": "2026-03-11T10:00:00Z",
                "verification_uri": "https://auth.openai.com/codex/device",
                "user_code": "ABCD-EFGH",
                "error": None,
                "output_excerpt": [],
            },
        },
    )

    response = client.post('/api/agents/codex-auth/device/start')

    assert response.status_code == 200
    payload = response.json()
    assert payload["login_session"]["status"] == "pending"
    assert payload["login_session"]["verification_uri"] == "https://auth.openai.com/codex/device"
    assert payload["login_session"]["user_code"] == "ABCD-EFGH"
    assert payload["target_actor_username"] == "codex-bot"


def test_codex_auth_device_start_requires_admin_role(tmp_path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)
    bootstrap = client.get('/api/bootstrap').json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    _create_member_session(client, workspace_id=workspace_id)

    response = client.post('/api/agents/codex-auth/device/start')

    assert response.status_code == 403
    assert "owners and admins" in response.json()["detail"]


def test_agents_chat_returns_guidance_when_codex_auth_missing(tmp_path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)
    bootstrap = client.get('/api/bootstrap').json()
    workspace_id = bootstrap["workspaces"][0]["id"]

    import features.agents.api as agents_api

    def _unexpected_execute(**kwargs):
        raise AssertionError("execute_task_automation should not run without Codex authentication")

    monkeypatch.setattr(agents_api, "execute_task_automation", _unexpected_execute)

    response = client.post(
        '/api/agents/chat',
        json={
            "workspace_id": workspace_id,
            "instruction": "Help me plan the next release.",
            "history": [],
            "attachment_refs": [],
            "session_attachment_refs": [],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["summary"] == "Codex authentication is not configured."
    assert "ask a workspace admin" in payload["comment"]


def test_agents_chat_stream_returns_guidance_when_codex_auth_missing(tmp_path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)
    bootstrap = client.get('/api/bootstrap').json()
    workspace_id = bootstrap["workspaces"][0]["id"]

    import features.agents.api as agents_api

    def _unexpected_stream_execute(**kwargs):
        raise AssertionError("execute_task_automation_stream should not run without Codex authentication")

    monkeypatch.setattr(agents_api, "execute_task_automation_stream", _unexpected_stream_execute)

    response = client.post(
        '/api/agents/chat/stream',
        json={
            "workspace_id": workspace_id,
            "instruction": "Help me plan the next release.",
            "history": [],
            "attachment_refs": [],
            "session_attachment_refs": [],
        },
    )

    assert response.status_code == 200
    body = response.text.strip().splitlines()
    assert len(body) == 1
    event = json.loads(body[0])
    assert event["type"] == "final"
    assert event["response"]["ok"] is False
    assert event["response"]["summary"] == "Codex authentication is not configured."
