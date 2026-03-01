from __future__ import annotations

import io
import json
import os
import time
import uuid
from importlib import reload
from pathlib import Path

from shared.models import ProjectMember, SessionLocal, User as UserModel


def build_client(tmp_path: Path):
    import os

    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    import main

    main = reload(main)
    main.bootstrap_data()
    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert login.status_code == 200
    return client


def test_execute_task_automation_includes_project_description_in_context(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project = client.post(
        "/api/projects",
        json={"workspace_id": ws_id, "name": "Agent Context", "description": "# Project soul\nAlways include tests."},
    ).json()
    created_rule = client.post(
        "/api/project-rules",
        json={
            "workspace_id": ws_id,
            "project_id": project["id"],
            "title": "Definition of done",
            "body": "Always add or update tests.",
        },
    )
    assert created_rule.status_code == 200

    from features.agents import executor as executor_module

    monkeypatch.setattr(executor_module, "AGENT_EXECUTOR_MODE", "command")
    monkeypatch.setattr(executor_module, "AGENT_CODEX_COMMAND", "dummy-exec")

    captured: dict = {}

    class DummyProcess:
        returncode = 0
        stdout = '{"action":"comment","summary":"ok","comment":null}'
        stderr = ""

    def fake_run(command, *, input, text, capture_output, timeout, check, cwd=None):  # noqa: A002
        _ = (command, text, capture_output, timeout, check)
        _ = cwd
        captured.update(json.loads(input))
        return DummyProcess()

    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    outcome = executor_module.execute_task_automation(
        task_id="",
        title="General Codex Chat",
        description="chat",
        status="To do",
        instruction="Summarize project goals",
        workspace_id=ws_id,
        project_id=project["id"],
        actor_user_id=bootstrap["current_user"]["id"],
        allow_mutations=True,
    )

    assert outcome.summary == "ok"
    assert captured["project_id"] == project["id"]
    assert captured["project_name"] == "Agent Context"
    assert captured["project_description"] == "# Project soul\nAlways include tests."
    assert captured["project_rules"][0]["title"] == "Definition of done"
    assert captured["project_rules"][0]["body"] == "Always add or update tests."
    assert captured["actor_user_id"] == bootstrap["current_user"]["id"]
    assert captured["actor_project_role"] == "Owner"
    assert isinstance(captured["graph_context_markdown"], str)
    assert captured["graph_context_markdown"]


def test_execute_task_automation_includes_project_skills_in_context(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project = client.post(
        "/api/projects",
        json={"workspace_id": ws_id, "name": "Agent Skill Context"},
    ).json()
    actor_user_id = bootstrap["current_user"]["id"]

    from shared.models import ProjectSkill, SessionLocal

    with SessionLocal() as db:
        db.add(
            ProjectSkill(
                id=str(uuid.uuid4()),
                workspace_id=ws_id,
                project_id=project["id"],
                skill_key="release_quality",
                name="Release Quality Skill",
                summary="Require release notes and tests.",
                source_type="url",
                source_locator="https://example.com/skills/release-quality.md",
                source_version="1.0.0",
                trust_level="verified",
                mode="enforced",
                generated_rule_id=None,
                manifest_json="{}",
                created_by=actor_user_id,
                updated_by=actor_user_id,
                is_deleted=False,
            )
        )
        db.commit()

    from features.agents import executor as executor_module

    monkeypatch.setattr(executor_module, "AGENT_EXECUTOR_MODE", "command")
    monkeypatch.setattr(executor_module, "AGENT_CODEX_COMMAND", "dummy-exec")

    captured: dict = {}

    class DummyProcess:
        returncode = 0
        stdout = '{"action":"comment","summary":"ok","comment":null}'
        stderr = ""

    def fake_run(command, *, input, text, capture_output, timeout, check, cwd=None):  # noqa: A002
        _ = (command, text, capture_output, timeout, check)
        _ = cwd
        captured.update(json.loads(input))
        return DummyProcess()

    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    outcome = executor_module.execute_task_automation(
        task_id="",
        title="General Codex Chat",
        description="chat",
        status="To do",
        instruction="Summarize project context",
        workspace_id=ws_id,
        project_id=project["id"],
        actor_user_id=actor_user_id,
        allow_mutations=True,
    )
    assert outcome.summary == "ok"
    assert len(captured["project_skills"]) == 1
    assert captured["project_skills"][0]["skill_key"] == "release_quality"
    assert captured["project_skills"][0]["mode"] == "enforced"
    assert captured["project_skills"][0]["trust_level"] == "verified"


def test_execute_task_automation_includes_chat_and_codex_session_ids(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    from features.agents import executor as executor_module

    monkeypatch.setattr(executor_module, "AGENT_EXECUTOR_MODE", "command")
    monkeypatch.setattr(executor_module, "AGENT_CODEX_COMMAND", "dummy-exec")

    captured: dict = {}

    class DummyProcess:
        returncode = 0
        stdout = '{"action":"comment","summary":"ok","comment":null}'
        stderr = ""

    def fake_run(command, *, input, text, capture_output, timeout, check, cwd=None):  # noqa: A002
        _ = (command, text, capture_output, timeout, check)
        _ = cwd
        captured.update(json.loads(input))
        return DummyProcess()

    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    outcome = executor_module.execute_task_automation(
        task_id="",
        title="General Codex Chat",
        description="chat",
        status="To do",
        instruction="Use continuation context",
        workspace_id=ws_id,
        project_id=project_id,
        chat_session_id="chat-session-001",
        codex_session_id="thread-001",
        actor_user_id=bootstrap["current_user"]["id"],
        allow_mutations=True,
    )

    assert outcome.summary == "ok"
    assert captured["chat_session_id"] == "chat-session-001"
    assert captured["codex_session_id"] == "thread-001"


def test_execute_task_automation_includes_team_mode_actor_role_in_context(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]
    actor_user_id = str(uuid.uuid4())

    with SessionLocal() as db:
        db.add(
            UserModel(
                id=actor_user_id,
                username="agent.qa.ctx",
                full_name="Quality Assurance Agent Context",
                user_type="agent",
                password_hash=None,
                must_change_password=False,
                password_changed_at=None,
                is_active=True,
                theme="dark",
                timezone="UTC",
                notifications_enabled=True,
                agent_chat_model="",
                agent_chat_reasoning_effort="medium",
            )
        )
        db.add(
            ProjectMember(
                workspace_id=ws_id,
                project_id=project_id,
                user_id=actor_user_id,
                role="QAAgent",
            )
        )
        db.commit()

    from features.agents import executor as executor_module

    monkeypatch.setattr(executor_module, "AGENT_EXECUTOR_MODE", "command")
    monkeypatch.setattr(executor_module, "AGENT_CODEX_COMMAND", "dummy-exec")

    captured: dict = {}

    class DummyProcess:
        returncode = 0
        stdout = '{"action":"comment","summary":"ok","comment":null}'
        stderr = ""

    def fake_run(command, *, input, text, capture_output, timeout, check, cwd=None):  # noqa: A002
        _ = (command, text, capture_output, timeout, check, cwd)
        captured.update(json.loads(input))
        return DummyProcess()

    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    outcome = executor_module.execute_task_automation(
        task_id="task-ctx-role",
        title="Role context check",
        description="ctx",
        status="To do",
        instruction="Summarize role-specific policy",
        workspace_id=ws_id,
        project_id=project_id,
        actor_user_id=actor_user_id,
        allow_mutations=True,
    )
    assert outcome.summary == "ok"
    assert captured["actor_user_id"] == actor_user_id
    assert captured["actor_project_role"] == "QAAgent"


def test_codex_prompt_includes_soul_md_section():
    from features.agents.codex_mcp_adapter import _build_prompt

    prompt = _build_prompt(
        {
            "task_id": "",
            "title": "General Codex Chat",
            "description": "chat",
            "status": "To do",
            "instruction": "Plan this feature",
            "workspace_id": "ws-1",
            "project_id": "pr-1",
            "actor_user_id": "user-1",
            "actor_project_role": "DeveloperAgent",
            "project_name": "Alpha",
            "project_description": "## Soul\nUse strict acceptance criteria.",
            "project_rules": [{"title": "Quality", "body": "Do not skip tests."}],
            "graph_context_markdown": "## Graph\nTask A IMPLEMENTS Spec B",
        }
    )

    assert "Context Pack:" in prompt
    assert "File: Soul.md (source: project.description)" in prompt
    assert "## Soul\nUse strict acceptance criteria." in prompt
    assert "File: ProjectRules.md (source: project_rules)" in prompt
    assert "Quality: Do not skip tests." in prompt
    assert "Current User ID: user-1" in prompt
    assert "Current User Project Role: DeveloperAgent" in prompt
    assert "File: GraphContext.md (source: knowledge_graph)" in prompt
    assert "Task A IMPLEMENTS Spec B" in prompt
    assert "Read each MCP tool description and follow its payload contract and operational guidance." in prompt


def test_codex_resume_prompt_is_compact_and_turn_focused():
    from features.agents.codex_mcp_adapter import _build_prompt, _build_resume_prompt

    ctx = {
        "task_id": "",
        "title": "General Codex Chat",
        "description": "chat",
        "status": "To do",
        "instruction": "Plan this feature",
        "workspace_id": "ws-1",
        "project_id": "pr-1",
        "actor_user_id": "user-1",
        "actor_project_role": "TeamLeadAgent",
        "project_name": "Alpha",
        "project_description": "## Soul\nUse strict acceptance criteria.",
        "project_rules": [{"title": "Quality", "body": "Do not skip tests."}],
        "graph_context_markdown": "## Graph\nTask A IMPLEMENTS Spec B",
    }
    full_prompt = _build_prompt(ctx)
    resume_prompt = _build_resume_prompt(ctx)

    assert "Context Pack:" in full_prompt
    assert "This is a resumed Codex thread." in resume_prompt
    assert "Context Pack:" not in resume_prompt
    assert "File: Soul.md" not in resume_prompt
    assert "Instruction: Plan this feature" in resume_prompt
    assert "Current User Project Role: TeamLeadAgent" in resume_prompt
    assert "Fresh Cross-Session Memory Snapshot" in resume_prompt
    assert "If Team Mode is requested, you MUST execute this setup order" in resume_prompt
    assert "Read each MCP tool description and follow its payload contract and operational guidance." in resume_prompt
    assert len(resume_prompt) < len(full_prompt)


def test_codex_resume_prompt_includes_compact_fresh_evidence_snapshot():
    from features.agents.codex_mcp_adapter import _build_resume_prompt

    prompt = _build_resume_prompt(
        {
            "task_id": "",
            "title": "General Codex Chat",
            "description": "chat",
            "status": "To do",
            "instruction": "What is the secret number?",
            "workspace_id": "ws-1",
            "project_id": "pr-1",
            "actor_user_id": "user-1",
            "project_name": "Alpha",
            "graph_summary_markdown": "Recent project chat includes a declared secret number.",
            "graph_evidence_json": json.dumps(
                [
                    {
                        "evidence_id": "ev_001",
                        "entity_type": "ChatMessage",
                        "source_type": "chat_message.content",
                        "final_score": 0.992,
                        "snippet": "Tajni broj je 44",
                    }
                ]
            ),
        }
    )

    assert "Fresh Cross-Session Memory Snapshot" in prompt
    assert "Fresh Summary:" in prompt
    assert "Fresh Evidence:" in prompt
    assert "Tajni broj je 44" in prompt
    assert "score=0.992" in prompt


def test_codex_prompt_includes_project_skills_section():
    from features.agents.codex_mcp_adapter import _build_prompt

    prompt = _build_prompt(
        {
            "task_id": "",
            "title": "General Codex Chat",
            "description": "chat",
            "status": "To do",
            "instruction": "Summarize project constraints",
            "workspace_id": "ws-1",
            "project_id": "pr-1",
            "actor_user_id": "user-1",
            "project_name": "Alpha",
            "project_description": "",
            "project_rules": [],
            "project_skills": [
                {
                    "skill_key": "release_quality",
                    "name": "Release Quality Skill",
                    "summary": "Require release notes and tests.",
                    "mode": "enforced",
                    "trust_level": "verified",
                    "source_locator": "https://example.com/skills/release-quality.md",
                }
            ],
            "graph_context_markdown": "",
        }
    )

    assert "File: ProjectSkills.md (source: project_skills)" in prompt
    assert "Release Quality Skill (release_quality)" in prompt
    assert "mode=enforced" in prompt
    assert "trust=verified" in prompt


def test_codex_prompt_includes_interactive_project_creation_guidance():
    from features.agents.codex_mcp_adapter import _build_prompt

    prompt = _build_prompt(
        {
            "task_id": "",
            "title": "General Codex Chat",
            "description": "chat",
            "status": "To do",
            "instruction": "Help me create a new project",
            "workspace_id": "ws-1",
            "project_id": "",
            "project_name": "",
            "project_description": "",
            "project_rules": [],
            "graph_context_markdown": "",
        }
    )

    assert "Read each MCP tool description and follow its payload contract and operational guidance." in prompt
    assert "Dev -> QA -> Lead -> Done" in prompt
    assert "at least one recurring scheduled Team Lead oversight task" in prompt
    assert "If Team Mode is requested, you MUST execute this setup order" in prompt
    assert "If the user requests an exact task count, keep that exact count" in prompt


def test_mcp_tool_descriptions_include_operation_specific_guidance():
    import inspect
    from features.agents import mcp_server

    assert mcp_server.MCP_DEFAULT_PROJECT_EMBEDDING_ENABLED is True
    assert mcp_server.MCP_DEFAULT_PROJECT_CHAT_INDEX_MODE == "KG_AND_VECTOR"
    assert mcp_server.MCP_DEFAULT_PROJECT_CHAT_ATTACHMENT_INGESTION_MODE == "METADATA_ONLY"
    assert "status watchers" in mcp_server.TASK_CREATE_TOOL_DESCRIPTION
    assert "to_statuses" in mcp_server.TASK_UPDATE_TOOL_DESCRIPTION
    assert "toggle" in mcp_server.THEME_TOGGLE_TOOL_DESCRIPTION
    assert "current app user profile" in mcp_server.THEME_SET_TOOL_DESCRIPTION
    assert "Prefer this over per-task loops" in mcp_server.BULK_TASK_ACTION_TOOL_DESCRIPTION
    assert "archive all tasks" in mcp_server.ARCHIVE_ALL_TASKS_TOOL_DESCRIPTION.lower()
    assert "plans/specs/design docs" in mcp_server.CREATE_NOTE_TOOL_DESCRIPTION
    assert "manual/custom setup" in mcp_server.CREATE_PROJECT_TOOL_DESCRIPTION
    assert "chat default profile" in mcp_server.CREATE_PROJECT_TOOL_DESCRIPTION.lower()
    assert "chat default profile" in mcp_server.PREVIEW_PROJECT_FROM_TEMPLATE_TOOL_DESCRIPTION.lower()
    assert "chat default profile" in mcp_server.CREATE_PROJECT_FROM_TEMPLATE_TOOL_DESCRIPTION.lower()
    assert "preview_project_from_template" in mcp_server.CREATE_PROJECT_FROM_TEMPLATE_TOOL_DESCRIPTION
    source = inspect.getsource(mcp_server)
    assert "embedding_enabled: bool = MCP_DEFAULT_PROJECT_EMBEDDING_ENABLED" in source
    assert "chat_index_mode: str = MCP_DEFAULT_PROJECT_CHAT_INDEX_MODE" in source
    assert "chat_attachment_ingestion_mode: str = MCP_DEFAULT_PROJECT_CHAT_ATTACHMENT_INGESTION_MODE" in source
    assert "embedding_enabled: bool | None = MCP_DEFAULT_PROJECT_EMBEDDING_ENABLED" in source
    assert "chat_index_mode: str | None = MCP_DEFAULT_PROJECT_CHAT_INDEX_MODE" in source
    assert "chat_attachment_ingestion_mode: str | None = MCP_DEFAULT_PROJECT_CHAT_ATTACHMENT_INGESTION_MODE" in source


def test_codex_usage_extraction_from_json_stream():
    from features.agents.codex_mcp_adapter import _extract_turn_usage

    stream = "\n".join(
        [
            '{"type":"turn.started"}',
            '{"type":"turn.completed","usage":{"input_tokens":321,"cached_input_tokens":111,"output_tokens":45}}',
        ]
    )
    usage = _extract_turn_usage(stream)
    assert usage is not None
    assert usage["input_tokens"] == 321
    assert usage["cached_input_tokens"] == 111
    assert usage["output_tokens"] == 45


def test_executor_parses_usage_payload():
    from features.agents.executor import _parse_command_outcome

    outcome = _parse_command_outcome(
        '{"action":"comment","summary":"ok","comment":null,"usage":{"input_tokens":25,"cached_input_tokens":9,"output_tokens":7,"context_limit_tokens":4096}}'
    )
    assert outcome.summary == "ok"
    assert outcome.usage is not None
    assert outcome.usage["input_tokens"] == 25
    assert outcome.usage["cached_input_tokens"] == 9
    assert outcome.usage["output_tokens"] == 7
    assert outcome.usage["context_limit_tokens"] == 4096


def test_executor_parses_codex_session_id():
    from features.agents.executor import _parse_command_outcome

    outcome = _parse_command_outcome(
        '{"action":"comment","summary":"ok","comment":null,"codex_session_id":"thread-abc-123"}'
    )
    assert outcome.summary == "ok"
    assert outcome.codex_session_id == "thread-abc-123"


def test_executor_parses_resume_flags():
    from features.agents.executor import _parse_command_outcome

    outcome = _parse_command_outcome(
        (
            '{"action":"comment","summary":"ok","comment":null,'
            '"resume_attempted":true,"resume_succeeded":false,"resume_fallback_used":true}'
        )
    )
    assert outcome.resume_attempted is True
    assert outcome.resume_succeeded is False
    assert outcome.resume_fallback_used is True


def test_plain_text_result_uses_first_non_empty_line_for_summary():
    from features.agents.codex_mcp_adapter import _build_plain_text_result

    payload = _build_plain_text_result("\n\nHello world\n\nSecond line")
    assert payload["summary"] == "Hello world"
    assert payload["comment"] == "Hello world\n\nSecond line"


def test_plain_text_result_empty_message_uses_empty_assistant_summary():
    from features.agents.codex_mcp_adapter import EMPTY_ASSISTANT_SUMMARY, _build_plain_text_result

    payload = _build_plain_text_result("")
    assert payload["summary"] == EMPTY_ASSISTANT_SUMMARY
    assert payload["comment"] is None


def test_extract_message_text_supports_content_blocks():
    from features.agents.codex_mcp_adapter import _extract_message_text

    item = {
        "type": "assistant_message",
        "content": [
            {"type": "output_text", "text": "Alpha "},
            {"type": "output_text", "text": "Beta"},
        ],
    }
    assert _extract_message_text(item) == "Alpha Beta"


def test_extract_delta_text_supports_nested_delta_payload():
    from features.agents.codex_mcp_adapter import _extract_delta_text

    params = {
        "delta": {
            "type": "output_text_delta",
            "text": "Partial response",
        }
    }
    assert _extract_delta_text(params) == "Partial response"


def test_message_delta_method_recognizes_assistant_event_names():
    from features.agents.codex_mcp_adapter import _is_message_delta_method

    assert _is_message_delta_method("item/assistantMessage/delta")
    assert _is_message_delta_method("item/agentMessage/delta")
    assert _is_message_delta_method("item/assistant-message/delta")
    assert _is_message_delta_method("item.assistantMessage.delta")
    assert _is_message_delta_method("item.delta")
    assert not _is_message_delta_method("item/userMessage/delta")
    assert not _is_message_delta_method("item/systemMessage/delta")
    assert not _is_message_delta_method("item/toolCall/delta")


def test_assistant_message_item_type_filter():
    from features.agents.codex_mcp_adapter import _is_assistant_message_item_type

    assert _is_assistant_message_item_type("assistant_message")
    assert _is_assistant_message_item_type("agent_message")
    assert _is_assistant_message_item_type("message")
    assert _is_assistant_message_item_type("assistant-message")
    assert not _is_assistant_message_item_type("user_message")
    assert not _is_assistant_message_item_type("system_message")


def test_extract_error_message_prefers_message_and_details():
    from features.agents.codex_mcp_adapter import _extract_error_message

    payload = {
        "message": "Unauthorized",
        "additionalDetails": "Missing bearer token",
    }
    assert _extract_error_message(payload) == "Unauthorized | Missing bearer token"


def test_extract_error_message_supports_additional_details_snake_case():
    from features.agents.codex_mcp_adapter import _extract_error_message

    payload = {
        "additional_details": "Only details present",
    }
    assert _extract_error_message(payload) == "Only details present"


def test_resolve_persistent_codex_home_path_sanitizes_workspace_and_session(monkeypatch, tmp_path):
    from features.agents.codex_mcp_adapter import _resolve_persistent_codex_home_path

    root = tmp_path / "codex-home-root"
    monkeypatch.setenv("AGENT_CODEX_HOME_ROOT", str(root))
    resolved = _resolve_persistent_codex_home_path(
        workspace_id="WS / Main",
        chat_session_id="Session:Alpha?1",
    )
    assert resolved == root.resolve() / "workspace" / "ws___main" / "chat" / "session_alpha_1"


def test_codex_home_cleanup_removes_stale_session_dirs_and_respects_interval(monkeypatch, tmp_path):
    from features.agents.codex_mcp_adapter import run_codex_home_cleanup_if_due

    root = tmp_path / "codex-home"
    old_session = root / "workspace" / "ws-1" / "chat" / "old-session"
    fresh_session = root / "workspace" / "ws-1" / "chat" / "fresh-session"
    old_session.mkdir(parents=True, exist_ok=True)
    fresh_session.mkdir(parents=True, exist_ok=True)
    old_file = old_session / "marker.txt"
    fresh_file = fresh_session / "marker.txt"
    old_file.write_text("old", encoding="utf-8")
    fresh_file.write_text("fresh", encoding="utf-8")

    now = time.time()
    old_ts = now - (10 * 86400)
    fresh_ts = now - (1 * 86400)
    os.utime(old_session, (old_ts, old_ts))
    os.utime(old_file, (old_ts, old_ts))
    os.utime(fresh_session, (fresh_ts, fresh_ts))
    os.utime(fresh_file, (fresh_ts, fresh_ts))

    monkeypatch.setenv("AGENT_CODEX_HOME_ROOT", str(root))
    monkeypatch.setenv("AGENT_CODEX_HOME_RETENTION_DAYS", "7")
    monkeypatch.setenv("AGENT_CODEX_HOME_CLEANUP_INTERVAL_SECONDS", "3600")

    first = run_codex_home_cleanup_if_due(now_unix_seconds=now)
    assert first["ran"] is True
    assert first["removed"] == 1
    assert not old_session.exists()
    assert fresh_session.exists()

    second = run_codex_home_cleanup_if_due(now_unix_seconds=now + 120)
    assert second["ran"] is False
    assert second["removed"] == 0


def test_codex_adapter_main_non_stream_uses_app_server_resume_thread(monkeypatch):
    from contextlib import contextmanager
    from features.agents import codex_mcp_adapter as adapter_module

    captured: dict[str, object] = {}

    @contextmanager
    def _fake_home_env(
        *,
        mcp_config_text: str,
        runtime_config_text: str = "",
        workspace_id: str | None = None,
        chat_session_id: str | None = None,
    ):
        captured["home_env_workspace_id"] = workspace_id
        captured["home_env_chat_session_id"] = chat_session_id
        captured["home_env_runtime_config_text"] = runtime_config_text
        _ = mcp_config_text
        yield {"HOME": "/tmp/fake-codex-home"}

    @contextmanager
    def _fake_run_lock(
        *,
        workspace_id: str | None = None,
        chat_session_id: str | None = None,
        timeout_seconds: float,
        poll_interval_seconds: float = 0.1,
    ):
        captured["lock_workspace_id"] = workspace_id
        captured["lock_chat_session_id"] = chat_session_id
        captured["lock_timeout_seconds"] = timeout_seconds
        captured["lock_poll_interval_seconds"] = poll_interval_seconds
        yield

    def _fake_run_codex_app_server_with_optional_stream(
        *,
        start_prompt: str,
        resume_prompt: str | None,
        timeout_seconds: float,
        stream_events: bool,
        model: str | None = None,
        reasoning_effort: str | None = None,
        model_provider: str | None = None,
        local_provider: str | None = None,
        output_schema: dict | None = None,
        preferred_thread_id: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, int] | None, str | None, bool, bool]:
        captured["stream_events"] = stream_events
        captured["preferred_thread_id"] = preferred_thread_id
        captured["timeout_seconds"] = timeout_seconds
        captured["has_output_schema"] = isinstance(output_schema, dict)
        captured["env_home"] = (env or {}).get("HOME")
        captured["start_prompt_contains_context_pack"] = "Context Pack:" in start_prompt
        captured["resume_prompt_contains_context_pack"] = "Context Pack:" in str(resume_prompt or "")
        captured["resume_prompt_text"] = str(resume_prompt or "")
        _ = (model, reasoning_effort, model_provider, local_provider)
        return (
            '{"action":"comment","summary":"ok","comment":null}',
            {"input_tokens": 12, "output_tokens": 3},
            "thread-new-2",
            True,
            True,
        )

    monkeypatch.setattr(adapter_module, "_codex_home_env", _fake_home_env)
    monkeypatch.setattr(adapter_module, "_chat_session_run_lock", _fake_run_lock)
    monkeypatch.setattr(adapter_module, "_run_codex_app_server_with_optional_stream", _fake_run_codex_app_server_with_optional_stream)
    monkeypatch.setattr(adapter_module, "run_codex_home_cleanup_if_due", lambda **_: {"ran": False, "removed": 0, "failures": 0})
    monkeypatch.setattr(
        adapter_module.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "instruction": "Continue the same chat thread",
                    "workspace_id": "ws-main",
                    "chat_session_id": "chat-42",
                    "codex_session_id": "thread-prev-1",
                    "stream_events": False,
                }
            )
        ),
    )
    stdout = io.StringIO()
    monkeypatch.setattr(adapter_module.sys, "stdout", stdout)

    exit_code = adapter_module.main()
    assert exit_code == 0

    payload = json.loads(stdout.getvalue().strip())
    assert payload["codex_session_id"] == "thread-new-2"
    assert payload["resume_attempted"] is True
    assert payload["resume_succeeded"] is True
    assert payload["resume_fallback_used"] is False
    assert captured["stream_events"] is False
    assert captured["preferred_thread_id"] == "thread-prev-1"
    assert captured["has_output_schema"] is True
    assert captured["start_prompt_contains_context_pack"] is True
    assert captured["resume_prompt_contains_context_pack"] is False
    assert "This is a resumed Codex thread." in captured["resume_prompt_text"]
    assert captured["home_env_workspace_id"] == "ws-main"
    assert captured["home_env_chat_session_id"] == "chat-42"
    assert captured["env_home"] == "/tmp/fake-codex-home"
    assert captured["lock_workspace_id"] == "ws-main"
    assert captured["lock_chat_session_id"] == "chat-42"


def test_strip_mcp_server_tables_preserves_non_mcp_config():
    from features.agents.codex_mcp_adapter import _strip_mcp_server_tables

    input_config = """
model_provider = "oss"
model = "qwen2.5-coder:14b"

[mcp_servers.task-management-tools]
url = "http://mcp-tools:8091/mcp"

[mcp_servers.github]
url = "https://api.githubcopilot.com/mcp/"
bearer_token_env_var = "GITHUB_PAT"

[profiles.default]
approval_policy = "never"
""".strip()
    stripped = _strip_mcp_server_tables(input_config)
    assert 'model_provider = "oss"' in stripped
    assert 'model = "qwen2.5-coder:14b"' in stripped
    assert "[profiles.default]" in stripped
    assert "[mcp_servers.task-management-tools]" not in stripped
    assert "[mcp_servers.github]" not in stripped


def test_prepare_codex_home_merges_base_config_with_selected_mcp_servers(monkeypatch, tmp_path):
    from features.agents.codex_mcp_adapter import _prepare_codex_home

    source_home = tmp_path / "source-home"
    source_codex_dir = source_home / ".codex"
    source_codex_dir.mkdir(parents=True, exist_ok=True)
    (source_codex_dir / "config.toml").write_text(
        """
model_provider = "oss"
model = "qwen2.5-coder:14b"

[mcp_servers.old]
url = "http://old.example/mcp"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(source_home))

    target_home = tmp_path / "target-home"
    selected_mcp_text = """
[mcp_servers.task-management-tools]
url = "http://mcp-tools:8091/mcp"
""".strip()
    _prepare_codex_home(target_home, mcp_config_text=selected_mcp_text)
    output = (target_home / ".codex" / "config.toml").read_text(encoding="utf-8")

    assert 'model_provider = "oss"' in output
    assert 'model = "qwen2.5-coder:14b"' in output
    assert "[mcp_servers.old]" not in output
    assert "[mcp_servers.task-management-tools]" in output


def test_prepare_codex_home_applies_runtime_provider_overrides(monkeypatch, tmp_path):
    from features.agents.codex_mcp_adapter import _prepare_codex_home

    source_home = tmp_path / "source-home"
    source_codex_dir = source_home / ".codex"
    source_codex_dir.mkdir(parents=True, exist_ok=True)
    (source_codex_dir / "config.toml").write_text(
        """
model_provider = "openai"
model = "gpt-5.3-codex-spark"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(source_home))

    target_home = tmp_path / "target-home"
    _prepare_codex_home(
        target_home,
        mcp_config_text="",
        runtime_config_text='model_provider = "oss"\nlocal_provider = "ollama"\n',
    )
    output = (target_home / ".codex" / "config.toml").read_text(encoding="utf-8")

    assert output.count('model_provider = "openai"') == 1
    assert output.count('model_provider = "oss"') == 1
    assert 'local_provider = "ollama"' in output
