import os
from importlib import reload
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select


def build_client(tmp_path: Path) -> TestClient:
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    import main

    main = reload(main)
    main.bootstrap_data()
    client = TestClient(main.app)
    login = client.post("/api/auth/login", json={"username": "m4tr1x", "password": "testtest"})
    assert login.status_code == 200
    return client


def _list_seed_counts(client: TestClient, *, workspace_id: str, project_id: str) -> tuple[int, int, int]:
    specifications = client.get(
        f"/api/specifications?workspace_id={workspace_id}&project_id={project_id}"
    ).json()["items"]
    tasks = client.get(f"/api/tasks?workspace_id={workspace_id}&project_id={project_id}").json()["items"]
    rules = client.get(f"/api/project-rules?workspace_id={workspace_id}&project_id={project_id}").json()["items"]
    return len(specifications), len(tasks), len(rules)


def test_project_template_catalog_endpoints(tmp_path):
    client = build_client(tmp_path)

    listed = client.get("/api/project-templates")
    assert listed.status_code == 200
    payload = listed.json()
    keys = {item["key"] for item in payload["items"]}
    assert "ddd_product_build" in keys
    assert "mobile_browser_game_development" in keys

    ddd = client.get("/api/project-templates/ddd")
    assert ddd.status_code == 200
    ddd_payload = ddd.json()
    assert ddd_payload["key"] == "ddd_product_build"
    assert ddd_payload["seed_counts"]["specifications"] >= 1
    assert ddd_payload["seed_counts"]["tasks"] >= 1
    assert ddd_payload["seed_counts"]["rules"] >= 1


def test_create_project_from_template_seeds_entities_and_binding(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]

    payload = {
        "workspace_id": workspace_id,
        "template_key": "ddd_product_build",
        "name": "DDD Template Pilot",
    }
    created = client.post("/api/projects/from-template", json=payload)
    assert created.status_code == 200
    body = created.json()

    project = body["project"]
    project_id = project["id"]
    assert body["template"]["key"] == "ddd_product_build"
    assert body["binding"]["template_key"] == "ddd_product_build"
    assert body["binding"]["template_version"] == "1.0.0"
    assert body["seed_summary"]["specification_count"] >= 1
    assert body["seed_summary"]["task_count"] >= 1
    assert body["seed_summary"]["rule_count"] >= 1

    spec_count, task_count, rule_count = _list_seed_counts(
        client,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    assert spec_count == body["seed_summary"]["specification_count"]
    assert task_count == body["seed_summary"]["task_count"]
    assert rule_count == body["seed_summary"]["rule_count"]

    second = client.post("/api/projects/from-template", json=payload)
    assert second.status_code == 200
    assert second.json()["project"]["id"] == project_id

    spec_count_after, task_count_after, rule_count_after = _list_seed_counts(
        client,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    assert spec_count_after == spec_count
    assert task_count_after == task_count
    assert rule_count_after == rule_count

    from shared.models import ProjectTemplateBinding, SessionLocal

    with SessionLocal() as db:
        bindings = db.execute(
            select(ProjectTemplateBinding).where(ProjectTemplateBinding.project_id == project_id)
        ).scalars().all()
        assert len(bindings) == 1
        assert bindings[0].template_key == "ddd_product_build"


def test_create_project_from_template_returns_404_for_unknown_template(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    response = client.post(
        "/api/projects/from-template",
        json={
            "workspace_id": workspace_id,
            "template_key": "unknown-template",
            "name": "Should Fail",
        },
    )
    assert response.status_code == 404


def test_create_project_from_template_syncs_graph_scaffold(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    workspace_id = client.get("/api/bootstrap").json()["workspaces"][0]["id"]

    from features.project_templates import application as template_app

    called: dict = {}

    def _capture_sync(*, project_id: str, workspace_id: str, template):
        called["project_id"] = project_id
        called["workspace_id"] = workspace_id
        called["template_key"] = template.key

    monkeypatch.setattr(template_app, "sync_template_graph_scaffold", _capture_sync)

    created = client.post(
        "/api/projects/from-template",
        json={
            "workspace_id": workspace_id,
            "template_key": "ddd",
            "name": "DDD Graph Seed",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert called["project_id"] == payload["project"]["id"]
    assert called["workspace_id"] == workspace_id
    assert called["template_key"] == "ddd_product_build"


def test_bootstrap_projects_expose_template_binding(tmp_path):
    client = build_client(tmp_path)
    bootstrap_payload = client.get("/api/bootstrap").json()
    workspace_id = bootstrap_payload["workspaces"][0]["id"]
    current_user_id = bootstrap_payload["current_user"]["id"]

    created = client.post(
        "/api/projects/from-template",
        json={
            "workspace_id": workspace_id,
            "template_key": "ddd_product_build",
            "name": "DDD Binding Visibility",
        },
    )
    assert created.status_code == 200
    created_project_id = created.json()["project"]["id"]

    refreshed = client.get("/api/bootstrap")
    assert refreshed.status_code == 200
    projects = refreshed.json()["projects"]
    project_payload = next(item for item in projects if item["id"] == created_project_id)
    binding = project_payload.get("template_binding")
    assert binding is not None
    assert binding["template_key"] == "ddd_product_build"
    assert binding["template_version"] == "1.0.0"
    assert binding["applied_by"] == current_user_id
    assert isinstance(binding["applied_at"], str) and binding["applied_at"]


def test_agent_service_can_create_project_from_template(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    workspace_id = client.get("/api/bootstrap").json()["workspaces"][0]["id"]

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", workspace_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {workspace_id})

    service = AgentTaskService()
    created = service.create_project_from_template(
        template_key="mobile-game",
        name="Mobile Game MCP Pilot",
    )
    assert created["project"]["workspace_id"] == workspace_id
    assert created["template"]["key"] == "mobile_browser_game_development"
    assert created["seed_summary"]["task_count"] >= 1
