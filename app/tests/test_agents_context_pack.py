from __future__ import annotations

import json
from importlib import reload
from pathlib import Path


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
    login = client.post("/api/auth/login", json={"username": "m4tr1x", "password": "testtest"})
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
    monkeypatch.setattr(executor_module, "build_graph_context_markdown", lambda **_: "## Graph\nTask -> Specification")

    captured: dict = {}

    class DummyProcess:
        returncode = 0
        stdout = '{"action":"comment","summary":"ok","comment":null}'
        stderr = ""

    def fake_run(command, *, input, text, capture_output, timeout, check):  # noqa: A002
        _ = (command, text, capture_output, timeout, check)
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
    assert captured["graph_context_markdown"] == "## Graph\nTask -> Specification"


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
    assert "set_user_theme(theme='light'|'dark')" in prompt
    assert "File: GraphContext.md (source: knowledge_graph)" in prompt
    assert "Task A IMPLEMENTS Spec B" in prompt


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

    assert "strict interactive setup protocol" in prompt
    assert "Strict protocol is mandatory" in prompt
    assert "list_project_templates -> get_project_template -> collect template parameters -> preview_project_from_template" in prompt
    assert "Never call create_project or create_project_from_template" in prompt


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
