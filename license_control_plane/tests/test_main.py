from __future__ import annotations

import os
from importlib import reload
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient


def _generate_private_key_pem() -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


def _build_client(tmp_path: Path, *, private_key_pem: str = "") -> TestClient:
    db_file = tmp_path / "control-plane.db"
    os.environ["LCP_DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["LCP_API_TOKEN"] = "control-plane-token"
    os.environ["LCP_TRIAL_DAYS"] = "7"
    os.environ["LCP_TOKEN_TTL_SECONDS"] = "3600"
    os.environ["LCP_SIGNING_PRIVATE_KEY_PEM"] = private_key_pem
    os.environ["LCP_SIGNING_KEY_ID"] = "test-key"
    os.environ["LCP_REQUIRE_SIGNED_TOKENS"] = "false"

    import license_control_plane.main as lcp_main

    lcp_main = reload(lcp_main)
    return TestClient(lcp_main.app)


def test_register_returns_signed_entitlement_when_signing_key_is_configured(tmp_path: Path):
    private_key_pem, public_key_pem = _generate_private_key_pem()
    with _build_client(tmp_path, private_key_pem=private_key_pem) as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-signed-installation",
                "workspace_id": "workspace-a",
                "metadata": {"source": "test"},
            },
        )
        assert register.status_code == 200
        payload = register.json()
        assert payload["ok"] is True
        assert isinstance(payload.get("entitlement"), dict)
        assert isinstance(payload.get("entitlement_token"), dict)

        from features.licensing.token_crypto import verify_entitlement_token

        verified = verify_entitlement_token(payload["entitlement_token"], public_key_pem)
        assert verified["installation_id"] == "cp-signed-installation"


def test_admin_subscription_update_changes_installation_status(tmp_path: Path):
    with _build_client(tmp_path) as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-external-billing-installation",
                "workspace_id": "workspace-a",
                "metadata": {"source": "test"},
            },
        )
        assert register.status_code == 200

        update = client.put(
            "/v1/admin/installations/cp-external-billing-installation/subscription",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "subscription_status": "active",
                "customer_ref": "customer-001",
                "valid_until": "2026-03-21T00:00:00Z",
                "metadata": {"billing_sync_source": "external-billing-app"},
                "plan_code": "monthly",
            },
        )
        assert update.status_code == 200
        update_payload = update.json()
        assert update_payload["ok"] is True
        assert update_payload["subscription_status"] == "active"
        assert update_payload["entitlement"]["status"] == "active"

        get_installation = client.get(
            "/v1/admin/installations/cp-external-billing-installation",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert get_installation.status_code == 200
        installation_payload = get_installation.json()["installation"]
        assert installation_payload["subscription_status"] == "active"
        assert installation_payload["plan_code"] == "monthly"
        assert installation_payload["metadata"].get("billing_sync_source") == "external-billing-app"


def test_admin_list_installations_supports_search_and_status_filter(tmp_path: Path):
    with _build_client(tmp_path) as client:
        first = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-tenant-alpha",
                "workspace_id": "workspace-a",
                "metadata": {"source": "test"},
            },
        )
        assert first.status_code == 200

        second = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-tenant-beta",
                "workspace_id": "workspace-b",
                "metadata": {"source": "test"},
            },
        )
        assert second.status_code == 200

        update = client.put(
            "/v1/admin/installations/cp-tenant-beta/subscription",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "subscription_status": "active",
                "plan_code": "monthly",
                "customer_ref": "beta-customer",
                "valid_until": "2026-12-31T00:00:00Z",
                "metadata": {"billing_sync_source": "external-billing-app"},
            },
        )
        assert update.status_code == 200

        listed = client.get(
            "/v1/admin/installations?q=beta&status=active&limit=10&offset=0",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert listed.status_code == 200
        payload = listed.json()
        assert payload["ok"] is True
        assert payload["total"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["installation"]["installation_id"] == "cp-tenant-beta"
