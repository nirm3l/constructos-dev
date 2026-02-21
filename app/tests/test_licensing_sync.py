from __future__ import annotations

import os
from importlib import reload
from pathlib import Path

from sqlalchemy import select


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
                            "metadata": {"billing_provider": "monri"},
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
