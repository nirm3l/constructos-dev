import json
import os
from importlib import reload
from pathlib import Path
from types import SimpleNamespace

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
        json.dumps({"oauthAccount": {"accessToken": "test-token"}}, ensure_ascii=True),
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
                "verification_uri": "https://auth.openai.com/device",
                "user_code": None,
                "error": None,
                "output_excerpt": [],
            },
        },
    )

    response = client.post('/api/agents/codex-auth/device/start')

    assert response.status_code == 200
    payload = response.json()
    assert payload["login_session"]["status"] == "pending"
    assert payload["login_session"]["verification_uri"] == "https://auth.openai.com/device"
    assert payload["login_session"]["user_code"] is None
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


def test_claude_auth_status_reports_none_without_host_or_override(tmp_path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)

    response = client.get('/api/agents/claude-auth')

    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is False
    assert payload["effective_source"] == "none"
    assert payload["target_actor_username"] == "claude-bot"
    assert payload["selected_login_method"] is None
    assert payload["supported_login_methods"] == ["claudeai", "console"]


def test_claude_auth_status_requires_logged_in_cli_state(tmp_path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)

    import features.agents.provider_auth as provider_auth

    override_auth_path = provider_auth.resolve_provider_system_override_auth_path("claude")
    _write_auth_file(override_auth_path)

    monkeypatch.setattr(
        provider_auth,
        "_read_claude_auth_status",
        lambda _home_path: {"loggedIn": False, "authMethod": "none"},
    )

    response = client.get('/api/agents/claude-auth')

    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is False
    assert payload["effective_source"] == "none"
    assert payload["override_available"] is False


def test_claude_auth_device_start_accepts_login_method(tmp_path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)
    import features.agents.api as agents_api

    captured: dict[str, object] = {}

    def _fake_start(_requested_by_user_id=None, *, login_method=None):
        captured["requested_by_user_id"] = _requested_by_user_id
        captured["login_method"] = login_method
        return {
            "configured": False,
            "effective_source": "none",
            "host_auth_available": False,
            "override_available": False,
            "override_updated_at": None,
            "scope": "system",
            "target_actor_user_id": "00000000-0000-0000-0000-000000000098",
            "target_actor_username": "claude-bot",
            "selected_login_method": login_method,
            "supported_login_methods": ["claudeai", "console"],
            "login_session": {
                "id": "session-claude-1",
                "status": "pending",
                "started_at": "2026-03-12T10:00:00Z",
                "updated_at": "2026-03-12T10:00:00Z",
                "login_method": login_method,
                "verification_uri": "https://console.anthropic.com",
                "user_code": None,
                "error": None,
                "output_excerpt": [],
            },
        }

    monkeypatch.setattr(agents_api, "start_claude_device_auth_session", _fake_start)

    response = client.post('/api/agents/claude-auth/device/start', json={"login_method": "console"})

    assert response.status_code == 200
    payload = response.json()
    assert captured["login_method"] == "console"
    assert payload["login_session"]["login_method"] == "console"
    assert payload["selected_login_method"] == "console"


def test_claude_auth_status_prefers_pending_session_login_method(tmp_path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)

    import features.agents.provider_auth as provider_auth

    home_path = provider_auth.ensure_provider_system_override_home("claude")
    (home_path / ".claude").mkdir(parents=True, exist_ok=True)
    (home_path / ".claude" / "settings.json").write_text('{"forceLoginMethod":"claudeai"}\n', encoding="utf-8")
    provider_auth._DEVICE_AUTH_SESSIONS["claude"] = provider_auth.DeviceAuthSessionState(
        session_id="session-pending",
        status="pending",
        started_at="2026-03-12T14:00:00Z",
        updated_at="2026-03-12T14:00:01Z",
        login_method="console",
    )

    response = client.get('/api/agents/claude-auth')

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_login_method"] == "console"


def test_claude_interactive_login_uses_full_login_command(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import features.agents.provider_auth as provider_auth

    captured: dict[str, object] = {}

    class _DummyProcess:
        pid = 123

        def poll(self):
            return None

    def _fake_openpty():
        return 101, 102

    def _fake_popen(args, **kwargs):
        captured["args"] = list(args)
        return _DummyProcess()

    monkeypatch.setattr(provider_auth.pty, "openpty", _fake_openpty)
    monkeypatch.setattr(provider_auth.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(provider_auth.os, "close", lambda _fd: None)

    process, master_fd = provider_auth._launch_provider_device_auth_process(
        provider_auth._provider_spec("claude"),
        home_path=tmp_path,
    )

    assert isinstance(process, _DummyProcess)
    assert master_fd == 101
    assert captured["args"] == ["claude"]


def test_claude_interactive_auth_sends_theme_login_and_console_choice(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import features.agents.provider_auth as provider_auth

    writes: list[bytes] = []
    session = provider_auth.DeviceAuthSessionState(
        session_id="session-1",
        status="pending",
        started_at="2026-03-12T13:00:00Z",
        updated_at="2026-03-12T13:00:00Z",
        login_method="console",
    )
    monkeypatch.setitem(provider_auth._DEVICE_AUTH_SESSIONS, "claude", session)
    monkeypatch.setattr(provider_auth.os, "write", lambda _fd, data: writes.append(data))
    monkeypatch.setattr(
        provider_auth,
        "_schedule_interactive_auth_write",
        lambda **kwargs: writes.append(kwargs["data"]),
    )

    provider_auth._handle_interactive_device_auth_output(
        provider="claude",
        session_id="session-1",
        chunk_text="Choose the text style that looks best with your terminal",
        master_fd=77,
    )
    provider_auth._handle_interactive_device_auth_output(
        provider="claude",
        session_id="session-1",
        chunk_text="Syntax highlighting available only in native build",
        master_fd=77,
    )
    provider_auth._handle_interactive_device_auth_output(
        provider="claude",
        session_id="session-1",
        chunk_text="Select login method:",
        master_fd=77,
    )

    assert writes == [b"\r", b"/login\r", b"\x1b[B\r", b"\x1b[B\r\n"]


def test_claude_interactive_auth_matches_tui_output_with_control_chars(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import features.agents.provider_auth as provider_auth

    writes: list[bytes] = []
    session = provider_auth.DeviceAuthSessionState(
        session_id="session-2",
        status="pending",
        started_at="2026-03-12T13:00:00Z",
        updated_at="2026-03-12T13:00:00Z",
        login_method="console",
    )
    monkeypatch.setitem(provider_auth._DEVICE_AUTH_SESSIONS, "claude", session)
    monkeypatch.setattr(provider_auth.os, "write", lambda _fd, data: writes.append(data))
    monkeypatch.setattr(
        provider_auth,
        "_schedule_interactive_auth_write",
        lambda **kwargs: writes.append(kwargs["data"]),
    )

    provider_auth._handle_interactive_device_auth_output(
        provider="claude",
        session_id="session-2",
        chunk_text="\x1b[1CLet's\x1cget\x1cstarted.\n\x1b[1CChoose\x1cthe\x1ctext\x1cstyle",
        master_fd=77,
    )
    provider_auth._handle_interactive_device_auth_output(
        provider="claude",
        session_id="session-2",
        chunk_text="\x1b[1C Syntax\x1chighlighting\x1cavailable\x1conly\x1cin\x1cnative\x1cbuild",
        master_fd=77,
    )
    provider_auth._handle_interactive_device_auth_output(
        provider="claude",
        session_id="session-2",
        chunk_text="\x1b[1CSelect\x1clogin\x1cmethod:",
        master_fd=77,
    )

    assert writes == [b"\r", b"/login\r", b"\x1b[B\r", b"\x1b[B\r\n"]


def test_claude_interactive_auth_matches_compacted_tui_output(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import features.agents.provider_auth as provider_auth

    writes: list[bytes] = []
    session = provider_auth.DeviceAuthSessionState(
        session_id="session-3",
        status="pending",
        started_at="2026-03-12T13:00:00Z",
        updated_at="2026-03-12T13:00:00Z",
        login_method="console",
    )
    monkeypatch.setitem(provider_auth._DEVICE_AUTH_SESSIONS, "claude", session)
    monkeypatch.setattr(provider_auth.os, "write", lambda _fd, data: writes.append(data))
    monkeypatch.setattr(
        provider_auth,
        "_schedule_interactive_auth_write",
        lambda **kwargs: writes.append(kwargs["data"]),
    )

    provider_auth._handle_interactive_device_auth_output(
        provider="claude",
        session_id="session-3",
        chunk_text="Choosethetextstylethatlooksbestwithyourterminal",
        master_fd=77,
    )
    provider_auth._handle_interactive_device_auth_output(
        provider="claude",
        session_id="session-3",
        chunk_text="Syntaxhighlightingavailableonlyinnativebuild",
        master_fd=77,
    )
    provider_auth._handle_interactive_device_auth_output(
        provider="claude",
        session_id="session-3",
        chunk_text="Selectloginmethod:",
        master_fd=77,
    )

    assert writes == [b"\r", b"/login\r", b"\x1b[B\r", b"\x1b[B\r\n"]


def test_claude_interactive_auth_confirms_completion_prompt(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import features.agents.provider_auth as provider_auth

    writes: list[bytes] = []
    session = provider_auth.DeviceAuthSessionState(
        session_id="session-4",
        status="pending",
        started_at="2026-03-12T13:00:00Z",
        updated_at="2026-03-12T13:00:00Z",
        login_method="console",
    )
    monkeypatch.setitem(provider_auth._DEVICE_AUTH_SESSIONS, "claude", session)
    monkeypatch.setattr(provider_auth.os, "write", lambda _fd, data: writes.append(data))

    provider_auth._handle_interactive_device_auth_output(
        provider="claude",
        session_id="session-4",
        chunk_text="Loginsuccessful.PressEntertocontinue…",
        master_fd=77,
    )

    assert writes == [b"\r"]


def test_claude_interactive_auth_confirms_trusted_folder_prompt(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import features.agents.provider_auth as provider_auth

    writes: list[bytes] = []
    session = provider_auth.DeviceAuthSessionState(
        session_id="session-5",
        status="pending",
        started_at="2026-03-12T13:00:00Z",
        updated_at="2026-03-12T13:00:00Z",
        login_method="console",
    )
    monkeypatch.setitem(provider_auth._DEVICE_AUTH_SESSIONS, "claude", session)
    monkeypatch.setattr(provider_auth.os, "write", lambda _fd, data: writes.append(data))

    provider_auth._handle_interactive_device_auth_output(
        provider="claude",
        session_id="session-5",
        chunk_text="❯1.Yes,Itrustthisfolder\nEntertoconfirm·Esctocancel",
        master_fd=77,
    )

    assert writes == [b"\r"]


def test_claude_auth_reconstructs_wrapped_verification_uri():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import features.agents.provider_auth as provider_auth

    session = provider_auth.DeviceAuthSessionState(
        session_id="session-url",
        status="pending",
        started_at="2026-03-12T14:00:00Z",
        updated_at="2026-03-12T14:00:01Z",
        login_method="console",
    )

    provider_auth._append_output_line(
        session,
        "https://platform.claude.com/oauth/authorize?code=true&client_id=9d1c250a-e61b-44",
    )
    provider_auth._append_output_line(
        session,
        "d9-88ed-5944d1962f5e&response_type=code&redirect_uri=https%3A%2F%2Fplatform.clau",
    )
    provider_auth._append_output_line(
        session,
        "de.com%2Foauth%2Fcode%2Fcallback&scope=org%3Acreate_api_key+user%3Aprofile",
    )
    provider_auth._append_output_line(
        session,
        "Loginmethodpre-selected:APIUsageBilling(AnthropicConsole)",
    )

    assert session.verification_uri is not None
    assert session.verification_uri.startswith("https://platform.claude.com/oauth/authorize?")
    assert "redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback" in session.verification_uri
    assert "Loginmethodpre-selected" not in session.verification_uri


def test_claude_auth_preserves_oauth_url_after_security_docs_output():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import features.agents.provider_auth as provider_auth

    session = provider_auth.DeviceAuthSessionState(
        session_id="session-url-2",
        status="pending",
        started_at="2026-03-12T14:00:00Z",
        updated_at="2026-03-12T14:00:01Z",
        login_method="console",
        verification_uri="https://platform.claude.com/oauth/authorize?code=true&state=abc123",
    )

    provider_auth._append_output_line(session, "Formoredetailssee:")
    provider_auth._append_output_line(session, "https://code.claude.com/docs/en/security")

    assert session.verification_uri == "https://platform.claude.com/oauth/authorize?code=true&state=abc123"


def test_claude_auth_submit_code_writes_to_live_session(monkeypatch):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import features.agents.provider_auth as provider_auth

    writes: list[bytes] = []
    session = provider_auth.DeviceAuthSessionState(
        session_id="session-submit",
        status="pending",
        started_at="2026-03-12T14:00:00Z",
        updated_at="2026-03-12T14:00:01Z",
        login_method="console",
        pty_master_fd=77,
    )
    session.process = SimpleNamespace(poll=lambda: None)
    monkeypatch.setitem(provider_auth._DEVICE_AUTH_SESSIONS, "claude", session)
    monkeypatch.setattr(provider_auth.os, "write", lambda _fd, data: writes.append(data))

    provider_auth.submit_provider_device_auth_code("claude", "abc-123")

    assert writes == [b"abc-123\r"]


def test_agents_chat_returns_claude_guidance_when_selected_provider_auth_missing(tmp_path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)
    bootstrap = client.get('/api/bootstrap').json()
    workspace_id = bootstrap["workspaces"][0]["id"]

    import features.agents.api as agents_api

    def _unexpected_execute(**kwargs):
        raise AssertionError("execute_task_automation should not run without Claude authentication")

    monkeypatch.setattr(agents_api, "execute_task_automation", _unexpected_execute)

    response = client.post(
        '/api/agents/chat',
        json={
          "workspace_id": workspace_id,
          "instruction": "Help me plan the next release.",
          "history": [],
          "attachment_refs": [],
          "session_attachment_refs": [],
          "model": "claude:sonnet",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["summary"] == "Claude authentication is not configured."
