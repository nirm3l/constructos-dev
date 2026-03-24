from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.critical.support.runtime import build_client as build_runtime_client

def build_client(tmp_path: Path) -> TestClient:
    return build_runtime_client(tmp_path)


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


def test_create_specification_is_case_insensitive_idempotent_by_title(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    first = client.post(
        "/api/specifications",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "FK Sarajevo Spec",
            "status": "Draft",
        },
    )
    second = client.post(
        "/api/specifications",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "fk sarajevo spec",
            "status": "Ready",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    listed = client.get(f"/api/specifications?workspace_id={ws_id}&project_id={project_id}&q=fk sarajevo spec")
    assert listed.status_code == 200
    assert len([item for item in listed.json()["items"] if item["title"].strip().lower() == "fk sarajevo spec"]) == 1


def test_create_specification_returns_aggregate_fallback_when_view_unavailable(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    import features.specifications.command_handlers as specification_handlers

    monkeypatch.setattr(specification_handlers, "load_specification_view", lambda db, specification_id: None)

    created = client.post(
        "/api/specifications",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Fallback spec response",
            "body": "text",
            "status": "Draft",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["title"] == "Fallback spec response"
    assert payload["workspace_id"] == ws_id
    assert payload["project_id"] == project_id
    assert payload["status"] == "Draft"


def test_create_specification_force_new_creates_new_instance(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    first = client.post(
        "/api/specifications",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Untitled spec",
            "status": "Draft",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/api/specifications?command_id=spec-force-new-1",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Untitled spec",
            "status": "Draft",
            "force_new": True,
        },
    )
    assert second.status_code == 200
    assert first.json()["id"] != second.json()["id"]

    deleted = client.post(f"/api/specifications/{first.json()['id']}/delete")
    assert deleted.status_code == 200

    after_delete_force_new = client.post(
        "/api/specifications?command_id=spec-force-new-2",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Untitled spec",
            "status": "Draft",
            "force_new": True,
        },
    )
    assert after_delete_force_new.status_code == 200
    assert after_delete_force_new.json()["id"] not in {first.json()["id"], second.json()["id"]}


def test_specification_status_aliases_are_normalized(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    created = client.post(
        "/api/specifications",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Alias status create",
            "status": "in_progress",
        },
    )
    assert created.status_code == 200
    spec = created.json()
    assert spec["status"] == "In progress"

    patched_done = client.patch(f"/api/specifications/{spec['id']}", json={"status": "done"})
    assert patched_done.status_code == 200
    assert patched_done.json()["status"] == "Implemented"

    patched_ready = client.patch(f"/api/specifications/{spec['id']}", json={"status": "READY"})
    assert patched_ready.status_code == 200
    assert patched_ready.json()["status"] == "Ready"

    bad = client.patch(f"/api/specifications/{spec['id']}", json={"status": "something-else"})
    assert bad.status_code == 422
    assert "status must be one of" in bad.text


def test_specification_tags_are_normalized_and_filterable(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    spec_both = client.post(
        "/api/specifications",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Spec both",
            "status": "Draft",
            "tags": ["Backend", "backend", " UX "],
        },
    )
    assert spec_both.status_code == 200
    spec_both_payload = spec_both.json()
    assert spec_both_payload["tags"] == ["backend", "ux"]

    spec_single = client.post(
        "/api/specifications",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Spec backend only",
            "status": "Draft",
            "tags": ["backend"],
        },
    )
    assert spec_single.status_code == 200
    spec_single_payload = spec_single.json()
    assert spec_single_payload["tags"] == ["backend"]

    spec_other = client.post(
        "/api/specifications",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Spec other",
            "status": "Draft",
            "tags": ["ops"],
        },
    )
    assert spec_other.status_code == 200

    filtered = client.get(f"/api/specifications?workspace_id={ws_id}&project_id={project_id}&tags=backend,ux")
    assert filtered.status_code == 200
    filtered_ids = {item["id"] for item in filtered.json()["items"]}
    assert spec_both_payload["id"] in filtered_ids
    assert spec_single_payload["id"] in filtered_ids
    assert spec_other.json()["id"] not in filtered_ids

    patched = client.patch(
        f"/api/specifications/{spec_single_payload['id']}",
        json={"tags": ["Critical", "critical", "infra"]},
    )
    assert patched.status_code == 200
    assert patched.json()["tags"] == ["critical", "infra"]

    filtered_after_patch = client.get(f"/api/specifications?workspace_id={ws_id}&project_id={project_id}&tags=critical")
    assert filtered_after_patch.status_code == 200
    filtered_after_patch_ids = {item["id"] for item in filtered_after_patch.json()["items"]}
    assert spec_single_payload["id"] in filtered_after_patch_ids


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


def test_create_and_bulk_create_tasks_from_specification_endpoint(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    spec = client.post(
        "/api/specifications",
        json={"workspace_id": ws_id, "project_id": project_id, "title": "Spec wrappers", "status": "Ready"},
    ).json()

    created_single = client.post(
        f"/api/specifications/{spec['id']}/tasks",
        json={"title": "Create one"},
    )
    assert created_single.status_code == 200
    single_payload = created_single.json()
    assert single_payload["specification_id"] == spec["id"]

    created_bulk = client.post(
        f"/api/specifications/{spec['id']}/tasks/bulk",
        json={"titles": ["Bulk one", "", "Bulk two"]},
    )
    assert created_bulk.status_code == 200
    bulk_payload = created_bulk.json()
    assert bulk_payload["created"] == 2
    assert bulk_payload["failed"] == 0
    assert bulk_payload["total"] == 2
    assert len(bulk_payload["items"]) == 2
    assert all(item["specification_id"] == spec["id"] for item in bulk_payload["items"])

    listed = client.get(f"/api/tasks?workspace_id={ws_id}&project_id={project_id}&specification_id={spec['id']}")
    assert listed.status_code == 200
    task_ids = {item["id"] for item in listed.json()["items"]}
    assert single_payload["id"] in task_ids
    assert {item["id"] for item in bulk_payload["items"]}.issubset(task_ids)


def test_link_and_unlink_task_and_note_using_specification_wrappers(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    spec = client.post(
        "/api/specifications",
        json={"workspace_id": ws_id, "project_id": project_id, "title": "Linking spec", "status": "Ready"},
    ).json()

    task = client.post(
        "/api/tasks",
        json={"title": "Unlinked task", "workspace_id": ws_id, "project_id": project_id},
    ).json()
    note = client.post(
        "/api/notes",
        json={"title": "Unlinked note", "workspace_id": ws_id, "project_id": project_id},
    ).json()

    task_link = client.post(f"/api/specifications/{spec['id']}/tasks/{task['id']}/link")
    assert task_link.status_code == 200
    assert task_link.json()["specification_id"] == spec["id"]

    note_link = client.post(f"/api/specifications/{spec['id']}/notes/{note['id']}/link")
    assert note_link.status_code == 200
    assert note_link.json()["specification_id"] == spec["id"]

    task_unlink = client.post(f"/api/specifications/{spec['id']}/tasks/{task['id']}/unlink")
    assert task_unlink.status_code == 200
    assert task_unlink.json()["id"] == task["id"]
    assert task_unlink.json()["specification_id"] is None

    note_unlink = client.post(f"/api/specifications/{spec['id']}/notes/{note['id']}/unlink")
    assert note_unlink.status_code == 200
    assert note_unlink.json()["id"] == note["id"]
    assert note_unlink.json()["specification_id"] is None

    task_still_exists = client.get(f"/api/tasks?workspace_id={ws_id}&project_id={project_id}&q=Unlinked task")
    assert task_still_exists.status_code == 200
    assert any(item["id"] == task["id"] and item["specification_id"] is None for item in task_still_exists.json()["items"])

    note_still_exists = client.get(f"/api/notes/{note['id']}")
    assert note_still_exists.status_code == 200
    assert note_still_exists.json()["specification_id"] is None


def test_patch_linked_task_allows_same_project_but_blocks_project_change(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_a = bootstrap["projects"][0]["id"]
    project_b = client.post("/api/projects", json={"workspace_id": ws_id, "name": "Second"}).json()["id"]

    spec = client.post(
        "/api/specifications",
        json={"workspace_id": ws_id, "project_id": project_a, "title": "Patch guard spec", "status": "Ready"},
    ).json()
    task = client.post(
        "/api/tasks",
        json={
            "title": "Linked task",
            "workspace_id": ws_id,
            "project_id": project_a,
            "specification_id": spec["id"],
        },
    ).json()

    same_project_patch = client.patch(
        f"/api/tasks/{task['id']}",
        json={"description": "Updated safely", "project_id": project_a},
    )
    assert same_project_patch.status_code == 200
    assert same_project_patch.json()["description"] == "Updated safely"
    assert same_project_patch.json()["specification_id"] == spec["id"]
    assert same_project_patch.json()["project_id"] == project_a

    change_project_patch = client.patch(
        f"/api/tasks/{task['id']}",
        json={"project_id": project_b},
    )
    assert change_project_patch.status_code == 409
    assert "Cannot change project while task is linked to specification" in change_project_patch.text


def test_link_existing_wrapper_rejects_cross_project_scope(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_a = bootstrap["projects"][0]["id"]
    project_b = client.post("/api/projects", json={"workspace_id": ws_id, "name": "Second"}).json()["id"]

    spec = client.post(
        "/api/specifications",
        json={"workspace_id": ws_id, "project_id": project_a, "title": "Project A spec", "status": "Ready"},
    ).json()
    task_b = client.post(
        "/api/tasks",
        json={"title": "Project B task", "workspace_id": ws_id, "project_id": project_b},
    ).json()
    note_b = client.post(
        "/api/notes",
        json={"title": "Project B note", "workspace_id": ws_id, "project_id": project_b},
    ).json()

    bad_task_link = client.post(f"/api/specifications/{spec['id']}/tasks/{task_b['id']}/link")
    assert bad_task_link.status_code == 400

    bad_note_link = client.post(f"/api/specifications/{spec['id']}/notes/{note_b['id']}/link")
    assert bad_note_link.status_code == 400


def test_specification_wrapper_endpoints_are_idempotent_with_command_id(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    spec = client.post(
        "/api/specifications",
        json={"workspace_id": ws_id, "project_id": project_id, "title": "Idempotent spec", "status": "Ready"},
    ).json()

    single_command = "cmd-spec-single-001"
    first_single = client.post(
        f"/api/specifications/{spec['id']}/tasks",
        json={"title": "Idempotent wrapper task"},
        headers={"X-Command-Id": single_command},
    )
    second_single = client.post(
        f"/api/specifications/{spec['id']}/tasks",
        json={"title": "Idempotent wrapper task"},
        headers={"X-Command-Id": single_command},
    )
    assert first_single.status_code == 200
    assert second_single.status_code == 200
    assert first_single.json()["id"] == second_single.json()["id"]

    bulk_command = "cmd-spec-bulk-001"
    first_bulk = client.post(
        f"/api/specifications/{spec['id']}/tasks/bulk",
        json={"titles": ["Bulk idempotent one", "Bulk idempotent two"]},
        headers={"X-Command-Id": bulk_command},
    )
    second_bulk = client.post(
        f"/api/specifications/{spec['id']}/tasks/bulk",
        json={"titles": ["Bulk idempotent one", "Bulk idempotent two"]},
        headers={"X-Command-Id": bulk_command},
    )
    assert first_bulk.status_code == 200
    assert second_bulk.status_code == 200
    assert [item["id"] for item in first_bulk.json()["items"]] == [item["id"] for item in second_bulk.json()["items"]]

    listed = client.get(f"/api/tasks?workspace_id={ws_id}&project_id={project_id}&specification_id={spec['id']}")
    assert listed.status_code == 200
    assert len([item for item in listed.json()["items"] if "Idempotent" in item["title"] or "Bulk idempotent" in item["title"]]) == 3


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
