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


def test_specification_crud_and_filters(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    created = client.post(
        "/api/specifications",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Auth v2",
            "body": "Detailed specification",
            "status": "Draft",
        },
    )
    assert created.status_code == 200
    spec = created.json()
    assert spec["title"] == "Auth v2"
    assert spec["status"] == "Draft"

    listed = client.get(f"/api/specifications?workspace_id={ws_id}&project_id={project_id}&q=Auth")
    assert listed.status_code == 200
    assert any(item["id"] == spec["id"] for item in listed.json()["items"])

    patched = client.patch(
        f"/api/specifications/{spec['id']}",
        json={"status": "Ready", "body": "Updated body"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "Ready"

    archived = client.post(f"/api/specifications/{spec['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["ok"] is True

    archived_list = client.get(f"/api/specifications?workspace_id={ws_id}&project_id={project_id}&archived=true")
    assert archived_list.status_code == 200
    assert any(item["id"] == spec["id"] for item in archived_list.json()["items"])

    restored = client.post(f"/api/specifications/{spec['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["ok"] is True


def test_task_and_note_can_link_to_specification(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    spec = client.post(
        "/api/specifications",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Billing spec",
            "status": "Ready",
        },
    ).json()

    task = client.post(
        "/api/tasks",
        json={
            "title": "Implement billing api",
            "workspace_id": ws_id,
            "project_id": project_id,
            "specification_id": spec["id"],
        },
    )
    assert task.status_code == 200
    task_payload = task.json()
    assert task_payload["specification_id"] == spec["id"]

    note = client.post(
        "/api/notes",
        json={
            "title": "Spec notes",
            "workspace_id": ws_id,
            "project_id": project_id,
            "specification_id": spec["id"],
        },
    )
    assert note.status_code == 200
    note_payload = note.json()
    assert note_payload["specification_id"] == spec["id"]

    tasks_filtered = client.get(f"/api/tasks?workspace_id={ws_id}&project_id={project_id}&specification_id={spec['id']}")
    assert tasks_filtered.status_code == 200
    assert any(item["id"] == task_payload["id"] for item in tasks_filtered.json()["items"])

    notes_filtered = client.get(f"/api/notes?workspace_id={ws_id}&project_id={project_id}&specification_id={spec['id']}")
    assert notes_filtered.status_code == 200
    assert any(item["id"] == note_payload["id"] for item in notes_filtered.json()["items"])


def test_cannot_link_task_to_specification_from_other_project(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_a = bootstrap["projects"][0]["id"]

    project_b = client.post("/api/projects", json={"workspace_id": ws_id, "name": "Second"}).json()["id"]
    spec_b = client.post(
        "/api/specifications",
        json={"workspace_id": ws_id, "project_id": project_b, "title": "Spec B", "status": "Ready"},
    ).json()

    bad = client.post(
        "/api/tasks",
        json={
            "title": "Wrong link",
            "workspace_id": ws_id,
            "project_id": project_a,
            "specification_id": spec_b["id"],
        },
    )
    assert bad.status_code == 400


def test_delete_project_deletes_specifications(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]

    project = client.post("/api/projects", json={"workspace_id": ws_id, "name": "Spec scoped"}).json()
    spec = client.post(
        "/api/specifications",
        json={"workspace_id": ws_id, "project_id": project["id"], "title": "Spec to delete", "status": "Ready"},
    ).json()

    deleted = client.delete(f"/api/projects/{project['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    missing = client.get(f"/api/specifications/{spec['id']}")
    assert missing.status_code == 404
