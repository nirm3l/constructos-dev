from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func

from tests.core.support.runtime import build_client as build_runtime_client


def build_client(tmp_path: Path) -> TestClient:
    return build_runtime_client(tmp_path)


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
    reordered_task_positions = [listed_task_ids.index(group_id) for group_id in reordered_task_ids]
    assert reordered_task_positions == sorted(reordered_task_positions)

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
    reordered_note_positions = [listed_note_ids.index(group_id) for group_id in reordered_note_ids]
    assert reordered_note_positions == sorted(reordered_note_positions)


def test_reorder_group_commands_are_idempotent_with_same_command_id(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    task_group_ids: list[str] = []
    for name in ["T1", "T2", "T3"]:
        created = client.post("/api/task-groups", json={"workspace_id": ws_id, "project_id": project_id, "name": name})
        assert created.status_code == 200
        task_group_ids.append(created.json()["id"])

    reordered_task_ids = [task_group_ids[2], task_group_ids[0], task_group_ids[1]]
    task_command_id = "323e4567-e89b-12d3-a456-426614174000"
    first_task_reorder = client.post(
        f"/api/task-groups/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": reordered_task_ids},
        headers={"X-Command-Id": task_command_id},
    )
    assert first_task_reorder.status_code == 200
    assert first_task_reorder.json()["updated"] == 3

    from shared.models import SessionLocal, StoredEvent
    from features.task_groups.domain import EVENT_REORDERED as TASK_GROUP_EVENT_REORDERED
    from features.note_groups.domain import EVENT_REORDERED as NOTE_GROUP_EVENT_REORDERED

    with SessionLocal() as db:
        task_reorder_count_before_replay = (
            db.query(func.count(StoredEvent.id))
            .filter(
                StoredEvent.aggregate_type == "TaskGroup",
                StoredEvent.event_type == TASK_GROUP_EVENT_REORDERED,
                StoredEvent.aggregate_id.in_(task_group_ids),
            )
            .scalar()
        ) or 0

    second_task_reorder = client.post(
        f"/api/task-groups/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": reordered_task_ids},
        headers={"X-Command-Id": task_command_id},
    )
    assert second_task_reorder.status_code == 200
    assert second_task_reorder.json()["updated"] == 3

    with SessionLocal() as db:
        task_reorder_count_after_replay = (
            db.query(func.count(StoredEvent.id))
            .filter(
                StoredEvent.aggregate_type == "TaskGroup",
                StoredEvent.event_type == TASK_GROUP_EVENT_REORDERED,
                StoredEvent.aggregate_id.in_(task_group_ids),
            )
            .scalar()
        ) or 0
    assert task_reorder_count_after_replay == task_reorder_count_before_replay

    note_group_ids: list[str] = []
    for name in ["N1", "N2", "N3"]:
        created = client.post("/api/note-groups", json={"workspace_id": ws_id, "project_id": project_id, "name": name})
        assert created.status_code == 200
        note_group_ids.append(created.json()["id"])

    reordered_note_ids = [note_group_ids[1], note_group_ids[2], note_group_ids[0]]
    note_command_id = "423e4567-e89b-12d3-a456-426614174000"
    first_note_reorder = client.post(
        f"/api/note-groups/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": reordered_note_ids},
        headers={"X-Command-Id": note_command_id},
    )
    assert first_note_reorder.status_code == 200
    assert first_note_reorder.json()["updated"] == 3

    with SessionLocal() as db:
        note_reorder_count_before_replay = (
            db.query(func.count(StoredEvent.id))
            .filter(
                StoredEvent.aggregate_type == "NoteGroup",
                StoredEvent.event_type == NOTE_GROUP_EVENT_REORDERED,
                StoredEvent.aggregate_id.in_(note_group_ids),
            )
            .scalar()
        ) or 0

    second_note_reorder = client.post(
        f"/api/note-groups/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": reordered_note_ids},
        headers={"X-Command-Id": note_command_id},
    )
    assert second_note_reorder.status_code == 200
    assert second_note_reorder.json()["updated"] == 3

    with SessionLocal() as db:
        note_reorder_count_after_replay = (
            db.query(func.count(StoredEvent.id))
            .filter(
                StoredEvent.aggregate_type == "NoteGroup",
                StoredEvent.event_type == NOTE_GROUP_EVENT_REORDERED,
                StoredEvent.aggregate_id.in_(note_group_ids),
            )
            .scalar()
        ) or 0
    assert note_reorder_count_after_replay == note_reorder_count_before_replay


def test_reorder_group_commands_ignore_duplicate_group_ids(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    task_group_ids: list[str] = []
    for name in ["DG1", "DG2", "DG3"]:
        created = client.post("/api/task-groups", json={"workspace_id": ws_id, "project_id": project_id, "name": name})
        assert created.status_code == 200
        task_group_ids.append(created.json()["id"])

    reordered_task_ids_with_dupes = [task_group_ids[2], task_group_ids[2], task_group_ids[0], task_group_ids[1]]
    reorder_tasks = client.post(
        f"/api/task-groups/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": reordered_task_ids_with_dupes},
    )
    assert reorder_tasks.status_code == 200
    assert reorder_tasks.json()["updated"] == 3

    listed_task_groups = client.get(f"/api/task-groups?workspace_id={ws_id}&project_id={project_id}")
    assert listed_task_groups.status_code == 200
    listed_task_ids = [item["id"] for item in listed_task_groups.json()["items"]]
    assert listed_task_ids.index(task_group_ids[2]) < listed_task_ids.index(task_group_ids[0]) < listed_task_ids.index(task_group_ids[1])

    note_group_ids: list[str] = []
    for name in ["DN1", "DN2", "DN3"]:
        created = client.post("/api/note-groups", json={"workspace_id": ws_id, "project_id": project_id, "name": name})
        assert created.status_code == 200
        note_group_ids.append(created.json()["id"])

    reordered_note_ids_with_dupes = [note_group_ids[1], note_group_ids[1], note_group_ids[2], note_group_ids[0]]
    reorder_notes = client.post(
        f"/api/note-groups/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": reordered_note_ids_with_dupes},
    )
    assert reorder_notes.status_code == 200
    assert reorder_notes.json()["updated"] == 3

    listed_note_groups = client.get(f"/api/note-groups?workspace_id={ws_id}&project_id={project_id}")
    assert listed_note_groups.status_code == 200
    listed_note_ids = [item["id"] for item in listed_note_groups.json()["items"]]
    assert listed_note_ids.index(note_group_ids[1]) < listed_note_ids.index(note_group_ids[2]) < listed_note_ids.index(note_group_ids[0])


def test_reorder_group_commands_skip_noop_event_emission(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    task_group_ids: list[str] = []
    for name in ["NG1", "NG2", "NG3"]:
        created = client.post("/api/task-groups", json={"workspace_id": ws_id, "project_id": project_id, "name": name})
        assert created.status_code == 200
        task_group_ids.append(created.json()["id"])

    note_group_ids: list[str] = []
    for name in ["NN1", "NN2", "NN3"]:
        created = client.post("/api/note-groups", json={"workspace_id": ws_id, "project_id": project_id, "name": name})
        assert created.status_code == 200
        note_group_ids.append(created.json()["id"])

    from shared.models import SessionLocal, StoredEvent
    from features.task_groups.domain import EVENT_REORDERED as TASK_GROUP_EVENT_REORDERED
    from features.note_groups.domain import EVENT_REORDERED as NOTE_GROUP_EVENT_REORDERED

    reorder_tasks = client.post(
        f"/api/task-groups/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": task_group_ids},
    )
    assert reorder_tasks.status_code == 200
    assert reorder_tasks.json()["updated"] == 3

    reorder_notes = client.post(
        f"/api/note-groups/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": note_group_ids},
    )
    assert reorder_notes.status_code == 200
    assert reorder_notes.json()["updated"] == 3

    with SessionLocal() as db:
        task_reordered_before_noop = (
            db.query(func.count(StoredEvent.id))
            .filter(
                StoredEvent.aggregate_type == "TaskGroup",
                StoredEvent.event_type == TASK_GROUP_EVENT_REORDERED,
                StoredEvent.aggregate_id.in_(task_group_ids),
            )
            .scalar()
        ) or 0
        note_reordered_before_noop = (
            db.query(func.count(StoredEvent.id))
            .filter(
                StoredEvent.aggregate_type == "NoteGroup",
                StoredEvent.event_type == NOTE_GROUP_EVENT_REORDERED,
                StoredEvent.aggregate_id.in_(note_group_ids),
            )
            .scalar()
        ) or 0

    second_reorder_tasks = client.post(
        f"/api/task-groups/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": task_group_ids},
    )
    assert second_reorder_tasks.status_code == 200
    assert second_reorder_tasks.json()["updated"] == 3

    second_reorder_notes = client.post(
        f"/api/note-groups/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": note_group_ids},
    )
    assert second_reorder_notes.status_code == 200
    assert second_reorder_notes.json()["updated"] == 3

    with SessionLocal() as db:
        task_reordered_after_noop = (
            db.query(func.count(StoredEvent.id))
            .filter(
                StoredEvent.aggregate_type == "TaskGroup",
                StoredEvent.event_type == TASK_GROUP_EVENT_REORDERED,
                StoredEvent.aggregate_id.in_(task_group_ids),
            )
            .scalar()
        ) or 0
        note_reordered_after_noop = (
            db.query(func.count(StoredEvent.id))
            .filter(
                StoredEvent.aggregate_type == "NoteGroup",
                StoredEvent.event_type == NOTE_GROUP_EVENT_REORDERED,
                StoredEvent.aggregate_id.in_(note_group_ids),
            )
            .scalar()
        ) or 0

    assert task_reordered_after_noop == task_reordered_before_noop
    assert note_reordered_after_noop == note_reordered_before_noop


def test_reorder_tasks_is_idempotent_and_skips_noop_events(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    task_ids: list[str] = []
    for title in ["RTR Task A", "RTR Task B", "RTR Task C"]:
        created = client.post(
            "/api/tasks",
            json={"title": title, "workspace_id": ws_id, "project_id": project_id},
        )
        assert created.status_code == 200
        task_ids.append(created.json()["id"])

    reordered_ids = [task_ids[2], task_ids[0], task_ids[1]]
    command_id = "523e4567-e89b-12d3-a456-426614174000"
    first_reorder = client.post(
        f"/api/tasks/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": reordered_ids},
        headers={"X-Command-Id": command_id},
    )
    assert first_reorder.status_code == 200
    payload = first_reorder.json()
    assert payload["ok"] is True
    assert payload["updated"] == 3

    listed = client.get(f"/api/tasks?workspace_id={ws_id}&project_id={project_id}&q=RTR Task")
    assert listed.status_code == 200
    listed_ids = [item["id"] for item in listed.json()["items"]]
    assert listed_ids.index(task_ids[2]) < listed_ids.index(task_ids[0]) < listed_ids.index(task_ids[1])

    from shared.models import SessionLocal, StoredEvent
    from features.tasks.domain import EVENT_REORDERED as TASK_EVENT_REORDERED

    with SessionLocal() as db:
        reorder_count_before_replay = (
            db.query(func.count(StoredEvent.id))
            .filter(
                StoredEvent.aggregate_type == "Task",
                StoredEvent.event_type == TASK_EVENT_REORDERED,
                StoredEvent.aggregate_id.in_(task_ids),
            )
            .scalar()
        ) or 0

    replay_reorder = client.post(
        f"/api/tasks/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": reordered_ids},
        headers={"X-Command-Id": command_id},
    )
    assert replay_reorder.status_code == 200
    replay_payload = replay_reorder.json()
    assert replay_payload["ok"] is True
    assert replay_payload["updated"] == 3

    with SessionLocal() as db:
        reorder_count_after_replay = (
            db.query(func.count(StoredEvent.id))
            .filter(
                StoredEvent.aggregate_type == "Task",
                StoredEvent.event_type == TASK_EVENT_REORDERED,
                StoredEvent.aggregate_id.in_(task_ids),
            )
            .scalar()
        ) or 0
    assert reorder_count_after_replay == reorder_count_before_replay

    with SessionLocal() as db:
        reorder_count_before_noop = (
            db.query(func.count(StoredEvent.id))
            .filter(
                StoredEvent.aggregate_type == "Task",
                StoredEvent.event_type == TASK_EVENT_REORDERED,
                StoredEvent.aggregate_id.in_(task_ids),
            )
            .scalar()
        ) or 0

    noop_reorder = client.post(
        f"/api/tasks/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": reordered_ids},
        headers={"X-Command-Id": "623e4567-e89b-12d3-a456-426614174000"},
    )
    assert noop_reorder.status_code == 200
    noop_payload = noop_reorder.json()
    assert noop_payload["ok"] is True
    assert noop_payload["updated"] == 3

    with SessionLocal() as db:
        reorder_count_after_noop = (
            db.query(func.count(StoredEvent.id))
            .filter(
                StoredEvent.aggregate_type == "Task",
                StoredEvent.event_type == TASK_EVENT_REORDERED,
                StoredEvent.aggregate_id.in_(task_ids),
            )
            .scalar()
        ) or 0
    assert reorder_count_after_noop == reorder_count_before_noop


def test_reorder_tasks_ignores_duplicate_task_ids(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    task_ids: list[str] = []
    for title in ["RTD Task A", "RTD Task B", "RTD Task C"]:
        created = client.post(
            "/api/tasks",
            json={"title": title, "workspace_id": ws_id, "project_id": project_id},
        )
        assert created.status_code == 200
        task_ids.append(created.json()["id"])

    reordered_ids_with_dupes = [task_ids[2], task_ids[2], task_ids[0], task_ids[1]]
    reorder = client.post(
        f"/api/tasks/reorder?workspace_id={ws_id}&project_id={project_id}",
        json={"ordered_ids": reordered_ids_with_dupes},
    )
    assert reorder.status_code == 200
    payload = reorder.json()
    assert payload["ok"] is True
    assert payload["updated"] == 3

    listed = client.get(f"/api/tasks?workspace_id={ws_id}&project_id={project_id}&q=RTD Task")
    assert listed.status_code == 200
    listed_ids = [item["id"] for item in listed.json()["items"]]
    assert listed_ids.index(task_ids[2]) < listed_ids.index(task_ids[0]) < listed_ids.index(task_ids[1])
