from __future__ import annotations

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
    login = client.post("/api/auth/login", json={"username": "m4tr1x", "password": "testtest"})
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
    assert isinstance(skill["generated_rule_id"], str) and skill["generated_rule_id"]

    created_rule = client.get(f"/api/project-rules/{skill['generated_rule_id']}")
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
        },
    )
    assert patched.status_code == 200
    patched_payload = patched.json()
    assert patched_payload["name"] == "Python Testing Skill v2"
    assert patched_payload["mode"] == "enforced"
    assert patched_payload["trust_level"] == "verified"
    assert patched_payload["summary"] == "Enforced quality baseline for tests."

    synced_rule = client.get(f"/api/project-rules/{skill['generated_rule_id']}")
    assert synced_rule.status_code == 200
    synced_rule_payload = synced_rule.json()
    assert synced_rule_payload["title"] == "Skill: Python Testing Skill v2"
    assert "- Mode: enforced" in synced_rule_payload["body"]
    assert "- Trust level: verified" in synced_rule_payload["body"]

    deleted = client.post(
        f"/api/project-skills/{skill['id']}/delete",
        json={"delete_linked_rule": True},
    )
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    missing_skill = client.get(f"/api/project-skills/{skill['id']}")
    assert missing_skill.status_code == 404
    missing_rule = client.get(f"/api/project-rules/{skill['generated_rule_id']}")
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

    generated_rule = client.get(f"/api/project-rules/{second_payload['generated_rule_id']}")
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
    assert isinstance(payload["generated_rule_id"], str) and payload["generated_rule_id"]

    generated_rule = client.get(f"/api/project-rules/{payload['generated_rule_id']}")
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

    generated_rule = client.get(f"/api/project-rules/{second_payload['generated_rule_id']}")
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
    first_rule_id = str(first_payload["generated_rule_id"])

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
    assert str(second_payload["generated_rule_id"])

    second_rule_id = str(second_payload["generated_rule_id"])
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

    deleted = service.delete_project_skill(skill_id=imported["id"])
    assert deleted["ok"] is True
