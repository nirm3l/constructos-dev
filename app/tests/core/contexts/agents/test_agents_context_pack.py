from __future__ import annotations

import io
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from importlib import reload
from pathlib import Path
from types import SimpleNamespace

import pytest
from shared.models import ProjectMember, SessionLocal, Task, User as UserModel, WorkspaceAgentRuntime

_MIN_EXECUTION_OUTCOME_CONTRACT_JSON = (
    '"execution_outcome_contract":{"contract_version":1,"files_changed":[],"commit_sha":null,'
    '"branch":null,"tests_run":false,"tests_passed":false,"artifacts":[]}'
)


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
        stdout = (
            '{"action":"comment","summary":"ok","comment":null,'
            + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
            + "}"
        )
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
        stdout = (
            '{"action":"comment","summary":"ok","comment":null,'
            + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
            + "}"
        )
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
        stdout = (
            '{"action":"comment","summary":"ok","comment":null,'
            + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
            + "}"
        )
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
        stdout = (
            '{"action":"comment","summary":"ok","comment":null,'
            + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
            + "}"
        )
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
    assert captured["actor_project_role"] == "QA"


def test_execute_task_automation_sets_task_worktree_context_for_team_mode_developer(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project = client.post(
        "/api/projects",
        json={"workspace_id": ws_id, "name": "Team Mode Worktree Context"},
    ).json()
    actor_user_id = str(uuid.uuid4())

    from shared.models import ProjectSkill

    with SessionLocal() as db:
        db.add(
            UserModel(
                id=actor_user_id,
                username="agent.dev.ctx",
                full_name="Developer Agent Context",
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
                project_id=project["id"],
                user_id=actor_user_id,
                role="DeveloperAgent",
            )
        )
        db.commit()

    enable_team_mode = client.post(
        f"/api/projects/{project['id']}/plugins/team_mode/enabled",
        json={"enabled": True},
    )
    assert enable_team_mode.status_code == 200

    from features.agents import executor as executor_module

    monkeypatch.setattr(executor_module, "AGENT_EXECUTOR_MODE", "command")
    monkeypatch.setattr(executor_module, "AGENT_CODEX_COMMAND", "dummy-exec")
    monkeypatch.setattr(
        executor_module,
        "_ensure_task_worktree",
        lambda **_kwargs: (
            Path("/home/app/workspace/team-mode-worktree/.constructos/worktrees/task1234"),
            "task/task1234-feature",
            Path("/home/app/workspace/team-mode-worktree"),
        ),
    )

    captured: dict = {}

    class DummyProcess:
        returncode = 0
        stdout = (
            '{"action":"comment","summary":"ok","comment":null,'
            + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
            + "}"
        )
        stderr = ""

    def fake_run(command, *, input, text, capture_output, timeout, check, cwd=None):  # noqa: A002
        _ = (command, text, capture_output, timeout, check, cwd)
        captured.update(json.loads(input))
        return DummyProcess()

    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    outcome = executor_module.execute_task_automation(
        task_id="task-1234-worktree",
        title="Implement feature",
        description="ctx",
        status="In Progress",
        instruction="Implement in isolated worktree",
        workspace_id=ws_id,
        project_id=project["id"],
        actor_user_id=actor_user_id,
        allow_mutations=True,
    )
    assert outcome.summary == "ok"
    assert captured["actor_project_role"] == "Developer"
    assert captured["team_mode_enabled"] is True
    assert captured["task_workdir"] == "/home/app/workspace/team-mode-worktree/.constructos/worktrees/task1234"
    assert captured["task_branch"] == "task/task1234-feature"
    assert captured["repo_root"] == "/home/app/workspace/team-mode-worktree"


def test_execute_task_automation_uses_assigned_bot_runtime_before_workspace_selection(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    from shared.settings import AGENT_SYSTEM_USER_ID, CLAUDE_SYSTEM_USER_ID

    task_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(
            WorkspaceAgentRuntime(
                workspace_id=ws_id,
                user_id=AGENT_SYSTEM_USER_ID,
                model="codex:gpt-5-codex",
                reasoning_effort="high",
                is_background_default=False,
            )
        )
        db.add(
            WorkspaceAgentRuntime(
                workspace_id=ws_id,
                user_id=CLAUDE_SYSTEM_USER_ID,
                model="claude:sonnet",
                reasoning_effort="",
                is_background_default=True,
            )
        )
        db.add(
            Task(
                id=task_id,
                workspace_id=ws_id,
                project_id=project_id,
                title="Assigned bot runtime",
                description="ctx",
                status="To do",
                assignee_id=AGENT_SYSTEM_USER_ID,
            )
        )
        db.commit()

    from features.agents import executor as executor_module

    monkeypatch.setattr(executor_module, "AGENT_EXECUTOR_MODE", "command")
    monkeypatch.setattr(executor_module, "AGENT_CODEX_COMMAND", "dummy-exec")

    captured: dict = {}

    class DummyProcess:
        returncode = 0
        stdout = (
            '{"action":"comment","summary":"ok","comment":null,'
            + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
            + "}"
        )
        stderr = ""

    def fake_run(command, *, input, text, capture_output, timeout, check, cwd=None):  # noqa: A002
        _ = (command, text, capture_output, timeout, check, cwd)
        captured.update(json.loads(input))
        return DummyProcess()

    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    outcome = executor_module.execute_task_automation(
        task_id=task_id,
        title="Assigned bot runtime",
        description="ctx",
        status="To do",
        instruction="Use the assigned bot runtime.",
        workspace_id=ws_id,
        project_id=project_id,
        actor_user_id=bootstrap["current_user"]["id"],
        allow_mutations=True,
    )

    assert outcome.summary == "ok"
    assert captured["model"] == "codex:gpt-5-codex"
    assert captured["reasoning_effort"] == "high"


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


def test_codex_prompt_includes_task_workspace_context():
    from features.agents.codex_mcp_adapter import _build_prompt

    prompt = _build_prompt(
        {
            "task_id": "task-1",
            "title": "Implement feature",
            "description": "worktree-aware run",
            "status": "In Progress",
            "instruction": "Start implementation",
            "workspace_id": "ws-1",
            "project_id": "pr-1",
            "actor_user_id": "user-1",
            "actor_project_role": "DeveloperAgent",
            "project_name": "Alpha",
            "project_description": "",
            "project_rules": [],
            "project_skills": [{"skill_key": "team_mode"}],
            "task_workdir": "/home/app/workspace/alpha/.constructos/worktrees/task-1",
            "task_branch": "task/task-1-implement-feature",
            "repo_root": "/home/app/workspace/alpha",
            "graph_context_markdown": "",
        }
    )

    assert "Task Branch: task/task-1-implement-feature" in prompt
    assert "Task Workdir: /home/app/workspace/alpha/.constructos/worktrees/task-1" in prompt
    assert "execute implementation from that workdir and commit only on that branch" in prompt
    assert "Treat `Task Workdir` as the only valid editing root for task automation." in prompt


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
    assert "If Team Mode is requested, prefer this setup flow" in resume_prompt
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
                        "snippet": "The secret number is 44",
                    }
                ]
            ),
        }
    )

    assert "Fresh Cross-Session Memory Snapshot" in prompt
    assert "Fresh Summary:" in prompt
    assert "Fresh Evidence:" in prompt
    assert "The secret number is 44" in prompt
    assert "score=0.992" in prompt


def test_prompt_segment_char_stats_uses_instruction_breakdown():
    from features.agents.codex_mcp_adapter import _prompt_segment_char_stats

    stats = _prompt_segment_char_stats(
        {
            "instruction": "short",
            "prompt_instruction_segments": {
                "user_instruction": 120,
                "attachment_context": 450,
                "cross_session_updates": 210,
            },
            "trigger_task_id": "",
            "trigger_from_status": "",
            "trigger_to_status": "",
            "trigger_timestamp": "",
            "plugin_policy_json": "{}",
            "plugin_required_checks": "",
            "graph_summary_markdown": "",
            "graph_evidence_json": "[]",
        },
        mode="resume",
    )

    assert stats["instruction"] == 780
    assert stats["instruction_user_instruction"] == 120
    assert stats["instruction_attachment_context"] == 450
    assert stats["instruction_cross_session_updates"] == 210
    assert "fresh_memory_snapshot" in stats


def test_codex_resume_prompt_includes_task_workspace_context():
    from features.agents.codex_mcp_adapter import _build_resume_prompt

    prompt = _build_resume_prompt(
        {
            "task_id": "task-1",
            "title": "Implement feature",
            "description": "worktree-aware run",
            "status": "In Progress",
            "instruction": "Resume implementation",
            "workspace_id": "ws-1",
            "project_id": "pr-1",
            "actor_user_id": "user-1",
            "project_name": "Alpha",
            "task_workdir": "/home/app/workspace/alpha/.constructos/worktrees/task-1",
            "task_branch": "task/task-1-implement-feature",
            "repo_root": "/home/app/workspace/alpha",
        }
    )

    assert "Task Branch: task/task-1-implement-feature" in prompt
    assert "Task Workdir: /home/app/workspace/alpha/.constructos/worktrees/task-1" in prompt
    assert "Treat `Task Workdir` as the only valid editing root for task automation." in prompt


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
    assert "prefer `setup_project_orchestration(...)` once required inputs are complete" in prompt
    assert "call `setup_project_orchestration(...)` as early as possible" in prompt
    assert "returns HTTP 422 with `missing_inputs`" in prompt
    assert "ask only the `next_question`" in prompt
    assert "present a user-friendly completion summary" in prompt
    assert "To do, In Progress, In Review, Awaiting decision, Blocked, Completed" in prompt
    assert "If Team Mode is requested, prefer this setup flow" in prompt
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
    assert "project starters" in mcp_server.LIST_PROJECT_STARTERS_TOOL_DESCRIPTION.lower()
    assert "setup profile" in mcp_server.GET_PROJECT_SETUP_PROFILE_TOOL_DESCRIPTION.lower()
    assert "in-app notification" in mcp_server.SEND_IN_APP_NOTIFICATION_TOOL_DESCRIPTION.lower()
    assert "staged project setup in one call" in mcp_server.SETUP_PROJECT_ORCHESTRATION_TOOL_DESCRIPTION
    assert "missing_inputs" in mcp_server.SETUP_PROJECT_ORCHESTRATION_TOOL_DESCRIPTION
    assert "deprecated" in mcp_server.ENSURE_TEAM_MODE_PROJECT_TOOL_DESCRIPTION.lower()
    assert "backward compatibility" in mcp_server.ENSURE_TEAM_MODE_PROJECT_TOOL_DESCRIPTION.lower()
    source = inspect.getsource(mcp_server)
    assert "embedding_enabled: bool = MCP_DEFAULT_PROJECT_EMBEDDING_ENABLED" in source
    assert "chat_index_mode: str = MCP_DEFAULT_PROJECT_CHAT_INDEX_MODE" in source
    assert "chat_attachment_ingestion_mode: str = MCP_DEFAULT_PROJECT_CHAT_ATTACHMENT_INGESTION_MODE" in source
    assert "primary_starter_key: str | None = None" in source
    assert "facet_keys: list[str] | None = None" in source
    assert "def send_in_app_notification(" in source


def test_create_mcp_registers_and_executes_setup_project_orchestration_tool(monkeypatch):
    from features.agents import mcp_server

    class FakeFastMCP:
        def __init__(self, name: str):
            self.name = name
            self._tools: dict[str, dict[str, object]] = {}

        def tool(self, description: str = ""):
            def _decorator(fn):
                self._tools[fn.__name__] = {"fn": fn, "description": description}
                return fn

            return _decorator

    captured: dict[str, object] = {}

    class FakeGateway:
        def setup_project_orchestration(self, **kwargs):
            captured.update(kwargs)
            return {
                "contract_version": 1,
                "ok": True,
                "project": {"id": "project-e2e", "link": "?tab=projects&project=project-e2e"},
            }

    monkeypatch.setitem(sys.modules, "fastmcp", SimpleNamespace(FastMCP=FakeFastMCP))
    monkeypatch.setattr(mcp_server, "build_mcp_gateway", lambda: FakeGateway())
    monkeypatch.setattr(mcp_server, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(mcp_server, "AGENT_ENABLED_PLUGINS", ["team_mode", "git_delivery", "docker_compose"])

    mcp = mcp_server.create_mcp()
    setup_tool = mcp._tools.get("setup_project_orchestration")
    assert setup_tool is not None
    fn = setup_tool["fn"]
    payload = fn(
        name="MCP E2E",
        short_description="End-to-end registration test.",
        workspace_id="ws-1",
        enable_team_mode=True,
        enable_docker_compose=True,
        docker_port=6768,
        seed_team_tasks=True,
        command_id="e2e-setup-001",
    )

    assert payload["ok"] is True
    assert payload["project"]["id"] == "project-e2e"
    assert captured["name"] == "MCP E2E"
    assert captured["enable_team_mode"] is True
    assert captured["enable_docker_compose"] is True
    assert captured["docker_port"] == 6768


def test_create_mcp_setup_project_orchestration_tool_runs_real_service_flow(tmp_path, monkeypatch):
    from features.agents import mcp_server
    from features.agents.service import AgentTaskService

    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    actor_user_id = bootstrap["current_user"]["id"]

    class FakeFastMCP:
        def __init__(self, name: str):
            self.name = name
            self._tools: dict[str, dict[str, object]] = {}

        def tool(self, description: str = ""):
            def _decorator(fn):
                self._tools[fn.__name__] = {"fn": fn, "description": description}
                return fn

            return _decorator

    monkeypatch.setitem(sys.modules, "fastmcp", SimpleNamespace(FastMCP=FakeFastMCP))
    monkeypatch.setattr(
        mcp_server,
        "build_mcp_gateway",
        lambda: AgentTaskService(
            require_token=False,
            actor_user_id=actor_user_id,
            allowed_workspace_ids={workspace_id},
            allowed_project_ids=set(),
            default_workspace_id=workspace_id,
        ),
    )
    monkeypatch.setattr(mcp_server, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(mcp_server, "AGENT_ENABLED_PLUGINS", ["team_mode", "git_delivery", "docker_compose"])

    mcp = mcp_server.create_mcp()
    setup_tool = mcp._tools.get("setup_project_orchestration")
    assert setup_tool is not None
    fn = setup_tool["fn"]
    payload = fn(
        name="MCP Integration Project",
        short_description="Setup via MCP tool layer.",
        primary_starter_key="web_app",
        workspace_id=workspace_id,
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=True,
        docker_port=6768,
        seed_team_tasks=False,
        kickoff_after_setup=False,
        command_id="mcp-e2e-setup-001",
    )

    assert payload["contract_version"] == 1
    assert payload["execution_state"] in {"setup_complete", "setup_failed"}
    assert payload["project"]["id"]
    assert payload["effective"]["team_mode_enabled"] is True
    assert payload["effective"]["git_delivery_enabled"] is True
    assert payload["effective"]["docker_compose_enabled"] is True
    assert isinstance(payload["steps"], list)
    assert payload["steps"]


def test_create_mcp_setup_project_orchestration_tool_supports_kickoff_after_setup(tmp_path, monkeypatch):
    from features.agents import mcp_server
    from features.agents.service import AgentTaskService

    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    actor_user_id = bootstrap["current_user"]["id"]

    class FakeFastMCP:
        def __init__(self, name: str):
            self.name = name
            self._tools: dict[str, dict[str, object]] = {}

        def tool(self, description: str = ""):
            def _decorator(fn):
                self._tools[fn.__name__] = {"fn": fn, "description": description}
                return fn

            return _decorator

    monkeypatch.setitem(sys.modules, "fastmcp", SimpleNamespace(FastMCP=FakeFastMCP))
    monkeypatch.setattr(
        mcp_server,
        "build_mcp_gateway",
        lambda: AgentTaskService(
            require_token=False,
            actor_user_id=actor_user_id,
            allowed_workspace_ids={workspace_id},
            allowed_project_ids=set(),
            default_workspace_id=workspace_id,
        ),
    )
    monkeypatch.setattr(mcp_server, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(mcp_server, "AGENT_ENABLED_PLUGINS", ["team_mode", "git_delivery", "docker_compose"])

    mcp = mcp_server.create_mcp()
    setup_tool = mcp._tools.get("setup_project_orchestration")
    assert setup_tool is not None
    fn = setup_tool["fn"]
    payload = fn(
        name="MCP Integration Project Kickoff",
        short_description="Setup via MCP tool layer with kickoff.",
        primary_starter_key="web_app",
        workspace_id=workspace_id,
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=True,
        docker_port=6768,
        seed_team_tasks=True,
        kickoff_after_setup=True,
        command_id="mcp-e2e-setup-kickoff-001",
    )

    assert payload["contract_version"] == 1
    assert payload["project"]["id"]
    assert payload["effective"]["team_mode_enabled"] is True
    assert payload["effective"]["git_delivery_enabled"] is True
    assert payload["effective"]["docker_compose_enabled"] is True
    requested = payload.get("requested")
    assert isinstance(requested, dict)
    assert requested.get("kickoff_after_setup") is True
    kickoff = payload.get("kickoff")
    if isinstance(kickoff, dict):
        assert isinstance(kickoff.get("ok"), bool)
        assert isinstance(kickoff.get("summary"), str)
        assert "kickoff" in str(kickoff.get("summary") or "").lower()


def test_create_mcp_setup_project_orchestration_setup_only_does_not_fail_on_delivery_warning(tmp_path, monkeypatch):
    from features.agents import mcp_server
    from features.agents.service import AgentTaskService

    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    actor_user_id = bootstrap["current_user"]["id"]

    class FakeFastMCP:
        def __init__(self, name: str):
            self.name = name
            self._tools: dict[str, dict[str, object]] = {}

        def tool(self, description: str = ""):
            def _decorator(fn):
                self._tools[fn.__name__] = {"fn": fn, "description": description}
                return fn

            return _decorator

    monkeypatch.setitem(sys.modules, "fastmcp", SimpleNamespace(FastMCP=FakeFastMCP))
    monkeypatch.setattr(
        mcp_server,
        "build_mcp_gateway",
        lambda: AgentTaskService(
            require_token=False,
            actor_user_id=actor_user_id,
            allowed_workspace_ids={workspace_id},
            allowed_project_ids=set(),
            default_workspace_id=workspace_id,
        ),
    )
    monkeypatch.setattr(mcp_server, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(mcp_server, "AGENT_ENABLED_PLUGINS", ["team_mode", "git_delivery", "docker_compose"])

    monkeypatch.setattr(
        AgentTaskService,
        "verify_team_mode_workflow",
        lambda self, **kwargs: {
            "ok": True,
            "workspace_id": str(kwargs.get("workspace_id") or ""),
            "required_failed_checks": [],
            "check_descriptions": {},
        },
    )
    monkeypatch.setattr(
        AgentTaskService,
        "verify_delivery_workflow",
        lambda self, **kwargs: {
            "ok": False,
            "required_failed_checks": ["repo_context_present"],
            "check_descriptions": {"repo_context_present": "Repository context must be linked."},
        },
    )

    mcp = mcp_server.create_mcp()
    setup_tool = mcp._tools.get("setup_project_orchestration")
    assert setup_tool is not None
    fn = setup_tool["fn"]
    payload = fn(
        name="MCP Setup-Only Delivery Warning",
        short_description="Validate setup-only success semantics.",
        primary_starter_key="web_app",
        workspace_id=workspace_id,
        enable_team_mode=True,
        enable_git_delivery=True,
        enable_docker_compose=True,
        docker_port=6768,
        seed_team_tasks=False,
        kickoff_after_setup=False,
        command_id="mcp-setup-only-delivery-warning-001",
    )

    assert payload["ok"] is True
    verification = (
        payload.get("user_facing_summary", {}).get("verification", {})
        if isinstance(payload.get("user_facing_summary"), dict)
        else {}
    )
    assert verification.get("delivery_status") == "Needs attention"
    assert verification.get("delivery_required_for_success") is False
    blocking_state = payload.get("user_facing_summary", {}).get("blocking_state", {})
    assert blocking_state.get("code") != "delivery_pending"


def test_create_mcp_setup_project_orchestration_tool_returns_missing_inputs_contract(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from features.agents import mcp_server
    from features.agents.service import AgentTaskService

    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    actor_user_id = bootstrap["current_user"]["id"]

    class FakeFastMCP:
        def __init__(self, name: str):
            self.name = name
            self._tools: dict[str, dict[str, object]] = {}

        def tool(self, description: str = ""):
            def _decorator(fn):
                self._tools[fn.__name__] = {"fn": fn, "description": description}
                return fn

            return _decorator

    monkeypatch.setitem(sys.modules, "fastmcp", SimpleNamespace(FastMCP=FakeFastMCP))
    monkeypatch.setattr(
        mcp_server,
        "build_mcp_gateway",
        lambda: AgentTaskService(
            require_token=False,
            actor_user_id=actor_user_id,
            allowed_workspace_ids={workspace_id},
            allowed_project_ids=set(),
            default_workspace_id=workspace_id,
        ),
    )
    monkeypatch.setattr(mcp_server, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(mcp_server, "AGENT_ENABLED_PLUGINS", ["team_mode", "git_delivery", "docker_compose"])

    mcp = mcp_server.create_mcp()
    setup_tool = mcp._tools.get("setup_project_orchestration")
    assert setup_tool is not None
    fn = setup_tool["fn"]
    with pytest.raises(HTTPException) as exc:
        fn(
            workspace_id=workspace_id,
            name="",
            short_description="",
            command_id="mcp-missing-inputs-001",
        )
    assert exc.value.status_code == 422
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "missing_setup_inputs"
    assert isinstance(detail.get("missing_inputs"), list)
    assert str(detail.get("next_question") or "").strip() != ""


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
        (
            '{"action":"comment","summary":"ok","comment":null,'
            + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
            + ',"usage":{"input_tokens":25,"cached_input_tokens":9,"output_tokens":7,"context_limit_tokens":4096}}'
        )
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
        (
            '{"action":"comment","summary":"ok","comment":null,'
            + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
            + ',"codex_session_id":"thread-abc-123"}'
        )
    )
    assert outcome.summary == "ok"
    assert outcome.codex_session_id == "thread-abc-123"


def test_executor_parses_resume_flags():
    from features.agents.executor import _parse_command_outcome

    outcome = _parse_command_outcome(
        (
            '{"action":"comment","summary":"ok","comment":null,'
            + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
            + ","
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


def test_extract_delta_text_preserves_leading_space_for_claude_text_delta():
    from features.agents.codex_mcp_adapter import _extract_delta_text

    params = {
        "delta": {
            "type": "text_delta",
            "text": " on various",
        }
    }
    assert _extract_delta_text(params) == " on various"


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
        provider: str,
        mcp_config_text: str,
        runtime_config_text: str = "",
        opencode_config_payload: dict | None = None,
        workspace_id: str | None = None,
        chat_session_id: str | None = None,
        actor_user_id: str | None = None,
    ):
        captured["home_env_provider"] = provider
        captured["home_env_workspace_id"] = workspace_id
        captured["home_env_chat_session_id"] = chat_session_id
        captured["home_env_runtime_config_text"] = runtime_config_text
        _ = (mcp_config_text, actor_user_id, opencode_config_payload)
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
        provider: str,
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
        mcp_config_payload: dict | None = None,
        run_cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, int] | None, str | None, bool, bool]:
        captured["run_provider"] = provider
        captured["stream_events"] = stream_events
        captured["preferred_thread_id"] = preferred_thread_id
        captured["timeout_seconds"] = timeout_seconds
        captured["has_output_schema"] = isinstance(output_schema, dict)
        captured["env_home"] = (env or {}).get("HOME")
        captured["start_prompt_contains_context_pack"] = "Context Pack:" in start_prompt
        captured["resume_prompt_contains_context_pack"] = "Context Pack:" in str(resume_prompt or "")
        captured["resume_prompt_text"] = str(resume_prompt or "")
        _ = (model, reasoning_effort, model_provider, local_provider, mcp_config_payload, run_cwd)
        return (
            (
                '{"action":"comment","summary":"ok","comment":null,'
                + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
                + "}"
            ),
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


def test_codex_adapter_main_forces_non_stream_for_opencode(monkeypatch):
    from contextlib import contextmanager
    from features.agents import codex_mcp_adapter as adapter_module

    captured: dict[str, object] = {}

    @contextmanager
    def _fake_home_env(
        *,
        provider: str,
        mcp_config_text: str,
        runtime_config_text: str = "",
        opencode_config_payload: dict | None = None,
        workspace_id: str | None = None,
        chat_session_id: str | None = None,
        actor_user_id: str | None = None,
    ):
        _ = (
            provider,
            mcp_config_text,
            runtime_config_text,
            opencode_config_payload,
            workspace_id,
            chat_session_id,
            actor_user_id,
        )
        yield {"HOME": "/tmp/fake-codex-home"}

    @contextmanager
    def _fake_run_lock(
        *,
        workspace_id: str | None = None,
        chat_session_id: str | None = None,
        timeout_seconds: float,
        poll_interval_seconds: float = 0.1,
    ):
        _ = (workspace_id, chat_session_id, timeout_seconds, poll_interval_seconds)
        yield

    def _fake_run_codex_app_server_with_optional_stream(
        *,
        provider: str,
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
        mcp_config_payload: dict | None = None,
        run_cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, int] | None, str | None, bool, bool]:
        captured["provider"] = provider
        captured["stream_events"] = stream_events
        _ = (
            start_prompt,
            resume_prompt,
            timeout_seconds,
            model,
            reasoning_effort,
            model_provider,
            local_provider,
            output_schema,
            preferred_thread_id,
            mcp_config_payload,
            run_cwd,
            env,
        )
        return (
            (
                '{"action":"comment","summary":"ok","comment":null,'
                + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
                + "}"
            ),
            {"input_tokens": 3, "output_tokens": 1},
            "thread-opencode",
            False,
            False,
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
                    "instruction": "hello",
                    "workspace_id": "ws-main",
                    "chat_session_id": "chat-opencode",
                    "stream_events": True,
                    "stream_plain_text": True,
                    "model": "opencode/gpt-5-nano",
                }
            )
        ),
    )
    stdout = io.StringIO()
    monkeypatch.setattr(adapter_module.sys, "stdout", stdout)

    exit_code = adapter_module.main()
    assert exit_code == 0
    assert captured["provider"] == "opencode"
    assert captured["stream_events"] is False


def test_strip_mcp_server_tables_preserves_non_mcp_config():
    from features.agents.codex_mcp_adapter import _strip_mcp_server_tables

    input_config = """
model_provider = "openai"
model = "gpt-5.3-codex-spark"

[mcp_servers.constructos-tools]
url = "http://mcp-tools:8091/mcp"

[mcp_servers.github]
url = "https://api.githubcopilot.com/mcp/"
bearer_token_env_var = "GITHUB_PAT"

[profiles.default]
approval_policy = "never"
""".strip()
    stripped = _strip_mcp_server_tables(input_config)
    assert 'model_provider = "openai"' in stripped
    assert 'model = "gpt-5.3-codex-spark"' in stripped
    assert "[profiles.default]" in stripped
    assert "[mcp_servers.constructos-tools]" not in stripped
    assert "[mcp_servers.github]" not in stripped


def test_prepare_codex_home_merges_base_config_with_selected_mcp_servers(monkeypatch, tmp_path):
    from features.agents.codex_mcp_adapter import _prepare_codex_home

    source_home = tmp_path / "source-home"
    source_codex_dir = source_home / ".codex"
    source_codex_dir.mkdir(parents=True, exist_ok=True)
    (source_codex_dir / "config.toml").write_text(
        """
model_provider = "openai"
model = "gpt-5.3-codex-spark"

[mcp_servers.old]
url = "http://old.example/mcp"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(source_home))

    target_home = tmp_path / "target-home"
    selected_mcp_text = """
[mcp_servers.constructos-tools]
url = "http://mcp-tools:8091/mcp"
""".strip()
    _prepare_codex_home(target_home, provider="codex", mcp_config_text=selected_mcp_text)
    output = (target_home / ".codex" / "config.toml").read_text(encoding="utf-8")

    assert 'model_provider = "openai"' in output
    assert 'model = "gpt-5.3-codex-spark"' in output
    assert "[mcp_servers.old]" not in output
    assert "[mcp_servers.constructos-tools]" in output


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
        provider="codex",
        mcp_config_text="",
        runtime_config_text='model_provider = "openai"\nreasoning_effort = "medium"\n',
    )
    output = (target_home / ".codex" / "config.toml").read_text(encoding="utf-8")

    assert output.count('model_provider = "openai"') >= 1
    assert 'reasoning_effort = "medium"' in output


def test_codex_home_env_sets_opencode_inline_mcp_config(monkeypatch):
    from features.agents.codex_mcp_adapter import _codex_home_env

    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", json.dumps({"model": "opencode/nemotron-3-super-free"}))
    opencode_mcp_payload = {
        "mcp": {
            "constructos-tools": {
                "type": "remote",
                "url": "http://localhost:8091/mcp",
                "enabled": True,
            }
        }
    }

    with _codex_home_env(
        provider="opencode",
        mcp_config_text="",
        opencode_config_payload=opencode_mcp_payload,
    ) as env:
        merged_raw = str(env.get("OPENCODE_CONFIG_CONTENT") or "").strip()
        assert merged_raw
        merged = json.loads(merged_raw)
        assert merged.get("model") == "opencode/nemotron-3-super-free"
        assert merged["mcp"]["constructos-tools"]["type"] == "remote"
        assert merged["mcp"]["constructos-tools"]["url"] == "http://localhost:8091/mcp"
        assert merged["mcp"]["constructos-tools"]["enabled"] is True


def test_run_structured_prompt_uses_cache_when_input_unchanged(monkeypatch):
    from features.agents import codex_mcp_adapter as adapter_module

    adapter_module._STRUCTURED_PROMPT_CACHE.clear()

    @contextmanager
    def _noop_lock(**kwargs):
        _ = kwargs
        yield

    @contextmanager
    def _noop_home_env(**kwargs):
        _ = kwargs
        yield {}

    calls = {"count": 0}

    def _fake_runner(**kwargs):
        _ = kwargs
        calls["count"] += 1
        return ('{"ok": true}', {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}, None, False, False)

    monkeypatch.setattr(adapter_module, "_chat_session_run_lock", _noop_lock)
    monkeypatch.setattr(adapter_module, "_codex_home_env", _noop_home_env)
    monkeypatch.setattr(adapter_module, "run_codex_home_cleanup_if_due", lambda **_: {"ran": False, "removed": 0, "failures": 0})
    monkeypatch.setattr(adapter_module, "_run_codex_app_server_with_optional_stream", _fake_runner)

    payload1, usage1 = adapter_module.run_structured_codex_prompt_with_usage(
        prompt="classify this",
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
        workspace_id="ws-1",
        session_key="session-1",
        mcp_servers=[],
    )
    payload2, usage2 = adapter_module.run_structured_codex_prompt_with_usage(
        prompt="classify this",
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
        workspace_id="ws-1",
        session_key="session-1",
        mcp_servers=[],
    )

    assert calls["count"] == 1
    assert payload1 == {"ok": True}
    assert payload2 == {"ok": True}
    assert usage1 == usage2


def test_run_structured_prompt_recomputes_when_input_changes(monkeypatch):
    from features.agents import codex_mcp_adapter as adapter_module

    adapter_module._STRUCTURED_PROMPT_CACHE.clear()

    @contextmanager
    def _noop_lock(**kwargs):
        _ = kwargs
        yield

    @contextmanager
    def _noop_home_env(**kwargs):
        _ = kwargs
        yield {}

    calls = {"count": 0}

    def _fake_runner(**kwargs):
        _ = kwargs
        calls["count"] += 1
        return ('{"ok": true}', {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}, None, False, False)

    monkeypatch.setattr(adapter_module, "_chat_session_run_lock", _noop_lock)
    monkeypatch.setattr(adapter_module, "_codex_home_env", _noop_home_env)
    monkeypatch.setattr(adapter_module, "run_codex_home_cleanup_if_due", lambda **_: {"ran": False, "removed": 0, "failures": 0})
    monkeypatch.setattr(adapter_module, "_run_codex_app_server_with_optional_stream", _fake_runner)

    adapter_module.run_structured_codex_prompt_with_usage(
        prompt="classify this",
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
        workspace_id="ws-1",
        session_key="session-1",
        mcp_servers=[],
    )
    adapter_module.run_structured_codex_prompt_with_usage(
        prompt="classify this changed",
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
        workspace_id="ws-1",
        session_key="session-1",
        mcp_servers=[],
    )


def test_run_opencode_cli_preserves_text_delta_whitespace(monkeypatch):
    from features.agents import codex_mcp_adapter as adapter_module

    events = [
        {"type": "step_start", "sessionID": "ses-1"},
        {"type": "text", "part": {"text": "Hello"}},
        {"type": "text", "part": {"text": " world"}},
        {"type": "step_finish", "part": {"tokens": {"input": 1, "output": 2}}},
    ]

    class _FakeProc:
        def __init__(self, output_lines):
            self.stdout = output_lines

        def poll(self):
            return None

        def kill(self):
            return None

        def wait(self):
            return 0

    fake_output = [json.dumps(event) + "\n" for event in events]

    monkeypatch.setattr(
        adapter_module.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeProc(fake_output),
    )

    final_message, usage, session_id, resume_attempted, resume_succeeded = adapter_module._run_opencode_cli_with_optional_stream(
        start_prompt="Say hello",
        resume_prompt=None,
        timeout_seconds=None,
        stream_events=False,
        model="opencode/gpt-5-nano",
        reasoning_effort=None,
        output_schema=None,
        preferred_thread_id=None,
        env=None,
        run_cwd=None,
    )

    assert final_message == "Hello world"
    assert usage == {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 2}
    assert session_id == "ses-1"
    assert resume_attempted is False
    assert resume_succeeded is False


def test_run_opencode_cli_accepts_final_result_payload_without_text_deltas(monkeypatch):
    from features.agents import codex_mcp_adapter as adapter_module

    structured_payload = (
        '{"action":"comment","summary":"ok","comment":null,'
        + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
        + "}"
    )
    events = [
        {"type": "step_start", "sessionID": "ses-2"},
        {"type": "result", "result": {"text": structured_payload}},
        {"type": "step_finish", "part": {"tokens": {"input": 5, "output": 7}}},
    ]

    class _FakeProc:
        def __init__(self, output_lines):
            self.stdout = output_lines

        def poll(self):
            return None

        def kill(self):
            return None

        def wait(self):
            return 0

    fake_output = [json.dumps(event) + "\n" for event in events]
    monkeypatch.setattr(
        adapter_module.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeProc(fake_output),
    )

    final_message, usage, session_id, resume_attempted, resume_succeeded = adapter_module._run_opencode_cli_with_optional_stream(
        start_prompt="Say hello",
        resume_prompt=None,
        timeout_seconds=None,
        stream_events=False,
        model="opencode/gpt-5-nano",
        reasoning_effort=None,
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {"type": "string"},
                "summary": {"type": "string"},
                "comment": {"type": ["string", "null"]},
                "execution_outcome_contract": {"type": "object"},
            },
            "required": ["action", "summary", "comment", "execution_outcome_contract"],
        },
        preferred_thread_id=None,
        env=None,
        run_cwd=None,
    )

    assert final_message == structured_payload
    assert usage == {"input_tokens": 5, "cached_input_tokens": 0, "output_tokens": 7}
    assert session_id == "ses-2"
    assert resume_attempted is False
    assert resume_succeeded is False


def test_run_opencode_cli_parses_embedded_json_line_with_prefix(monkeypatch):
    from features.agents import codex_mcp_adapter as adapter_module

    structured_payload = (
        '{"action":"comment","summary":"ok","comment":null,'
        + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
        + "}"
    )
    raw_lines = [
        'Database migration complete. {"type":"step_start","sessionID":"ses-3"}\n',
        f'noise before json {{"type":"result","result":{{"text":{json.dumps(structured_payload)}}}}}\n',
        '{"type":"step_finish","part":{"tokens":{"input":9,"output":4}}}\n',
    ]

    class _FakeProc:
        def __init__(self, output_lines):
            self.stdout = output_lines

        def poll(self):
            return None

        def kill(self):
            return None

        def wait(self):
            return 0

    monkeypatch.setattr(
        adapter_module.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeProc(raw_lines),
    )

    final_message, usage, session_id, resume_attempted, resume_succeeded = adapter_module._run_opencode_cli_with_optional_stream(
        start_prompt="hello",
        resume_prompt=None,
        timeout_seconds=None,
        stream_events=False,
        model="opencode/gpt-5-nano",
        reasoning_effort=None,
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {"type": "string"},
                "summary": {"type": "string"},
                "comment": {"type": ["string", "null"]},
                "execution_outcome_contract": {"type": "object"},
            },
            "required": ["action", "summary", "comment", "execution_outcome_contract"],
        },
        preferred_thread_id=None,
        env=None,
        run_cwd=None,
    )

    assert final_message == structured_payload
    assert usage == {"input_tokens": 9, "cached_input_tokens": 0, "output_tokens": 4}
    assert session_id == "ses-3"
    assert resume_attempted is False
    assert resume_succeeded is False


def test_run_opencode_cli_parses_multiple_json_objects_from_single_line(monkeypatch):
    from features.agents import codex_mcp_adapter as adapter_module

    structured_payload = (
        '{"action":"comment","summary":"ok","comment":null,'
        + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
        + "}"
    )
    merged_line = (
        '{"type":"step_start","sessionID":"ses-4"}'
        + json.dumps({"type": "result", "result": {"text": structured_payload}})
        + '{"type":"step_finish","part":{"tokens":{"input":4,"output":2}}}\n'
    )

    class _FakeProc:
        def __init__(self, output_lines):
            self.stdout = output_lines

        def poll(self):
            return None

        def kill(self):
            return None

        def wait(self):
            return 0

    monkeypatch.setattr(
        adapter_module.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeProc([merged_line]),
    )

    final_message, usage, session_id, resume_attempted, resume_succeeded = adapter_module._run_opencode_cli_with_optional_stream(
        start_prompt="hello",
        resume_prompt=None,
        timeout_seconds=None,
        stream_events=False,
        model="opencode/gpt-5-nano",
        reasoning_effort=None,
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {"type": "string"},
                "summary": {"type": "string"},
                "comment": {"type": ["string", "null"]},
                "execution_outcome_contract": {"type": "object"},
            },
            "required": ["action", "summary", "comment", "execution_outcome_contract"],
        },
        preferred_thread_id=None,
        env=None,
        run_cwd=None,
    )

    assert final_message == structured_payload
    assert usage == {"input_tokens": 4, "cached_input_tokens": 0, "output_tokens": 2}
    assert session_id == "ses-4"
    assert resume_attempted is False
    assert resume_succeeded is False


def test_try_parse_structured_reply_text_handles_noisy_multi_json_payload():
    from features.agents.codex_mcp_adapter import _try_parse_structured_reply_text

    noisy = (
        "startup logs... "
        '{"type":"step_start","sessionID":"ses-x"}'
        '{"action":"comment","summary":"ok","comment":null,'
        + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
        + "}"
    )
    parsed = _try_parse_structured_reply_text(noisy)

    assert isinstance(parsed, dict)
    assert parsed.get("summary") == "ok"
    assert parsed.get("action") == "comment"


def test_run_opencode_cli_uses_stdout_structured_fallback_when_events_missing(monkeypatch):
    from features.agents import codex_mcp_adapter as adapter_module

    structured_payload = (
        '{"action":"comment","summary":"fallback-ok","comment":null,'
        + _MIN_EXECUTION_OUTCOME_CONTRACT_JSON
        + "}"
    )
    raw_lines = [
        "Performing one time database migration, may take a few minutes...\n",
        "sqlite-migration:done\n",
        f"Database migration complete. {structured_payload}\n",
    ]

    class _FakeProc:
        def __init__(self, output_lines):
            self.stdout = output_lines

        def poll(self):
            return None

        def kill(self):
            return None

        def wait(self):
            return 0

    monkeypatch.setattr(
        adapter_module.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeProc(raw_lines),
    )

    final_message, usage, session_id, resume_attempted, resume_succeeded = adapter_module._run_opencode_cli_with_optional_stream(
        start_prompt="hello",
        resume_prompt=None,
        timeout_seconds=None,
        stream_events=False,
        model="opencode/gpt-5-nano",
        reasoning_effort=None,
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {"type": "string"},
                "summary": {"type": "string"},
                "comment": {"type": ["string", "null"]},
                "execution_outcome_contract": {"type": "object"},
            },
            "required": ["action", "summary", "comment", "execution_outcome_contract"],
        },
        preferred_thread_id=None,
        env=None,
        run_cwd=None,
    )

    parsed = json.loads(final_message)
    assert parsed["summary"] == "fallback-ok"
    assert usage is None
    assert session_id is None
    assert resume_attempted is False
    assert resume_succeeded is False


def test_structured_response_selection_for_stream_modes() -> None:
    from features.agents.codex_mcp_adapter import _should_use_structured_response

    assert _should_use_structured_response(provider="opencode", stream_events=True, stream_plain_text=True) is True
    assert _should_use_structured_response(provider="codex", stream_events=True, stream_plain_text=True) is False
    assert _should_use_structured_response(provider="codex", stream_events=False, stream_plain_text=True) is True
    assert _should_use_structured_response(provider="claude", stream_events=True, stream_plain_text=False) is True


def test_opencode_streaming_structured_mode_disables_plain_text_deltas(monkeypatch):
    from features.agents import codex_mcp_adapter as adapter_module

    captured_stream_plain_text: list[bool] = []
    emitted_events: list[dict[str, object]] = []

    def _fake_run_opencode_server_stream_once(*, stream_plain_text: bool, **kwargs):
        captured_stream_plain_text.append(bool(stream_plain_text))
        _ = kwargs
        return (
            json.dumps(
                {
                    "action": "comment",
                    "summary": "Safe summary",
                    "comment": "Safe comment",
                    "execution_outcome_contract": {
                        "contract_version": 1,
                        "files_changed": [],
                        "commit_sha": None,
                        "branch": None,
                        "tests_run": False,
                        "tests_passed": False,
                        "artifacts": [],
                    },
                }
            ),
            {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1},
            "ses-1",
        )

    monkeypatch.setattr(adapter_module, "_run_opencode_server_stream_once", _fake_run_opencode_server_stream_once)
    monkeypatch.setattr(adapter_module, "_emit_stream_event", lambda event: emitted_events.append(dict(event)))

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["action", "summary"],
    }
    final_message, usage, session_id, resume_attempted, resume_succeeded = adapter_module._run_opencode_cli_with_optional_stream(
        start_prompt="hello",
        resume_prompt=None,
        timeout_seconds=5.0,
        stream_events=True,
        model="opencode/gpt-5-nano",
        reasoning_effort=None,
        output_schema=schema,
        preferred_thread_id=None,
        env=None,
        run_cwd=None,
    )

    assert captured_stream_plain_text == [False]
    assert final_message
    assert usage == {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1}
    assert session_id == "ses-1"
    assert resume_attempted is False
    assert resume_succeeded is False
    assert not any(str(item.get("type") or "") == "assistant_text" for item in emitted_events)
    assert any(str(item.get("type") or "") == "usage" for item in emitted_events)
