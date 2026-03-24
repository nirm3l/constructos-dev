from __future__ import annotations

import os
import json
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
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert login.status_code == 200
    return client


def _login_as_user(client: TestClient, *, username: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def _activate_user_password(client: TestClient, *, username: str, temporary_password: str, new_password: str) -> None:
    _login_as_user(client, username=username, password=temporary_password)
    changed = client.post(
        "/api/auth/change-password",
        json={"current_password": temporary_password, "new_password": new_password},
    )
    assert changed.status_code == 200


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


def test_license_status_hides_legacy_public_beta_metadata_for_non_beta_subscription(tmp_path: Path):
    client = build_client(tmp_path)
    from shared.models import LicenseEntitlement, LicenseInstallation, SessionLocal

    with SessionLocal() as db:
        installation = db.execute(
            select(LicenseInstallation).where(LicenseInstallation.installation_id == TEST_INSTALLATION_ID)
        ).scalar_one()
        installation.status = "active"
        installation.plan_code = "trial"
        installation.metadata_json = json.dumps(
            {
                "subscription_status": "trialing",
                "subscription_valid_until": "2026-02-26T08:00:00+00:00",
                "public_beta": True,
                "public_beta_free_until": "2026-03-31T23:59:59+00:00",
                "entitlement_reason": "subscription_trialing",
            }
        )
        db.add(
            LicenseEntitlement(
                installation_id=installation.id,
                source="control-plane",
                status="active",
                plan_code="trial",
                valid_from=datetime.now(timezone.utc) - timedelta(minutes=5),
                valid_until=datetime.now(timezone.utc) + timedelta(days=1),
                raw_payload_json="{}",
            )
        )
        db.commit()

    res = client.get("/api/license/status")
    assert res.status_code == 200
    metadata = res.json()["license"]["metadata"]
    assert metadata.get("subscription_status") == "trialing"
    assert "public_beta" not in metadata
    assert "public_beta_free_until" not in metadata


def test_license_status_includes_update_notification_with_stable_id_and_type(tmp_path: Path):
    client = build_client(tmp_path)
    from shared.models import LicenseInstallation, SessionLocal

    with SessionLocal() as db:
        installation = db.execute(
            select(LicenseInstallation).where(LicenseInstallation.installation_id == TEST_INSTALLATION_ID)
        ).scalar_one()
        installation.metadata_json = json.dumps(
            {
                "latest_app_version": "v9.9.9",
                "latest_image_tag": "v9.9.9",
                "latest_release_at": "2026-03-01T12:00:00+00:00",
            }
        )
        db.commit()

    res = client.get("/api/license/status")
    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    license_payload = payload["license"]
    notifications = license_payload.get("notifications") or []
    assert isinstance(notifications, list)
    assert len(notifications) >= 1
    update_notifications = [n for n in notifications if n.get("notification_type") == "AppUpdateAvailable"]
    assert len(update_notifications) == 1
    item = update_notifications[0]
    assert str(item.get("id") or "").startswith("license-app-update:")
    assert item.get("dedupe_key") == item.get("id")
    assert isinstance(item.get("payload"), dict)
    assert item["payload"].get("action") == "auto_update_app_images"
    assert item["payload"].get("target_image_tag") == "v9.9.9"


def test_license_status_includes_control_plane_notifications_from_metadata(tmp_path: Path):
    client = build_client(tmp_path)
    from shared.models import LicenseInstallation, SessionLocal

    with SessionLocal() as db:
        installation = db.execute(
            select(LicenseInstallation).where(LicenseInstallation.installation_id == TEST_INSTALLATION_ID)
        ).scalar_one()
        installation.metadata_json = json.dumps(
            {
                "control_plane_notifications": [
                    {
                        "id": "cpn-release-001",
                        "message": "ConstructOS v0.1.1660 is available.",
                        "created_at": "2026-03-01T12:00:00+00:00",
                        "notification_type": "AppUpdateAvailable",
                        "severity": "info",
                        "dedupe_key": "cpn-release-001",
                        "source_event": "control-plane.notification",
                        "payload": {"action": "auto_update_app_images"},
                    }
                ]
            }
        )
        db.commit()

    res = client.get("/api/license/status")
    assert res.status_code == 200
    payload = res.json()["license"]
    assert "control_plane_notifications" not in (payload.get("metadata") or {})
    notifications = payload["notifications"]
    item = next(note for note in notifications if note["id"] == "cpn-release-001")
    assert item["notification_type"] == "AppUpdateAvailable"
    assert item["payload"]["action"] == "auto_update_app_images"


def test_auto_update_endpoint_ignores_legacy_image_tag_field_and_starts_run(tmp_path: Path):
    client = build_client(tmp_path)

    res = client.post("/api/license/auto-update", json={"image_tag": "bad tag with space"})
    assert res.status_code == 200
    payload = res.json()
    assert payload.get("ok") is True
    assert str(payload.get("run_id") or "").strip()


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


def test_license_activate_requires_owner(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]

    created = client.post(
        "/api/admin/users",
        json={"workspace_id": ws_id, "username": "license-admin", "role": "Admin"},
    )
    assert created.status_code == 200
    temp_password = created.json()["temporary_password"]

    client.post("/api/auth/logout")
    _activate_user_password(
        client,
        username="license-admin",
        temporary_password=temp_password,
        new_password="license-admin-pass-123",
    )

    res = client.post("/api/license/activate", json={"activation_code": "ACT-TEST-0001-0002-0003"})
    assert res.status_code == 403
    assert res.json()["detail"] == "Only workspace owners can activate a license."


def test_license_auto_update_requires_owner(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get("/api/bootstrap").json()
    ws_id = bootstrap["workspaces"][0]["id"]

    created = client.post(
        "/api/admin/users",
        json={"workspace_id": ws_id, "username": "auto-update-admin", "role": "Admin"},
    )
    assert created.status_code == 200
    temp_password = created.json()["temporary_password"]

    client.post("/api/auth/logout")
    _activate_user_password(
        client,
        username="auto-update-admin",
        temporary_password=temp_password,
        new_password="auto-update-admin-pass-123",
    )

    res = client.post("/api/license/auto-update")
    assert res.status_code == 403
    assert res.json()["detail"] == "Only workspace owners can trigger application auto-update."
