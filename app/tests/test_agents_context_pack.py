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

    return TestClient(main.app)


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
        allow_mutations=True,
    )

    assert outcome.summary == "ok"
    assert captured["project_id"] == project["id"]
    assert captured["project_name"] == "Agent Context"
    assert captured["project_description"] == "# Project soul\nAlways include tests."
    assert captured["project_rules"][0]["title"] == "Definition of done"
    assert captured["project_rules"][0]["body"] == "Always add or update tests."
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
    assert "File: GraphContext.md (source: knowledge_graph)" in prompt
    assert "Task A IMPLEMENTS Spec B" in prompt
