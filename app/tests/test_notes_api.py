from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def build_client(tmp_path: Path) -> TestClient:
    import os
    from importlib import reload

    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    import main

    main = reload(main)
    main.bootstrap_data()
    return TestClient(main.app)


def test_create_and_patch_note(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    created = client.post("/api/notes", json={"title": "Plan: Notes MVP", "workspace_id": ws_id, "project_id": project_id, "body": "# Hello\n\n```py\nprint('x')\n```"})
    assert created.status_code == 200
    note = created.json()
    assert note["title"] == "Plan: Notes MVP"
    assert note["workspace_id"] == ws_id
    assert "print" in note["body"]

    patched = client.patch(f"/api/notes/{note['id']}", json={"title": "Plan: Notes MVP v2", "tags": ["mvp", "notes"], "pinned": True})
    assert patched.status_code == 200
    payload = patched.json()
    assert payload["title"] == "Plan: Notes MVP v2"
    assert payload["pinned"] is True
    assert "mvp" in payload["tags"]


def test_list_notes_search_and_filters(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    client.post("/api/notes", json={"title": "Alpha", "workspace_id": ws_id, "project_id": project_id, "body": "first"})
    client.post("/api/notes", json={"title": "Beta", "workspace_id": ws_id, "project_id": project_id, "body": "second", "pinned": True})

    res = client.get(f"/api/notes?workspace_id={ws_id}&project_id={project_id}&q=Beta")
    assert res.status_code == 200
    assert any(n["title"] == "Beta" for n in res.json()["items"])

    pinned_only = client.get(f"/api/notes?workspace_id={ws_id}&project_id={project_id}&pinned=true")
    assert pinned_only.status_code == 200
    assert all(n["pinned"] is True for n in pinned_only.json()["items"])


def test_archive_and_restore_note(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    note = client.post("/api/notes", json={"title": "Archive me", "workspace_id": ws_id, "project_id": project_id}).json()
    archived = client.post(f"/api/notes/{note['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["ok"] is True

    active_list = client.get(f"/api/notes?workspace_id={ws_id}&project_id={project_id}").json()["items"]
    assert all(n["id"] != note["id"] for n in active_list)

    archived_list = client.get(f"/api/notes?workspace_id={ws_id}&project_id={project_id}&archived=true").json()["items"]
    assert any(n["id"] == note["id"] for n in archived_list)

    restored = client.post(f"/api/notes/{note['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["ok"] is True


def test_command_id_idempotency_for_create_note(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]
    command_id = "cmd-create-note-001"

    first = client.post(
        "/api/notes",
        json={"title": "Idempotent note", "workspace_id": ws_id, "project_id": project_id},
        headers={"X-Command-Id": command_id},
    )
    second = client.post(
        "/api/notes",
        json={"title": "Idempotent note", "workspace_id": ws_id, "project_id": project_id},
        headers={"X-Command-Id": command_id},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    notes = client.get(f"/api/notes?workspace_id={ws_id}&project_id={project_id}&q=Idempotent").json()["items"]
    assert len(notes) == 1


def test_create_note_requires_project_id(tmp_path: Path):
    client = build_client(tmp_path)
    ws_id = client.get("/api/bootstrap").json()["workspaces"][0]["id"]
    res = client.post("/api/notes", json={"title": "No project", "workspace_id": ws_id})
    assert res.status_code == 422


def test_note_tags_are_normalized_and_filterable(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    created = client.post(
        "/api/notes",
        json={
            "title": "Tagged note",
            "workspace_id": ws_id,
            "project_id": project_id,
            "tags": ["Review", "review", " UX "],
        },
    )
    assert created.status_code == 200
    note = created.json()
    assert note["tags"] == ["review", "ux"]

    filtered = client.get(f"/api/notes?workspace_id={ws_id}&project_id={project_id}&tags=review,ux")
    assert filtered.status_code == 200
    assert any(item["id"] == note["id"] for item in filtered.json()["items"])


def test_note_refs_roundtrip(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    created = client.post(
        "/api/notes",
        json={
            "title": "Refs note",
            "workspace_id": ws_id,
            "project_id": project_id,
            "external_refs": [{"url": "https://example.com/doc"}],
            "attachment_refs": [{"path": "/tmp/readme.md"}],
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["external_refs"][0]["url"] == "https://example.com/doc"
    assert payload["attachment_refs"][0]["path"] == "/tmp/readme.md"
