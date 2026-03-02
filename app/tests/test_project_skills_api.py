from __future__ import annotations

import json
import os
from importlib import reload
from pathlib import Path

import httpx
from fastapi.testclient import TestClient


def build_client(tmp_path: Path) -> TestClient:
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    import main

    main = reload(main)
    main.bootstrap_data()
    client = TestClient(main.app)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert login.status_code == 200
    return client


def _mock_skill_response(monkeypatch, *, body: str):
    from features.project_skills import application as skill_app

    def fake_get(url, timeout, follow_redirects, headers):  # noqa: ANN001, A002
        _ = (url, timeout, follow_redirects, headers)
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/markdown"},
            text=body,
        )

    monkeypatch.setattr(skill_app.httpx, "get", fake_get)


def test_project_skill_import_crud_flow(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    _mock_skill_response(
        monkeypatch,
        body="# Python Testing Skill\nAlways add tests for changed behavior.",
    )

    imported = client.post(
        "/api/project-skills/import",
        json={
            "workspace_id": workspace_id,
            "project_id": project_id,
            "source_url": "https://example.com/skills/python-testing.md",
            "skill_key": "python_testing",
            "mode": "advisory",
            "trust_level": "reviewed",
        },
    )
    assert imported.status_code == 200
    skill = imported.json()
    assert skill["project_id"] == project_id
    assert skill["skill_key"] == "python_testing"
    assert skill["already_exists"] is False
    assert skill["generated_rule_id"] is None

    applied = client.post(f"/api/project-skills/{skill['id']}/apply")
    assert applied.status_code == 200
    applied_payload = applied.json()
    assert isinstance(applied_payload["generated_rule_id"], str) and applied_payload["generated_rule_id"]

    created_rule = client.get(f"/api/project-rules/{applied_payload['generated_rule_id']}")
    assert created_rule.status_code == 200
    created_rule_payload = created_rule.json()
    assert "Imported skill context:" in created_rule_payload["body"]
    assert "Always add tests for changed behavior." in created_rule_payload["body"]

    listed = client.get(f"/api/project-skills?workspace_id={workspace_id}&project_id={project_id}")
    assert listed.status_code == 200
    assert any(item["id"] == skill["id"] for item in listed.json()["items"])

    fetched = client.get(f"/api/project-skills/{skill['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == skill["id"]

    patched = client.patch(
        f"/api/project-skills/{skill['id']}",
        json={
            "name": "Python Testing Skill v2",
            "mode": "enforced",
            "trust_level": "verified",
            "summary": "Enforced quality baseline for tests.",
            "content": "# Python Testing Skill v2\nAlways add regression tests and smoke checks.",
        },
    )
    assert patched.status_code == 200
    patched_payload = patched.json()
    assert patched_payload["name"] == "Python Testing Skill v2"
    assert patched_payload["mode"] == "enforced"
    assert patched_payload["trust_level"] == "verified"
    assert patched_payload["summary"] == "Enforced quality baseline for tests."
    assert (
        str(patched_payload["manifest"].get("source_content", "")).strip()
        == "# Python Testing Skill v2\nAlways add regression tests and smoke checks."
    )

    synced_rule = client.get(f"/api/project-rules/{applied_payload['generated_rule_id']}")
    assert synced_rule.status_code == 200
    synced_rule_payload = synced_rule.json()
    assert synced_rule_payload["title"] == "Skill: Python Testing Skill v2"
    assert "- Mode: enforced" in synced_rule_payload["body"]
    assert "- Trust level: verified" in synced_rule_payload["body"]
    assert "Always add regression tests and smoke checks." in synced_rule_payload["body"]

    deleted = client.post(
        f"/api/project-skills/{skill['id']}/delete",
        json={"delete_linked_rule": True},
    )
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    missing_skill = client.get(f"/api/project-skills/{skill['id']}")
    assert missing_skill.status_code == 404
    missing_rule = client.get(f"/api/project-rules/{applied_payload['generated_rule_id']}")
    assert missing_rule.status_code == 404


def test_project_skill_reimport_with_same_source_and_key_refreshes_existing(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    _mock_skill_response(monkeypatch, body="# API Skill\nUse strict API contracts.")
    payload = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "source_url": "https://example.com/skills/api-contracts.md",
        "skill_key": "api_contracts",
    }

    first = client.post("/api/project-skills/import", json=payload)
    assert first.status_code == 200
    second = client.post("/api/project-skills/import", json=payload)
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["already_exists"] is False
    assert second.json()["updated_existing"] is True


def test_project_skill_reimport_updates_existing(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    from features.project_skills import application as skill_app

    responses = iter(
        [
            "# API Skill\nUse strict API contracts.",
            "# API Skill\nUpdated behavior summary.",
        ]
    )

    def fake_get(url, timeout, follow_redirects, headers):  # noqa: ANN001, A002
        _ = (url, timeout, follow_redirects, headers)
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/markdown"},
            text=next(responses),
        )

    monkeypatch.setattr(skill_app.httpx, "get", fake_get)

    payload = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "source_url": "https://example.com/skills/api-contracts.md",
        "skill_key": "api_contracts",
    }
    first = client.post("/api/project-skills/import", json=payload)
    assert first.status_code == 200
    first_payload = first.json()
    applied_first = client.post(f"/api/project-skills/{first_payload['id']}/apply")
    assert applied_first.status_code == 200
    first_rule_id = str(applied_first.json()["generated_rule_id"])
    assert first_rule_id

    second = client.post(
        "/api/project-skills/import",
        json=payload,
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["id"] == first_payload["id"]
    assert second_payload["already_exists"] is False
    assert second_payload["updated_existing"] is True
    assert second_payload["summary"] == "Updated behavior summary."
    assert str(second_payload["generated_rule_id"] or "") == first_rule_id

    generated_rule = client.get(f"/api/project-rules/{first_rule_id}")
    assert generated_rule.status_code == 200
    generated_rule_payload = generated_rule.json()
    assert "Updated behavior summary." in generated_rule_payload["body"]


def test_project_skill_import_from_file(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    imported = client.post(
        "/api/project-skills/import-file",
        data={
            "workspace_id": workspace_id,
            "project_id": project_id,
            "skill_key": "file_import_skill",
            "mode": "advisory",
            "trust_level": "reviewed",
        },
        files={
            "file": (
                "file-import-skill.md",
                b"# File Import Skill\nAlways validate file payload structure before processing.",
                "text/markdown",
            )
        },
    )
    assert imported.status_code == 200
    payload = imported.json()
    assert payload["project_id"] == project_id
    assert payload["source_type"] == "file"
    assert payload["skill_key"] == "file_import_skill"
    assert payload["summary"] == "Always validate file payload structure before processing."
    assert str(payload["source_locator"]).startswith("upload://")
    assert payload["already_exists"] is False
    assert payload["generated_rule_id"] is None

    applied = client.post(f"/api/project-skills/{payload['id']}/apply")
    assert applied.status_code == 200
    applied_payload = applied.json()
    assert isinstance(applied_payload["generated_rule_id"], str) and applied_payload["generated_rule_id"]

    generated_rule = client.get(f"/api/project-rules/{applied_payload['generated_rule_id']}")
    assert generated_rule.status_code == 200
    generated_rule_payload = generated_rule.json()
    assert "Imported skill context:" in generated_rule_payload["body"]
    assert "Always validate file payload structure before processing." in generated_rule_payload["body"]


def test_project_skill_import_from_file_updates_existing_when_requested(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    import_payload = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "skill_key": "file_update_skill",
        "mode": "advisory",
        "trust_level": "reviewed",
    }

    first = client.post(
        "/api/project-skills/import-file",
        data=import_payload,
        files={
            "file": (
                "SKILL.md",
                b"# File Update Skill\nInitial import content.",
                "text/markdown",
            )
        },
    )
    assert first.status_code == 200
    first_payload = first.json()
    applied_first = client.post(f"/api/project-skills/{first_payload['id']}/apply")
    assert applied_first.status_code == 200
    first_rule_id = str(applied_first.json()["generated_rule_id"])
    assert first_rule_id

    second = client.post(
        "/api/project-skills/import-file",
        data=import_payload,
        files={
            "file": (
                "SKILL.md",
                b"# File Update Skill\nUpdated file import content.",
                "text/markdown",
            )
        },
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["id"] == first_payload["id"]
    assert second_payload["already_exists"] is False
    assert second_payload["updated_existing"] is True
    assert second_payload["summary"] == "Updated file import content."
    assert str(second_payload["generated_rule_id"] or "") == first_rule_id

    generated_rule = client.get(f"/api/project-rules/{first_rule_id}")
    assert generated_rule.status_code == 200
    generated_rule_payload = generated_rule.json()
    assert "Updated file import content." in generated_rule_payload["body"]


def test_project_skill_reimport_from_file_after_delete_restores_skill(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    import_payload = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "skill_key": "file_restore_skill",
        "mode": "advisory",
        "trust_level": "reviewed",
    }
    import_files = {
        "file": (
            "SKILL.md",
            b"# File Restore Skill\nUse this for restore-path verification.",
            "text/markdown",
        )
    }

    first = client.post("/api/project-skills/import-file", data=import_payload, files=import_files)
    assert first.status_code == 200
    first_payload = first.json()
    first_skill_id = str(first_payload["id"])
    applied_first = client.post(f"/api/project-skills/{first_skill_id}/apply")
    assert applied_first.status_code == 200
    first_rule_id = str(applied_first.json()["generated_rule_id"])
    assert first_rule_id

    deleted = client.post(
        f"/api/project-skills/{first_skill_id}/delete",
        json={"delete_linked_rule": True},
    )
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    second = client.post("/api/project-skills/import-file", data=import_payload, files=import_files)
    assert second.status_code == 200
    second_payload = second.json()
    assert str(second_payload["id"]) == first_skill_id
    assert second_payload["already_exists"] is False
    assert second_payload["generated_rule_id"] is None

    applied_second = client.post(f"/api/project-skills/{first_skill_id}/apply")
    assert applied_second.status_code == 200
    second_rule_id = str(applied_second.json()["generated_rule_id"])
    assert second_rule_id

    if second_rule_id != first_rule_id:
        deleted_rule = client.get(f"/api/project-rules/{first_rule_id}")
        assert deleted_rule.status_code == 404
    active_rule = client.get(f"/api/project-rules/{second_rule_id}")
    assert active_rule.status_code == 200


def test_project_skill_import_uses_frontmatter_description_as_summary(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    _mock_skill_response(
        monkeypatch,
        body=(
            "---\n"
            "name: pdf\n"
            "description: Use this skill whenever the user needs to work with PDF files.\n"
            "---\n\n"
            "# PDF Processing Guide\n\n"
            "## Overview\n\n"
            "This guide covers essential PDF operations.\n"
        ),
    )

    imported = client.post(
        "/api/project-skills/import",
        json={
            "workspace_id": workspace_id,
            "project_id": project_id,
            "source_url": "https://example.com/skills/pdf.md",
            "skill_key": "pdf_skill",
        },
    )
    assert imported.status_code == 200
    payload = imported.json()
    assert payload["summary"] == "Use this skill whenever the user needs to work with PDF files."
    assert payload["name"] == "PDF Processing Guide"


def test_project_skill_patch_rejects_enabled_field(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    _mock_skill_response(monkeypatch, body="# API Skill\nUse strict API contracts.")
    imported = client.post(
        "/api/project-skills/import",
        json={
            "workspace_id": workspace_id,
            "project_id": project_id,
            "source_url": "https://example.com/skills/api-contracts.md",
            "skill_key": "api_contracts",
        },
    )
    assert imported.status_code == 200
    skill_id = imported.json()["id"]

    patched = client.patch(
        f"/api/project-skills/{skill_id}",
        json={"enabled": False},
    )
    assert patched.status_code == 422
    assert "enabled" in str(patched.json().get("detail", ""))


def test_project_skill_import_normalizes_github_blob_source_url(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    from features.project_skills import application as skill_app

    captured: dict[str, str] = {}

    def fake_get(url, timeout, follow_redirects, headers):  # noqa: ANN001, A002
        _ = (timeout, follow_redirects, headers)
        captured["url"] = str(url)
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/markdown"},
            text="# GitHub Blob Skill\nUse strict review checklists.",
        )

    monkeypatch.setattr(skill_app.httpx, "get", fake_get)

    requested_url = "https://github.com/acme/example-repo/blob/main/skills/blob-skill.md"
    imported = client.post(
        "/api/project-skills/import",
        json={
            "workspace_id": workspace_id,
            "project_id": project_id,
            "source_url": requested_url,
            "skill_key": "blob_skill",
        },
    )
    assert imported.status_code == 200
    payload = imported.json()
    expected_raw_url = "https://raw.githubusercontent.com/acme/example-repo/main/skills/blob-skill.md"
    assert captured["url"] == expected_raw_url
    assert payload["source_locator"] == expected_raw_url
    assert payload["manifest"]["requested_source_url"] == requested_url
    assert payload["manifest"]["source_url"] == expected_raw_url


def test_workspace_skill_catalog_seed_and_attach_to_project(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    catalog = client.get(f"/api/workspace-skills?workspace_id={workspace_id}")
    assert catalog.status_code == 200
    items = catalog.json()["items"]
    assert any(item["skill_key"] == "git_delivery" for item in items)
    assert any(item["skill_key"] == "github_delivery" for item in items)
    assert any(item["skill_key"] == "jira_execution" for item in items)
    assert any(item["skill_key"] == "team_mode" for item in items)

    github_skill = next(item for item in items if item["skill_key"] == "github_delivery")
    assert github_skill["source_locator"] == "seed://workspace-skills/github-delivery"
    assert github_skill["is_seeded"] is True
    github_content = str(github_skill["manifest"].get("source_content", ""))
    assert "Core Git execution rules are enforced by `git_delivery`." in github_content

    jira_skill = next(item for item in items if item["skill_key"] == "jira_execution")
    assert jira_skill["source_locator"] == "seed://workspace-skills/jira-execution"
    assert jira_skill["is_seeded"] is True
    jira_content = str(jira_skill["manifest"].get("source_content", ""))
    assert "create one Jira snapshot issue per app task" in jira_content

    team_mode_skill = next(item for item in items if item["skill_key"] == "team_mode")
    assert team_mode_skill["source_locator"] == "seed://workspace-skills/team-mode"
    assert team_mode_skill["is_seeded"] is True
    assert team_mode_skill["mode"] == "enforced"
    team_mode_content = str(team_mode_skill["manifest"].get("source_content", ""))
    assert "M0rph3u5" in team_mode_content
    assert "0r4cl3" in team_mode_content

    attached = client.post(
        f"/api/workspace-skills/{github_skill['id']}/attach",
        json={"workspace_id": workspace_id, "project_id": project_id},
    )
    assert attached.status_code == 200
    attached_payload = attached.json()
    assert attached_payload["project_id"] == project_id
    assert attached_payload["skill_key"] == "github_delivery"
    assert attached_payload["generated_rule_id"] is None
    assert attached_payload["attached_from_workspace_skill_id"] == github_skill["id"]
    dependency = attached_payload.get("git_delivery_dependency") or {}
    assert dependency.get("project_skill_id")

    project_skills = client.get(f"/api/project-skills?workspace_id={workspace_id}&project_id={project_id}")
    assert project_skills.status_code == 200
    project_skill_keys = {item["skill_key"] for item in project_skills.json()["items"]}
    assert "github_delivery" in project_skill_keys
    assert "git_delivery" in project_skill_keys

    github_project_skill_id = next(
        item["id"] for item in project_skills.json()["items"] if item["skill_key"] == "github_delivery"
    )
    applied = client.post(f"/api/project-skills/{github_project_skill_id}/apply")
    assert applied.status_code == 200
    apply_payload = applied.json()
    apply_dependency = apply_payload.get("git_delivery_dependency") or {}
    assert apply_dependency.get("project_skill_id")
    assert apply_dependency.get("applied") is True


def test_apply_team_mode_skill_ensures_agent_users_and_project_roles(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    catalog = client.get(f"/api/workspace-skills?workspace_id={workspace_id}")
    assert catalog.status_code == 200
    team_mode_skill = next(item for item in catalog.json()["items"] if item["skill_key"] == "team_mode")

    attached = client.post(
        f"/api/workspace-skills/{team_mode_skill['id']}/attach",
        json={"workspace_id": workspace_id, "project_id": project_id},
    )
    assert attached.status_code == 200
    attached_payload = attached.json()
    assert attached_payload["skill_key"] == "team_mode"

    applied = client.post(f"/api/project-skills/{attached_payload['id']}/apply")
    assert applied.status_code == 200
    applied_payload = applied.json()
    assert isinstance(applied_payload["generated_rule_id"], str) and applied_payload["generated_rule_id"]
    assert isinstance(applied_payload.get("gate_policy_rule_id"), str) and applied_payload["gate_policy_rule_id"]
    assert applied_payload["team_mode_contract_complete"] is True
    team_dependencies = applied_payload.get("resolved_dependencies") or []
    git_dependency = next((item for item in team_dependencies if item.get("skill_key") == "git_delivery"), None)
    assert git_dependency is not None
    assert git_dependency.get("project_skill_id")
    assert git_dependency.get("applied") is True
    roster = applied_payload["team_mode_roster"]
    assert isinstance(roster, list) and len(roster) == 4
    roster_by_username = {str(item["username"]): item for item in roster}
    assert roster_by_username["agent.m0rph3u5"]["project_member_role"] == "TeamLeadAgent"
    assert roster_by_username["agent.tr1n1ty"]["project_member_role"] == "DeveloperAgent"
    assert roster_by_username["agent.n30"]["project_member_role"] == "DeveloperAgent"
    assert roster_by_username["agent.0r4cl3"]["project_member_role"] == "QAAgent"
    assert all(bool(item.get("user_id")) for item in roster)

    members = client.get(f"/api/projects/{project_id}/members")
    assert members.status_code == 200
    items = members.json()["items"]
    by_username = {str(item["user"]["username"]): item for item in items}

    expected = {
        "agent.m0rph3u5": "TeamLeadAgent",
        "agent.tr1n1ty": "DeveloperAgent",
        "agent.n30": "DeveloperAgent",
        "agent.0r4cl3": "QAAgent",
    }
    for username, expected_role in expected.items():
        assert username in by_username
        assert by_username[username]["role"] == expected_role
        assert by_username[username]["user"]["user_type"] == "agent"

    applied_again = client.post(f"/api/project-skills/{attached_payload['id']}/apply")
    assert applied_again.status_code == 200

    project_skills = client.get(f"/api/project-skills?workspace_id={workspace_id}&project_id={project_id}")
    assert project_skills.status_code == 200
    skill_by_key = {item["skill_key"]: item for item in project_skills.json()["items"]}
    assert "team_mode" in skill_by_key
    assert "git_delivery" in skill_by_key
    team_rule_id = str(skill_by_key["team_mode"].get("generated_rule_id") or "").strip()
    git_rule_id = str(skill_by_key["git_delivery"].get("generated_rule_id") or "").strip()
    assert team_rule_id
    assert git_rule_id
    assert team_rule_id != git_rule_id
    project_rules = client.get(f"/api/project-rules?workspace_id={workspace_id}&project_id={project_id}")
    assert project_rules.status_code == 200
    gate_rules = [
        item
        for item in project_rules.json()["items"]
        if "gate policy" in str(item.get("title") or "").strip().lower()
    ]
    assert len(gate_rules) == 1
    gate_rule = gate_rules[0]
    assert str(gate_rule.get("id") or "").strip() == str(applied_payload.get("gate_policy_rule_id") or "").strip()
    assert "```json" in str(gate_rule.get("body") or "")
    assert "required_checks" in str(gate_rule.get("body") or "")

    members_again = client.get(f"/api/projects/{project_id}/members")
    assert members_again.status_code == 200
    items_again = members_again.json()["items"]
    for username, expected_role in expected.items():
        matches = [item for item in items_again if str(item["user"]["username"]) == username]
        assert len(matches) == 1
        assert matches[0]["role"] == expected_role


def test_team_mode_runner_attributes_automation_events_to_assigned_agent(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    catalog = client.get(f"/api/workspace-skills?workspace_id={workspace_id}")
    assert catalog.status_code == 200
    team_mode_skill = next(item for item in catalog.json()["items"] if item["skill_key"] == "team_mode")

    attached = client.post(
        f"/api/workspace-skills/{team_mode_skill['id']}/attach",
        json={"workspace_id": workspace_id, "project_id": project_id},
    )
    assert attached.status_code == 200
    skill_id = attached.json()["id"]
    applied = client.post(f"/api/project-skills/{skill_id}/apply")
    assert applied.status_code == 200

    members = client.get(f"/api/projects/{project_id}/members")
    assert members.status_code == 200
    assignee = next(item for item in members.json()["items"] if item["user"]["username"] == "agent.tr1n1ty")
    assignee_id = str(assignee["user_id"])

    created = client.post(
        "/api/tasks",
        json={
            "title": "Team mode actor attribution",
            "workspace_id": workspace_id,
            "project_id": project_id,
            "assignee_id": assignee_id,
        },
    )
    assert created.status_code == 200
    task_id = created.json()["id"]

    queued = client.post(f"/api/tasks/{task_id}/automation/run", json={"instruction": "Leave a progress comment"})
    assert queued.status_code == 200

    from features.agents.runner import run_queued_automation_once
    from features.tasks.domain import EVENT_AUTOMATION_COMPLETED
    from shared.models import SessionLocal, StoredEvent
    from sqlalchemy import select

    processed = run_queued_automation_once(limit=5)
    assert processed >= 1

    with SessionLocal() as db:
        completion_event = db.execute(
            select(StoredEvent)
            .where(
                StoredEvent.aggregate_type == "Task",
                StoredEvent.aggregate_id == task_id,
                StoredEvent.event_type == EVENT_AUTOMATION_COMPLETED,
            )
            .order_by(StoredEvent.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        assert completion_event is not None
        meta = json.loads(completion_event.meta or "{}")
        assert meta.get("actor_id") == assignee_id


def test_workspace_skill_patch_updates_content(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]

    catalog = client.get(f"/api/workspace-skills?workspace_id={workspace_id}")
    assert catalog.status_code == 200
    github_skill = next(item for item in catalog.json()["items"] if item["skill_key"] == "github_delivery")

    patched = client.patch(
        f"/api/workspace-skills/{github_skill['id']}",
        json={
            "name": "GitHub Delivery Skill v2",
            "summary": "Updated summary for delivery workflow.",
            "mode": "enforced",
            "trust_level": "verified",
            "content": "# GitHub Delivery Skill v2\nPrefer squash merges and release tags.",
        },
    )
    assert patched.status_code == 200
    payload = patched.json()
    assert payload["name"] == "GitHub Delivery Skill v2"
    assert payload["summary"] == "Updated summary for delivery workflow."
    assert payload["mode"] == "enforced"
    assert payload["trust_level"] == "verified"
    assert str(payload["manifest"].get("source_content", "")).strip() == (
        "# GitHub Delivery Skill v2\nPrefer squash merges and release tags."
    )


def test_delete_project_soft_deletes_project_skills(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]

    project = client.post(
        "/api/projects",
        json={"workspace_id": workspace_id, "name": "Skill Cleanup"},
    ).json()

    _mock_skill_response(monkeypatch, body="# Cleanup Skill\nDelete me with project.")
    imported = client.post(
        "/api/project-skills/import",
        json={
            "workspace_id": workspace_id,
            "project_id": project["id"],
            "source_url": "https://example.com/skills/cleanup.md",
            "skill_key": "cleanup_skill",
        },
    )
    assert imported.status_code == 200
    skill_id = imported.json()["id"]

    deleted_project = client.delete(f"/api/projects/{project['id']}")
    assert deleted_project.status_code == 200
    assert deleted_project.json()["ok"] is True

    from shared.models import ProjectSkill, SessionLocal

    with SessionLocal() as db:
        skill = db.get(ProjectSkill, skill_id)
        assert skill is not None
        assert bool(skill.is_deleted) is True


def test_agent_task_service_supports_project_skill_lifecycle(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]
    user_id = bootstrap["current_user"]["id"]

    _mock_skill_response(monkeypatch, body="# MCP Skill\nWork through AgentTaskService.")

    from features.agents.service import AgentTaskService

    service = AgentTaskService(
        require_token=False,
        actor_user_id=user_id,
        allowed_workspace_ids=set(),
        allowed_project_ids=set(),
        default_workspace_id="",
    )

    imported = service.import_project_skill(
        workspace_id=workspace_id,
        project_id=project_id,
        source_url="https://example.com/skills/mcp.md",
        skill_key="mcp_skill",
    )
    assert imported["skill_key"] == "mcp_skill"
    assert imported["generated_rule_id"] is None

    applied = service.apply_project_skill(skill_id=imported["id"])
    assert isinstance(applied["generated_rule_id"], str) and applied["generated_rule_id"]

    listed = service.list_project_skills(workspace_id=workspace_id, project_id=project_id)
    assert any(item["id"] == imported["id"] for item in listed["items"])

    fetched = service.get_project_skill(skill_id=imported["id"])
    assert fetched["id"] == imported["id"]

    updated = service.update_project_skill(
        skill_id=imported["id"],
        patch={"mode": "enforced", "trust_level": "verified"},
    )
    assert updated["mode"] == "enforced"
    assert updated["trust_level"] == "verified"

    members = service.list_project_members(workspace_id=workspace_id, project_id=project_id, limit=200)
    assert isinstance(members.get("items"), list)
    assert int(members.get("total", 0)) >= 1

    deleted = service.delete_project_skill(skill_id=imported["id"])
    assert deleted["ok"] is True
