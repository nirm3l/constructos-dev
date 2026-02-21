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


def test_activation_code_flow_enforces_three_device_limit(tmp_path: Path):
    with _build_client(tmp_path) as client:
        create_code = client.post(
            "/v1/admin/activation-codes",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-seat-limit",
                "plan_code": "monthly",
                "valid_until": "2026-12-31T00:00:00Z",
                "max_installations": 3,
                "metadata": {"issued_by": "tests"},
            },
        )
        assert create_code.status_code == 200
        code_payload = create_code.json()
        assert code_payload["ok"] is True
        activation_code = code_payload["activation_code"]
        assert isinstance(activation_code, str)
        assert activation_code.startswith("ACT-")

        for installation_id in ["cp-seat-1", "cp-seat-2", "cp-seat-3"]:
            activate = client.post(
                "/v1/installations/activate",
                headers={"Authorization": "Bearer control-plane-token"},
                json={
                    "installation_id": installation_id,
                    "workspace_id": "workspace-seat",
                    "activation_code": activation_code,
                    "metadata": {"source": "integration-test"},
                },
            )
            assert activate.status_code == 200
            body = activate.json()
            assert body["ok"] is True
            assert body["entitlement"]["status"] == "active"
            assert body["seat_usage"]["max_installations"] == 3

        fourth = client.post(
            "/v1/installations/activate",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-seat-4",
                "workspace_id": "workspace-seat",
                "activation_code": activation_code,
                "metadata": {"source": "integration-test"},
            },
        )
        assert fourth.status_code == 409
        assert "Seat limit exceeded (3/3)" in fourth.json()["detail"]

        list_codes = client.get(
            "/v1/admin/activation-codes?customer_ref=customer-seat-limit",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert list_codes.status_code == 200
        list_payload = list_codes.json()
        assert list_payload["ok"] is True
        assert list_payload["total"] == 1
        assert list_payload["items"][0]["usage_count"] == 3


def test_client_token_allows_installation_endpoints_and_blocks_admin_endpoints(tmp_path: Path):
    with _build_client(tmp_path) as client:
        create_client_token = client.post(
            "/v1/admin/client-tokens",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-client-token",
                "metadata": {"source": "tests"},
            },
        )
        assert create_client_token.status_code == 200
        client_token_payload = create_client_token.json()
        assert client_token_payload["ok"] is True
        client_token = client_token_payload["client_token"]
        assert isinstance(client_token, str)
        assert client_token.startswith("lcp_")

        create_code = client.post(
            "/v1/admin/activation-codes",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-client-token",
                "plan_code": "monthly",
                "valid_until": "2026-12-31T00:00:00Z",
                "max_installations": 3,
                "metadata": {"source": "tests"},
            },
        )
        assert create_code.status_code == 200
        activation_code = create_code.json()["activation_code"]

        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": f"Bearer {client_token}"},
            json={
                "installation_id": "cp-client-token-installation",
                "workspace_id": "workspace-client-token",
                "metadata": {"source": "tests"},
            },
        )
        assert register.status_code == 200
        register_payload = register.json()
        assert register_payload["ok"] is True
        assert register_payload["installation"]["customer_ref"] == "customer-client-token"

        activate = client.post(
            "/v1/installations/activate",
            headers={"Authorization": f"Bearer {client_token}"},
            json={
                "installation_id": "cp-client-token-installation",
                "workspace_id": "workspace-client-token",
                "activation_code": activation_code,
                "metadata": {"source": "tests"},
            },
        )
        assert activate.status_code == 200
        activate_payload = activate.json()
        assert activate_payload["ok"] is True
        assert activate_payload["entitlement"]["status"] == "active"

        forbidden_admin = client.get(
            "/v1/admin/installations",
            headers={"Authorization": f"Bearer {client_token}"},
        )
        assert forbidden_admin.status_code == 401

        wrong_customer_code = client.post(
            "/v1/admin/activation-codes",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-other",
                "plan_code": "monthly",
                "valid_until": "2026-12-31T00:00:00Z",
                "max_installations": 3,
                "metadata": {"source": "tests"},
            },
        )
        assert wrong_customer_code.status_code == 200
        wrong_code = wrong_customer_code.json()["activation_code"]

        wrong_activate = client.post(
            "/v1/installations/activate",
            headers={"Authorization": f"Bearer {client_token}"},
            json={
                "installation_id": "cp-client-token-installation",
                "workspace_id": "workspace-client-token",
                "activation_code": wrong_code,
                "metadata": {"source": "tests"},
            },
        )
        assert wrong_activate.status_code == 403
