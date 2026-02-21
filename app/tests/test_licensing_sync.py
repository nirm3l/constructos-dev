from __future__ import annotations

import os
import json
import base64
from importlib import reload
from pathlib import Path

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
    os.environ["LICENSE_SERVER_URL"] = "http://license-control-plane:8092"
    os.environ["LICENSE_SERVER_TOKEN"] = "dev-license-token"
    os.environ["LICENSE_TRIAL_DAYS"] = "7"
    os.environ.pop("LICENSE_PUBLIC_KEY", None)

    import shared.models as shared_models
    import shared.settings as shared_settings

    reload(shared_settings)
    reload(shared_models)

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


def test_sync_license_once_accepts_valid_signed_token(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "signed.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    os.environ["LICENSE_ENFORCEMENT_ENABLED"] = "true"
    os.environ["LICENSE_INSTALLATION_ID"] = "signed-installation"
    os.environ["LICENSE_SERVER_URL"] = "http://license-control-plane:8092"
    os.environ["LICENSE_SERVER_TOKEN"] = "dev-license-token"
    os.environ["LICENSE_TRIAL_DAYS"] = "7"

    public_key_pem, private_key = _create_ed25519_keypair()
    os.environ["LICENSE_PUBLIC_KEY"] = public_key_pem

    import shared.models as shared_models
    import shared.settings as shared_settings

    reload(shared_settings)
    reload(shared_models)

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
    os.environ["LICENSE_SERVER_URL"] = "http://license-control-plane:8092"
    os.environ["LICENSE_SERVER_TOKEN"] = "dev-license-token"
    os.environ["LICENSE_TRIAL_DAYS"] = "7"

    public_key_pem, private_key = _create_ed25519_keypair()
    os.environ["LICENSE_PUBLIC_KEY"] = public_key_pem

    import shared.models as shared_models
    import shared.settings as shared_settings

    reload(shared_settings)
    reload(shared_models)

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
