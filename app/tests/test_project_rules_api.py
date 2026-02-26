from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def build_client(tmp_path: Path) -> TestClient:
    import os
    from importlib import reload

    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    import main

    main = reload(main)
    main.bootstrap_data()
    client = TestClient(main.app)
    login = client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'})
    assert login.status_code == 200
    return client


def test_project_rule_crud_and_listing(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]
    project_id = bootstrap["projects"][0]["id"]

    created = client.post(
        "/api/project-rules",
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "title": "Code quality",
            "body": "Every change must include tests.",
        },
    )
    assert created.status_code == 200
    rule = created.json()
    assert rule["title"] == "Code quality"
    assert rule["project_id"] == project_id

    listed = client.get(f"/api/project-rules?workspace_id={ws_id}&project_id={project_id}")
    assert listed.status_code == 200
    assert any(item["id"] == rule["id"] for item in listed.json()["items"])

    patched = client.patch(
        f"/api/project-rules/{rule['id']}",
        json={"title": "Code quality bar", "body": "Every change includes tests and docs."},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Code quality bar"

    deleted = client.post(f"/api/project-rules/{rule['id']}/delete")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    missing = client.get(f"/api/project-rules/{rule['id']}")
    assert missing.status_code == 404


def test_delete_project_deletes_project_rules(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]

    project = client.post("/api/projects", json={"workspace_id": ws_id, "name": "Rule scoped"}).json()
    rule = client.post(
        "/api/project-rules",
        json={
            "workspace_id": ws_id,
            "project_id": project["id"],
            "title": "Rule to be deleted",
            "body": "This should disappear with project delete.",
        },
    )
    assert rule.status_code == 200
    rule_id = rule.json()["id"]

    deleted = client.delete(f"/api/projects/{project['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    missing = client.get(f"/api/project-rules/{rule_id}")
    assert missing.status_code == 404
