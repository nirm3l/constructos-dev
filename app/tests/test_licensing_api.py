from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from importlib import reload
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

TEST_INSTALLATION_ID = "test-installation"


def build_client(tmp_path: Path) -> TestClient:
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    os.environ["LICENSE_ENFORCEMENT_ENABLED"] = "true"
    os.environ["LICENSE_INSTALLATION_ID"] = TEST_INSTALLATION_ID
    os.environ["LICENSE_TRIAL_DAYS"] = "7"
    import main

    main = reload(main)
    main.bootstrap_data()
    client = TestClient(main.app)
    login = client.post("/api/auth/login", json={"username": "m4tr1x", "password": "testtest"})
    assert login.status_code == 200
    return client


def test_license_status_defaults_to_trial(tmp_path: Path):
    client = build_client(tmp_path)

    res = client.get("/api/license/status")
    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    license_payload = payload["license"]
    assert license_payload["installation_id"] == TEST_INSTALLATION_ID
    assert license_payload["status"] == "trial"
    assert license_payload["enforcement_enabled"] is True
    assert license_payload["write_access"] is True
    assert license_payload["trial_ends_at"] is not None
    assert license_payload["grace_ends_at"] is not None


def test_license_status_expired_blocks_writes_when_enforced(tmp_path: Path):
    client = build_client(tmp_path)
    from shared.models import LicenseInstallation, SessionLocal

    with SessionLocal() as db:
        installation = db.execute(
            select(LicenseInstallation).where(LicenseInstallation.installation_id == TEST_INSTALLATION_ID)
        ).scalar_one()
        installation.status = "trial"
        installation.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=10)
        db.commit()

    res = client.get("/api/license/status")
    assert res.status_code == 200
    license_payload = res.json()["license"]
    assert license_payload["status"] == "expired"
    assert license_payload["enforcement_enabled"] is True
    assert license_payload["write_access"] is False


def test_expired_license_blocks_write_endpoints(tmp_path: Path):
    client = build_client(tmp_path)
    from shared.models import LicenseInstallation, SessionLocal

    with SessionLocal() as db:
        installation = db.execute(
            select(LicenseInstallation).where(LicenseInstallation.installation_id == TEST_INSTALLATION_ID)
        ).scalar_one()
        installation.status = "trial"
        installation.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=10)
        db.commit()

    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    workspace_id = bootstrap.json()["workspaces"][0]["id"]

    res = client.post("/api/projects", json={"workspace_id": workspace_id, "name": "Should be blocked"})
    assert res.status_code == 402
    payload = res.json()
    assert "License expired" in payload["detail"]
    assert payload["license"]["status"] == "expired"
    assert payload["license"]["write_access"] is False


def test_health_includes_license_summary(tmp_path: Path):
    client = build_client(tmp_path)

    res = client.get("/api/health")
    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    assert isinstance(payload.get("license"), dict)
    assert payload["license"]["status"] in {"trial", "active", "grace", "expired", "unlicensed"}
