from __future__ import annotations

import os
import json
import base64
from importlib import reload
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select


def _create_ed25519_keypair() -> tuple[str, Ed25519PrivateKey]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return public_pem, private_key


def _sign_token_payload(payload: dict, private_key: Ed25519PrivateKey) -> dict:
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = private_key.sign(canonical)
    signature_b64 = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return {
        "alg": "ed25519",
        "kid": "test-key",
        "payload": payload,
        "signature": signature_b64,
    }


def test_sync_license_once_updates_local_entitlement(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    os.environ["LICENSE_ENFORCEMENT_ENABLED"] = "true"
    os.environ["LICENSE_INSTALLATION_ID"] = "sync-test-installation"
    os.environ["LICENSE_SERVER_TOKEN"] = "dev-license-token"
    os.environ["LICENSE_TRIAL_DAYS"] = "7"
    os.environ.pop("LICENSE_PUBLIC_KEY", None)

    import shared.models as shared_models
    import shared.licensing as shared_licensing
    import shared.settings as shared_settings
    import features.licensing.read_models as licensing_read_models

    reload(shared_settings)
    reload(shared_models)
    reload(shared_licensing)
    reload(licensing_read_models)
    shared_licensing.reset_license_installation_id_cache()

    import main

    main = reload(main)
    main.bootstrap_data()

    from features.licensing import sync

    sync = reload(sync)
    monkeypatch.setattr(sync, "_resolve_local_operating_system", lambda: "linux-test")
    captured_payloads: dict[str, dict] = {}

    class _MockResponse:
        def __init__(self, payload: dict):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _MockClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, headers: dict, json: dict):
            if url.endswith("/v1/installations/register"):
                captured_payloads["register"] = dict(json)
                return _MockResponse({"ok": True})
            if url.endswith("/v1/installations/heartbeat"):
                captured_payloads["heartbeat"] = dict(json)
                return _MockResponse(
                    {
                        "ok": True,
                        "entitlement": {
                            "status": "active",
                            "plan_code": "monthly",
                            "valid_from": "2026-02-21T00:00:00Z",
                            "valid_until": "2026-03-21T00:00:00Z",
                            "trial_ends_at": "2026-02-28T00:00:00Z",
                            "token_expires_at": "2026-02-21T01:00:00Z",
                            "metadata": {"billing_provider": "external-billing-app"},
                        },
                    }
                )
            raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(sync.httpx, "Client", _MockClient)

    ok = sync.sync_license_once()
    assert ok is True
    assert captured_payloads["register"]["operating_system"] == "linux-test"
    assert captured_payloads["heartbeat"]["operating_system"] == "linux-test"

    from shared.models import LicenseEntitlement, LicenseInstallation, LicenseValidationLog, SessionLocal

    with SessionLocal() as db:
        installation = db.execute(
            select(LicenseInstallation).where(LicenseInstallation.installation_id == "sync-test-installation")
        ).scalar_one()
        assert installation.status == "active"
        assert installation.plan_code == "monthly"

        entitlement = db.execute(
            select(LicenseEntitlement)
            .where(LicenseEntitlement.installation_id == installation.id)
            .order_by(LicenseEntitlement.id.desc())
        ).scalars().first()
        assert entitlement is not None
        assert entitlement.status == "active"
        assert entitlement.plan_code == "monthly"

        validation = db.execute(
            select(LicenseValidationLog)
            .where(LicenseValidationLog.installation_id == installation.id)
            .order_by(LicenseValidationLog.id.desc())
        ).scalars().first()
        assert validation is not None
        assert validation.result == "active"


def test_sync_license_once_persists_control_plane_notifications(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "notifications.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    os.environ["LICENSE_ENFORCEMENT_ENABLED"] = "true"
    os.environ["LICENSE_INSTALLATION_ID"] = "sync-notifications-installation"
    os.environ["LICENSE_SERVER_TOKEN"] = "dev-license-token"
    os.environ["LICENSE_TRIAL_DAYS"] = "7"
    os.environ.pop("LICENSE_PUBLIC_KEY", None)

    import shared.models as shared_models
    import shared.licensing as shared_licensing
    import shared.settings as shared_settings
    import features.licensing.read_models as licensing_read_models

    reload(shared_settings)
    reload(shared_models)
    reload(shared_licensing)
    reload(licensing_read_models)
    shared_licensing.reset_license_installation_id_cache()

    import main

    main = reload(main)
    main.bootstrap_data()

    from features.licensing import sync

    sync = reload(sync)

    class _MockResponse:
        def __init__(self, payload: dict):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _MockClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, headers: dict, json: dict):
            if url.endswith("/v1/installations/register"):
                return _MockResponse({"ok": True})
            if url.endswith("/v1/installations/heartbeat"):
                return _MockResponse(
                    {
                        "ok": True,
                        "notifications": [
                            {
                                "id": "cpn-test-notice",
                                "message": "ConstructOS update is available.",
                                "notification_type": "AppUpdateAvailable",
                                "severity": "info",
                                "dedupe_key": "cpn-test-notice",
                                "payload": {"action": "auto_update_app_images"},
                            }
                        ],
                        "entitlement": {
                            "status": "active",
                            "plan_code": "monthly",
                            "valid_from": "2026-02-21T00:00:00Z",
                            "valid_until": "2026-03-21T00:00:00Z",
                            "trial_ends_at": "2026-02-28T00:00:00Z",
                            "token_expires_at": "2026-02-21T01:00:00Z",
                            "metadata": {"billing_provider": "external-billing-app"},
                        },
                    }
                )
            raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(sync.httpx, "Client", _MockClient)

    ok = sync.sync_license_once()
    assert ok is True

    from shared.models import LicenseInstallation, Notification, SessionLocal

    with SessionLocal() as db:
        installation = db.execute(
            select(LicenseInstallation).where(LicenseInstallation.installation_id == "sync-notifications-installation")
        ).scalar_one()
        metadata = json.loads(installation.metadata_json or "{}")
        assert isinstance(metadata.get("control_plane_notifications"), list)
        assert metadata["control_plane_notifications"][0]["id"] == "cpn-test-notice"
        notification = db.execute(
            select(Notification)
            .where(Notification.dedupe_key == "license-notification:sync-notifications-installation:cpn-test-notice")
            .order_by(Notification.created_at.desc())
        ).scalars().first()
        assert notification is not None
        assert notification.notification_type == "AppUpdateAvailable"
        assert notification.is_read is False


def test_activate_with_code_once_sends_operating_system(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "activate-os.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    os.environ["LICENSE_ENFORCEMENT_ENABLED"] = "true"
    os.environ["LICENSE_INSTALLATION_ID"] = "activate-os-installation"
    os.environ["LICENSE_SERVER_TOKEN"] = "dev-license-token"
    os.environ["LICENSE_TRIAL_DAYS"] = "7"
    os.environ.pop("LICENSE_PUBLIC_KEY", None)

    import shared.models as shared_models
    import shared.licensing as shared_licensing
    import shared.settings as shared_settings

    reload(shared_settings)
    reload(shared_models)
    reload(shared_licensing)
    shared_licensing.reset_license_installation_id_cache()

    import main

    main = reload(main)
    main.bootstrap_data()

    from features.licensing import sync

    sync = reload(sync)
    monkeypatch.setattr(sync, "_resolve_local_operating_system", lambda: "windows-test")
    captured_activate_payload: dict[str, Any] = {}

    class _MockResponse:
        def __init__(self, payload: dict):
            self._payload = payload
            self.status_code = 200

        def json(self):
            return self._payload

    class _MockClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, headers: dict, json: dict):
            if not url.endswith("/v1/installations/activate"):
                raise AssertionError(f"Unexpected URL: {url}")
            captured_activate_payload.update(json)
            return _MockResponse(
                {
                    "ok": True,
                    "entitlement": {
                        "status": "active",
                        "plan_code": "monthly",
                        "valid_from": "2026-02-21T00:00:00Z",
                        "valid_until": "2026-03-21T00:00:00Z",
                        "trial_ends_at": "2026-02-28T00:00:00Z",
                        "token_expires_at": "2026-02-21T01:00:00Z",
                        "metadata": {"source": "test"},
                    },
                }
            )

    monkeypatch.setattr(sync.httpx, "Client", _MockClient)

    result = sync.activate_with_code_once("ACT-TEST-0001-0002-0003")
    assert isinstance(result, dict)
    assert captured_activate_payload["operating_system"] == "windows-test"


def test_sync_license_once_accepts_valid_signed_token(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "signed.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    os.environ["LICENSE_ENFORCEMENT_ENABLED"] = "true"
    os.environ["LICENSE_INSTALLATION_ID"] = "signed-installation"
    os.environ["LICENSE_SERVER_TOKEN"] = "dev-license-token"
    os.environ["LICENSE_TRIAL_DAYS"] = "7"

    public_key_pem, private_key = _create_ed25519_keypair()
    os.environ["LICENSE_PUBLIC_KEY"] = public_key_pem

    import shared.models as shared_models
    import shared.licensing as shared_licensing
    import shared.settings as shared_settings

    reload(shared_settings)
    reload(shared_models)
    reload(shared_licensing)
    shared_licensing.reset_license_installation_id_cache()

    import main

    main = reload(main)
    main.bootstrap_data()

    from features.licensing import sync

    sync = reload(sync)

    entitlement_payload = {
        "installation_id": "signed-installation",
        "status": "active",
        "plan_code": "monthly",
        "valid_from": "2026-02-21T00:00:00Z",
        "valid_until": "2026-03-21T00:00:00Z",
        "trial_ends_at": "2026-02-28T00:00:00Z",
        "token_expires_at": "2026-02-21T01:00:00Z",
        "metadata": {"billing_provider": "external-billing-app"},
    }
    signed_token = _sign_token_payload(entitlement_payload, private_key)

    class _MockResponse:
        def __init__(self, payload: dict):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _MockClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, headers: dict, json: dict):
            if url.endswith("/v1/installations/register"):
                return _MockResponse({"ok": True})
            if url.endswith("/v1/installations/heartbeat"):
                return _MockResponse({"ok": True, "entitlement_token": signed_token})
            raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(sync.httpx, "Client", _MockClient)

    ok = sync.sync_license_once()
    assert ok is True

    from shared.models import LicenseInstallation, SessionLocal

    with SessionLocal() as db:
        installation = db.execute(
            select(LicenseInstallation).where(LicenseInstallation.installation_id == "signed-installation")
        ).scalar_one()
        assert installation.status == "active"
        assert installation.plan_code == "monthly"


def test_sync_license_once_rejects_invalid_signed_token(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "invalid-signature.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    os.environ["LICENSE_ENFORCEMENT_ENABLED"] = "true"
    os.environ["LICENSE_INSTALLATION_ID"] = "invalid-signature-installation"
    os.environ["LICENSE_SERVER_TOKEN"] = "dev-license-token"
    os.environ["LICENSE_TRIAL_DAYS"] = "7"

    public_key_pem, private_key = _create_ed25519_keypair()
    os.environ["LICENSE_PUBLIC_KEY"] = public_key_pem

    import shared.models as shared_models
    import shared.licensing as shared_licensing
    import shared.settings as shared_settings

    reload(shared_settings)
    reload(shared_models)
    reload(shared_licensing)
    shared_licensing.reset_license_installation_id_cache()

    import main

    main = reload(main)
    main.bootstrap_data()

    from features.licensing import sync

    sync = reload(sync)

    entitlement_payload = {
        "installation_id": "invalid-signature-installation",
        "status": "active",
        "plan_code": "monthly",
        "valid_from": "2026-02-21T00:00:00Z",
        "valid_until": "2026-03-21T00:00:00Z",
        "trial_ends_at": "2026-02-28T00:00:00Z",
        "token_expires_at": "2026-02-21T01:00:00Z",
        "metadata": {"billing_provider": "external-billing-app"},
    }
    signed_token = _sign_token_payload(entitlement_payload, private_key)
    signed_token["signature"] = signed_token["signature"][:-2] + "zz"

    class _MockResponse:
        def __init__(self, payload: dict):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _MockClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, headers: dict, json: dict):
            if url.endswith("/v1/installations/register"):
                return _MockResponse({"ok": True})
            if url.endswith("/v1/installations/heartbeat"):
                return _MockResponse({"ok": True, "entitlement_token": signed_token})
            raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(sync.httpx, "Client", _MockClient)

    ok = sync.sync_license_once()
    assert ok is False

    from shared.models import LicenseInstallation, LicenseValidationLog, SessionLocal

    with SessionLocal() as db:
        installation = db.execute(
            select(LicenseInstallation).where(LicenseInstallation.installation_id == "invalid-signature-installation")
        ).scalar_one()
        assert installation.status in {"trial", "unlicensed", "expired"}

        validation = db.execute(
            select(LicenseValidationLog)
            .where(LicenseValidationLog.installation_id == installation.id)
            .order_by(LicenseValidationLog.id.desc())
        ).scalars().first()
        assert validation is not None
        assert validation.result == "error"


def test_sync_license_once_marks_expired_on_seat_limit_rejection(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "seat-limit-rejection.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    os.environ["LICENSE_ENFORCEMENT_ENABLED"] = "true"
    os.environ["LICENSE_INSTALLATION_ID"] = "seat-limit-installation"
    os.environ["LICENSE_SERVER_TOKEN"] = "dev-license-token"
    os.environ["LICENSE_TRIAL_DAYS"] = "7"
    os.environ.pop("LICENSE_PUBLIC_KEY", None)

    import shared.models as shared_models
    import shared.licensing as shared_licensing
    import shared.settings as shared_settings

    reload(shared_settings)
    reload(shared_models)
    reload(shared_licensing)
    shared_licensing.reset_license_installation_id_cache()

    import main

    main = reload(main)
    main.bootstrap_data()

    from features.licensing import sync

    sync = reload(sync)

    class _MockResponse:
        def __init__(self, *, url: str, status_code: int, payload: dict | None = None):
            self.url = url
            self.status_code = int(status_code)
            self._payload = payload or {}
            self._request = httpx.Request("POST", self.url)
            self._response = httpx.Response(self.status_code, request=self._request, json=self._payload)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"HTTP {self.status_code}",
                    request=self._request,
                    response=self._response,
                )

        def json(self):
            return self._payload

        @property
        def text(self) -> str:
            return json.dumps(self._payload)

    class _MockClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, headers: dict, json: dict):
            if url.endswith("/v1/installations/register"):
                return _MockResponse(
                    url=url,
                    status_code=409,
                    payload={"detail": "Seat limit exceeded (3/3) for customer customer-seat-limit"},
                )
            raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(sync.httpx, "Client", _MockClient)

    ok = sync.sync_license_once()
    assert ok is False

    from features.licensing.read_models import license_status_read_model
    from shared.models import LicenseInstallation, LicenseValidationLog, SessionLocal

    with SessionLocal() as db:
        payload = license_status_read_model(db)
        assert payload["status"] == "expired"
        assert payload["write_access"] is False
        assert payload["metadata"].get("control_plane_last_error_code") == 409
        assert "Seat limit exceeded" in str(payload["metadata"].get("control_plane_last_error_detail") or "")

        installation = db.execute(
            select(LicenseInstallation).where(LicenseInstallation.installation_id == "seat-limit-installation")
        ).scalar_one()
        assert installation.status == "expired"
        assert installation.trial_ends_at is not None
        trial_ends_at = installation.trial_ends_at
        if trial_ends_at.tzinfo is None:
            trial_ends_at = trial_ends_at.replace(tzinfo=timezone.utc)
        assert trial_ends_at <= datetime.now(timezone.utc) - timedelta(hours=1)

        validation = db.execute(
            select(LicenseValidationLog)
            .where(LicenseValidationLog.installation_id == installation.id)
            .order_by(LicenseValidationLog.id.desc())
        ).scalars().first()
        assert validation is not None
        assert validation.result == "error"
        assert "hard_rejection" in (validation.details_json or "")


def test_assert_license_startup_write_access_allows_trial(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "startup-trial.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.setenv("EVENTSTORE_URI", "")
    monkeypatch.setenv("LICENSE_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setenv("LICENSE_INSTALLATION_ID", "startup-trial-installation")
    monkeypatch.setenv("LICENSE_TRIAL_DAYS", "7")
    monkeypatch.delenv("LICENSE_PUBLIC_KEY", raising=False)

    import shared.models as shared_models
    import shared.licensing as shared_licensing
    import shared.settings as shared_settings

    reload(shared_settings)
    reload(shared_models)
    reload(shared_licensing)
    shared_licensing.reset_license_installation_id_cache()

    import main

    main = reload(main)
    main.bootstrap_data()

    from features.licensing import sync

    sync = reload(sync)
    payload = sync.assert_license_startup_write_access()
    assert payload["status"] in {"trial", "active", "grace"}
    assert payload["write_access"] is True


def test_assert_license_startup_write_access_raises_when_expired(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "startup-expired.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.setenv("EVENTSTORE_URI", "")
    monkeypatch.setenv("LICENSE_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setenv("LICENSE_INSTALLATION_ID", "startup-expired-installation")
    monkeypatch.setenv("LICENSE_TRIAL_DAYS", "7")
    monkeypatch.delenv("LICENSE_PUBLIC_KEY", raising=False)

    import shared.models as shared_models
    import shared.licensing as shared_licensing
    import shared.settings as shared_settings

    reload(shared_settings)
    reload(shared_models)
    reload(shared_licensing)
    shared_licensing.reset_license_installation_id_cache()

    import main

    main = reload(main)
    main.bootstrap_data()

    from shared.models import LicenseInstallation, SessionLocal

    with SessionLocal() as db:
        installation = db.execute(
            select(LicenseInstallation).where(LicenseInstallation.installation_id == "startup-expired-installation")
        ).scalar_one()
        installation.status = "trial"
        installation.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=10)
        db.commit()

    from features.licensing import sync

    sync = reload(sync)
    try:
        sync.assert_license_startup_write_access()
        assert False, "Expected LicenseStartupError"
    except sync.LicenseStartupError as exc:
        assert "status=expired" in str(exc)
