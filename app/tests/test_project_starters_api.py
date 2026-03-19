import os
from importlib import reload
from pathlib import Path

from fastapi.testclient import TestClient
from fastapi import HTTPException


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
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert login.status_code == 200
    return client


def test_project_starter_catalog_endpoints(tmp_path):
    client = build_client(tmp_path)

    listed = client.get("/api/project-starters")
    assert listed.status_code == 200
    payload = listed.json()
    keys = {item["key"] for item in payload["items"]}
    assert keys == {"api_service", "blank", "ddd_system", "web_app", "web_game"}
    assert "mobile_first" in payload["facets"]

    ddd = client.get("/api/project-starters/ddd")
    assert ddd.status_code == 200
    ddd_payload = ddd.json()
    assert ddd_payload["key"] == "ddd_system"
    assert ddd_payload["artifact_counts"]["specifications"] >= 1
    assert ddd_payload["artifact_counts"]["tasks"] >= 1
    assert ddd_payload["artifact_counts"]["rules"] >= 1


def test_setup_project_orchestration_requires_primary_starter_for_new_project(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    from features.agents.service import AgentTaskService

    service = AgentTaskService(
        require_token=False,
        actor_user_id=bootstrap["current_user"]["id"],
        allowed_workspace_ids={bootstrap["workspaces"][0]["id"]},
        allowed_project_ids=set(),
        default_workspace_id=bootstrap["workspaces"][0]["id"],
    )
    try:
        service.setup_project_orchestration(
            workspace_id=bootstrap["workspaces"][0]["id"],
            name="Starter Missing",
            short_description="Missing starter",
            enable_team_mode=False,
            enable_git_delivery=False,
        )
    except HTTPException as exc:
        detail = exc.detail
    else:
        raise AssertionError("Expected missing starter validation")
    assert detail["next_input_key"] == "primary_starter_key"


def test_setup_project_orchestration_persists_setup_profile_and_seeds_starter_artifacts(tmp_path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    workspace_id = bootstrap["workspaces"][0]["id"]
    from features.agents.service import AgentTaskService

    service = AgentTaskService(
        require_token=False,
        actor_user_id=bootstrap["current_user"]["id"],
        allowed_workspace_ids={workspace_id},
        allowed_project_ids=set(),
        default_workspace_id=workspace_id,
    )
    result = service.setup_project_orchestration(
        workspace_id=workspace_id,
        primary_starter_key="web_game",
        facet_keys=["ddd_system", "mobile_first"],
        name="Atlas Arena",
        short_description="Browser game with domain boundaries",
        enable_team_mode=False,
        enable_git_delivery=False,
        enable_docker_compose=False,
        expected_event_storming_enabled=True,
    )
    assert result["blocking"] is False
    assert result["effective"]["primary_starter_key"] == "web_game"
    assert "ddd_system" in result["effective"]["facet_keys"]
    assert result["seeded_entities"]["starter_artifacts"]["counts"]["specifications"] >= 1

    project_id = result["project"]["id"]
    profile = client.get(f"/api/projects/{project_id}/setup-profile")
    assert profile.status_code == 200
    profile_payload = profile.json()
    assert profile_payload["primary_starter_key"] == "web_game"
    assert "mobile_first" in profile_payload["facet_keys"]

    project_payload = client.get("/api/bootstrap").json()
    created_project = next(item for item in project_payload["projects"] if item["id"] == project_id)
    assert created_project["setup_profile"]["primary_starter_key"] == "web_game"
