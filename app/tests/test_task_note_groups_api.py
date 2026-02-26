from __future__ import annotations

from importlib import reload
from pathlib import Path

from fastapi.testclient import TestClient


def build_client(tmp_path: Path) -> TestClient:
    import os

    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    import main

    main = reload(main)
    main.bootstrap_data()
    client = TestClient(main.app)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert login.status_code == 200
    return client


def test_task_group_assignment_filter_and_delete_unassign(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    group = client.post(
        "/api/task-groups",
        json={"workspace_id": ws_id, "project_id": project_id, "name": "Sprint backlog", "color": "#228B22"},
    )
    assert group.status_code == 200
    group_payload = group.json()
    assert group_payload["name"] == "Sprint backlog"

    task = client.post(
        "/api/tasks",
        json={
            "title": "Grouped task",
            "workspace_id": ws_id,
            "project_id": project_id,
            "task_group_id": group_payload["id"],
        },
    )
    assert task.status_code == 200
    task_payload = task.json()
    assert task_payload["task_group_id"] == group_payload["id"]

    filtered = client.get(
        f"/api/tasks?workspace_id={ws_id}&project_id={project_id}&task_group_id={group_payload['id']}"
    )
    assert filtered.status_code == 200
    assert any(item["id"] == task_payload["id"] for item in filtered.json()["items"])

    deleted = client.post(f"/api/task-groups/{group_payload['id']}/delete")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    after_delete = client.get(f"/api/tasks?workspace_id={ws_id}&project_id={project_id}&q=Grouped task")
    assert after_delete.status_code == 200
    items = after_delete.json()["items"]
    assert items
    assert items[0]["task_group_id"] is None



def test_note_group_assignment_filter_and_delete_unassign(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    group = client.post(
        "/api/note-groups",
        json={"workspace_id": ws_id, "project_id": project_id, "name": "Research", "color": "#0055AA"},
    )
    assert group.status_code == 200
    group_payload = group.json()

    note = client.post(
        "/api/notes",
        json={
            "title": "Grouped note",
            "workspace_id": ws_id,
            "project_id": project_id,
            "note_group_id": group_payload["id"],
        },
    )
    assert note.status_code == 200
    note_payload = note.json()
    assert note_payload["note_group_id"] == group_payload["id"]

    filtered = client.get(
        f"/api/notes?workspace_id={ws_id}&project_id={project_id}&note_group_id={group_payload['id']}"
    )
    assert filtered.status_code == 200
    assert any(item["id"] == note_payload["id"] for item in filtered.json()["items"])

    deleted = client.post(f"/api/note-groups/{group_payload['id']}/delete")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    after_delete = client.get(f"/api/notes?workspace_id={ws_id}&project_id={project_id}&q=Grouped note")
    assert after_delete.status_code == 200
    items = after_delete.json()["items"]
    assert items
    assert items[0]["note_group_id"] is None



def test_group_scope_validation_across_projects(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_a = bootstrap["projects"][0]["id"]

    project_b = client.post("/api/projects", json={"workspace_id": ws_id, "name": "Second project"})
    assert project_b.status_code == 200
    project_b_id = project_b.json()["id"]

    task_group = client.post(
        "/api/task-groups",
        json={"workspace_id": ws_id, "project_id": project_a, "name": "A tasks"},
    )
    assert task_group.status_code == 200
    task_group_id = task_group.json()["id"]

    task_invalid = client.post(
        "/api/tasks",
        json={
            "title": "Wrong group scope",
            "workspace_id": ws_id,
            "project_id": project_b_id,
            "task_group_id": task_group_id,
        },
    )
    assert task_invalid.status_code == 400
    assert "does not belong to project" in task_invalid.text

    note_group = client.post(
        "/api/note-groups",
        json={"workspace_id": ws_id, "project_id": project_a, "name": "A notes"},
    )
    assert note_group.status_code == 200
    note_group_id = note_group.json()["id"]

    note_invalid = client.post(
        "/api/notes",
        json={
            "title": "Wrong note group scope",
            "workspace_id": ws_id,
            "project_id": project_b_id,
            "note_group_id": note_group_id,
        },
    )
    assert note_invalid.status_code == 400
    assert "does not belong to project" in note_invalid.text



def test_reorder_task_and_note_groups(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    task_group_ids: list[str] = []
    for name in ["One", "Two", "Three"]:
        created = client.post("/api/task-groups", json={"workspace_id": ws_id, "project_id": project_id, "name": name})
        assert created.status_code == 200
        task_group_ids.append(created.json()["id"])

    reordered_task_ids = [task_group_ids[2], task_group_ids[0], task_group_ids[1]]
    reorder_tasks = client.post(
        f"/api/task-groups/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": reordered_task_ids},
        headers={"X-Command-Id": "123e4567-e89b-12d3-a456-426614174000"},
    )
    assert reorder_tasks.status_code == 200
    assert reorder_tasks.json()["updated"] == 3

    listed_task_groups = client.get(f"/api/task-groups?workspace_id={ws_id}&project_id={project_id}")
    assert listed_task_groups.status_code == 200
    listed_task_ids = [item["id"] for item in listed_task_groups.json()["items"]]
    assert listed_task_ids[:3] == reordered_task_ids

    note_group_ids: list[str] = []
    for name in ["Alpha", "Beta", "Gamma"]:
        created = client.post("/api/note-groups", json={"workspace_id": ws_id, "project_id": project_id, "name": name})
        assert created.status_code == 200
        note_group_ids.append(created.json()["id"])

    reordered_note_ids = [note_group_ids[1], note_group_ids[2], note_group_ids[0]]
    reorder_notes = client.post(
        f"/api/note-groups/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": reordered_note_ids},
        headers={"X-Command-Id": "223e4567-e89b-12d3-a456-426614174000"},
    )
    assert reorder_notes.status_code == 200
    assert reorder_notes.json()["updated"] == 3

    listed_note_groups = client.get(f"/api/note-groups?workspace_id={ws_id}&project_id={project_id}")
    assert listed_note_groups.status_code == 200
    listed_note_ids = [item["id"] for item in listed_note_groups.json()["items"]]
    assert listed_note_ids[:3] == reordered_note_ids
