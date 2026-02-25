from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from importlib import reload
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

TEST_INSTALLATION_ID = "test-installation"


def build_client(tmp_path: Path, installation_id: str | None = TEST_INSTALLATION_ID) -> TestClient:
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    os.environ["LICENSE_ENFORCEMENT_ENABLED"] = "true"
    if installation_id:
        os.environ["LICENSE_INSTALLATION_ID"] = installation_id
    else:
        os.environ.pop("LICENSE_INSTALLATION_ID", None)
    os.environ["LICENSE_TRIAL_DAYS"] = "7"
    import shared.licensing as shared_licensing
    import shared.models as shared_models
    import shared.settings as shared_settings
    import main

    shared_settings.LICENSE_INSTALLATION_ID = str(installation_id or "").strip()
    shared_models.ensure_engine()
    shared_licensing.reset_license_installation_id_cache()
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


def test_license_status_auto_generates_installation_id_when_not_configured(tmp_path: Path):
    client = build_client(tmp_path, installation_id=None)
    from shared.models import LicenseInstallation, SessionLocal

    res = client.get("/api/license/status")
    assert res.status_code == 200
    payload = res.json()
    license_payload = payload["license"]
    generated_id = str(license_payload["installation_id"])
    assert generated_id.startswith("inst-")

    with SessionLocal() as db:
        installation = db.execute(
            select(LicenseInstallation).where(LicenseInstallation.installation_id == generated_id)
        ).scalar_one_or_none()
        assert installation is not None


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


def test_license_status_prefers_expired_control_plane_entitlement_over_local_trial_window(tmp_path: Path):
    client = build_client(tmp_path)
    from shared.models import LicenseEntitlement, LicenseInstallation, SessionLocal

    with SessionLocal() as db:
        installation = db.execute(
            select(LicenseInstallation).where(LicenseInstallation.installation_id == TEST_INSTALLATION_ID)
        ).scalar_one()
        installation.status = "expired"
        installation.plan_code = "trial"
        installation.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=35)
        db.add(
            LicenseEntitlement(
                installation_id=installation.id,
                source="control-plane",
                status="expired",
                plan_code="trial",
                valid_from=datetime.now(timezone.utc) - timedelta(minutes=5),
                valid_until=None,
                raw_payload_json="{}",
            )
        )
        db.commit()

    res = client.get("/api/license/status")
    assert res.status_code == 200
    license_payload = res.json()["license"]
    assert license_payload["status"] == "expired"
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


def test_license_activate_endpoint_returns_updated_license_payload(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)

    import features.licensing.api as licensing_api

    def _fake_activate(code: str):
        assert code == "ACT-TEST-0001-0002-0003"
        return {
            "license": {
                "installation_id": TEST_INSTALLATION_ID,
                "status": "active",
                "plan_code": "monthly",
                "enforcement_enabled": True,
                "write_access": True,
                "trial_ends_at": None,
                "grace_ends_at": None,
                "last_validated_at": None,
                "token_expires_at": None,
                "metadata": {},
            },
            "seat_usage": {
                "active_installations": 1,
                "max_installations": 3,
                "customer_ref": "customer-001",
            },
        }

    monkeypatch.setattr(licensing_api, "activate_with_code_once", _fake_activate)

    res = client.post("/api/license/activate", json={"activation_code": "ACT-TEST-0001-0002-0003"})
    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    assert payload["license"]["status"] == "active"
    assert payload["seat_usage"]["max_installations"] == 3


def test_license_activate_endpoint_surfaces_activation_errors(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)

    import features.licensing.api as licensing_api
    from features.licensing.sync import LicenseActivationError

    def _fake_activate(_code: str):
        raise LicenseActivationError(409, "Seat limit exceeded (3/3)")

    monkeypatch.setattr(licensing_api, "activate_with_code_once", _fake_activate)

    res = client.post("/api/license/activate", json={"activation_code": "ACT-TEST-0001-0002-0003"})
    assert res.status_code == 409
    assert "Seat limit exceeded" in res.json()["detail"]
