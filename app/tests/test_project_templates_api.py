import os
from importlib import reload
from pathlib import Path

import httpx
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


def test_preview_project_from_template_returns_plan_and_does_not_write(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    project_count_before = len(bootstrap["projects"])

    response = client.post(
        "/api/projects/from-template/preview",
        json={
            "workspace_id": workspace_id,
            "template_key": "ddd_product_build",
            "name": "DDD Preview Pilot",
            "description": "Preview only",
            "member_user_ids": [bootstrap["current_user"]["id"]],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "preview"
    assert body["template"]["key"] == "ddd_product_build"
    assert body["project_blueprint"]["name"] == "DDD Preview Pilot"
    assert body["project_conflict"]["status"] == "none"
    assert body["project_conflict"]["can_create"] is True
    assert body["seed_summary"]["specification_count"] >= 1
    assert body["seed_summary"]["task_count"] >= 1
    assert body["seed_summary"]["rule_count"] >= 1
    assert body["seed_summary"]["graph_node_count"] >= 1
    assert body["seed_summary"]["graph_edge_count"] >= 1
    preview_project_id = body["project_blueprint"]["project_id"]
    assert isinstance(preview_project_id, str) and preview_project_id

    refreshed = client.get("/api/bootstrap").json()
    assert len(refreshed["projects"]) == project_count_before

    from shared.models import ProjectTemplateBinding, SessionLocal

    with SessionLocal() as db:
        binding = db.execute(
            select(ProjectTemplateBinding).where(ProjectTemplateBinding.project_id == preview_project_id)
        ).scalar_one_or_none()
        assert binding is None


def test_preview_project_from_template_returns_404_for_unknown_template(tmp_path):
    client = build_client(tmp_path)
    workspace_id = client.get("/api/bootstrap").json()["workspaces"][0]["id"]
    response = client.post(
        "/api/projects/from-template/preview",
        json={
            "workspace_id": workspace_id,
            "template_key": "unknown-template",
        },
    )
    assert response.status_code == 404


def test_preview_project_from_template_applies_parameters_to_seed_blueprint(tmp_path):
    client = build_client(tmp_path)
    workspace_id = client.get("/api/bootstrap").json()["workspaces"][0]["id"]
    response = client.post(
        "/api/projects/from-template/preview",
        json={
            "workspace_id": workspace_id,
            "template_key": "ddd",
            "name": "DDD Parameter Preview",
            "parameters": {
                "domain_name": "Order",
                "bounded_context_name": "Sales Context",
                "integration_boundary_name": "ERP ACL Boundary",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["binding_preview"]["parameters"]["domain_name"] == "Order"
    nodes = payload["seed_blueprint"]["graph"]["nodes"]
    node_title_by_key = {str(item["node_key"]): str(item["title"]) for item in nodes}
    assert node_title_by_key["agg_product"] == "Order Aggregate"
    assert node_title_by_key["bc_core"] == "Sales Context"
    assert node_title_by_key["boundary_catalog_acl"] == "ERP ACL Boundary"


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


def test_create_project_from_template_applies_parameters_and_persists_binding_parameters(tmp_path):
    client = build_client(tmp_path)
    workspace_id = client.get("/api/bootstrap").json()["workspaces"][0]["id"]
    response = client.post(
        "/api/projects/from-template",
        json={
            "workspace_id": workspace_id,
            "template_key": "mobile-game",
            "name": "Mobile Parameter Pilot",
            "parameters": {
                "game_name": "Sky Runners",
                "target_device_profile": "Midrange Android 2022",
                "deployment_target": "Staging LAN Cluster",
                "release_environment": "Staging",
                "qa_port": 4173,
                "team_size": 10,
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["binding"]["parameters"]["game_name"] == "Sky Runners"
    assert payload["binding"]["parameters"]["team_size"] == 10

    project_id = payload["project"]["id"]
    tasks = client.get(f"/api/tasks?workspace_id={workspace_id}&project_id={project_id}").json()["items"]
    deploy_task = next(item for item in tasks if item["title"] == "Create Docker Compose deployment profile for LAN QA")
    assert "Staging LAN Cluster" in str(deploy_task["description"])
    assert "4173" in str(deploy_task["description"])
    assert "large team" in str(deploy_task["description"]).casefold()

    rules = client.get(f"/api/project-rules?workspace_id={workspace_id}&project_id={project_id}").json()["items"]
    deploy_rule = next(
        item for item in rules if item["title"] == "All releases must be deployed through Docker Compose on a LAN-accessible port"
    )
    assert "Staging LAN Cluster" in str(deploy_rule["body"])
    assert "4173" in str(deploy_rule["body"])


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


def test_agent_service_can_preview_project_from_template(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    workspace_id = client.get("/api/bootstrap").json()["workspaces"][0]["id"]

    from features.agents.service import AgentTaskService
    import features.agents.service as svc_module

    monkeypatch.setattr(svc_module, "MCP_AUTH_TOKEN", "")
    monkeypatch.setattr(svc_module, "MCP_DEFAULT_WORKSPACE_ID", workspace_id)
    monkeypatch.setattr(svc_module, "MCP_ALLOWED_WORKSPACE_IDS", {workspace_id})

    service = AgentTaskService()
    preview = service.preview_project_from_template(
        template_key="mobile-game",
        name="Mobile Game Preview",
    )
    assert preview["mode"] == "preview"
    assert preview["template"]["key"] == "mobile_browser_game_development"
    assert preview["seed_summary"]["task_count"] >= 1


def test_create_project_from_template_seeds_template_skills(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    workspace_id = client.get("/api/bootstrap").json()["workspaces"][0]["id"]

    from dataclasses import replace

    from features.project_templates import application as template_app
    from features.project_templates.catalog import TemplateSkill, get_template_definition
    from features.project_skills import application as skill_app

    base_template = get_template_definition("ddd")
    assert base_template is not None
    template_with_skill = replace(
        base_template,
        skills=(
            TemplateSkill(
                source_url="https://example.com/skills/template-quality.md",
                name="Template Quality Skill",
                skill_key="template_quality",
                mode="enforced",
                trust_level="reviewed",
                required=True,
            ),
        ),
    )
    monkeypatch.setattr(template_app, "get_template_definition", lambda template_key: template_with_skill)

    def fake_get(url, timeout, follow_redirects, headers):  # noqa: ANN001, A002
        _ = (url, timeout, follow_redirects, headers)
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/markdown"},
            text="# Template Quality Skill\nAlways add tests and release notes.",
        )

    monkeypatch.setattr(skill_app.httpx, "get", fake_get)

    created = client.post(
        "/api/projects/from-template",
        json={
            "workspace_id": workspace_id,
            "template_key": "ddd",
            "name": "DDD Skill Seed",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    project_id = payload["project"]["id"]
    assert payload["seed_summary"]["skill_count"] == 1
    assert payload["seed_summary"]["skill_skip_count"] == 0
    assert len(payload["seeded_entity_ids"]["project_skill_ids"]) == 1
    assert len(payload["seeded_entity_ids"]["project_skill_rule_ids"]) == 1

    listed_skills = client.get(f"/api/project-skills?workspace_id={workspace_id}&project_id={project_id}")
    assert listed_skills.status_code == 200
    items = listed_skills.json()["items"]
    assert len(items) == 1
    assert items[0]["skill_key"] == "template_quality"
    assert items[0]["mode"] == "enforced"
    assert items[0]["trust_level"] == "reviewed"
