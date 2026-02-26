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


def _build_client(
    tmp_path: Path,
    *,
    private_key_pem: str = "",
    public_beta_free_until: str = "",
    beta_plan_valid_until: str = "",
    client_token_bundle_password: str = "",
    client_token_delimiter: str = ".",
    client_token_bundle_segment_index: int = 2,
    customer_ref_secret: str = "",
) -> TestClient:
    db_file = tmp_path / "control-plane.db"
    os.environ["LCP_DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["LCP_API_TOKEN"] = "control-plane-token"
    os.environ["LCP_TRIAL_DAYS"] = "7"
    os.environ["LCP_TOKEN_TTL_SECONDS"] = "3600"
    os.environ["LCP_SIGNING_PRIVATE_KEY_PEM"] = private_key_pem
    os.environ["LCP_SIGNING_KEY_ID"] = "test-key"
    os.environ["LCP_REQUIRE_SIGNED_TOKENS"] = "false"
    os.environ["LCP_PUBLIC_BETA_FREE_UNTIL"] = public_beta_free_until
    os.environ["LCP_BETA_PLAN_VALID_UNTIL"] = beta_plan_valid_until
    os.environ["APP_BUNDLE_PASSWORD"] = ""
    os.environ["LCP_CLIENT_TOKEN_BUNDLE_PASSWORD"] = client_token_bundle_password
    os.environ["LCP_CLIENT_TOKEN_DELIMITER"] = client_token_delimiter
    os.environ["LCP_CLIENT_TOKEN_BUNDLE_SEGMENT_INDEX"] = str(client_token_bundle_segment_index)
    os.environ["LCP_EMAIL_RESEND_API_KEY"] = ""
    os.environ["LCP_EMAIL_FROM"] = ""
    os.environ["LCP_EMAIL_REPLY_TO"] = ""
    os.environ["LCP_CUSTOMER_REF_SECRET"] = customer_ref_secret

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


def test_admin_subscription_update_lifetime_clears_valid_until(tmp_path: Path):
    with _build_client(tmp_path) as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-lifetime-installation",
                "workspace_id": "workspace-lifetime",
                "metadata": {"source": "test"},
            },
        )
        assert register.status_code == 200

        update = client.put(
            "/v1/admin/installations/cp-lifetime-installation/subscription",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "subscription_status": "lifetime",
                "customer_ref": "customer-lifetime",
                "valid_until": "2026-12-31T00:00:00Z",
                "plan_code": "lifetime",
            },
        )
        assert update.status_code == 200
        payload = update.json()
        assert payload["ok"] is True
        assert payload["subscription_status"] == "lifetime"
        assert payload["entitlement"]["status"] == "active"
        assert payload["entitlement"]["plan_code"] == "lifetime"
        assert payload["entitlement"]["valid_until"] is None

        get_installation = client.get(
            "/v1/admin/installations/cp-lifetime-installation",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert get_installation.status_code == 200
        installation_payload = get_installation.json()["installation"]
        assert installation_payload["subscription_status"] == "lifetime"
        assert installation_payload["plan_code"] == "lifetime"
        assert installation_payload["subscription_valid_until"] is None


def test_admin_subscription_update_rejects_invalid_status_plan_mapping(tmp_path: Path):
    with _build_client(tmp_path) as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-invalid-plan-mapping",
                "workspace_id": "workspace-invalid",
                "customer_ref": "customer-invalid",
                "metadata": {"source": "test"},
            },
        )
        assert register.status_code == 200

        update = client.put(
            "/v1/admin/installations/cp-invalid-plan-mapping/subscription",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "subscription_status": "active",
                "plan_code": "beta",
                "customer_ref": "customer-invalid",
                "valid_until": "2026-12-31T00:00:00Z",
            },
        )
        assert update.status_code == 400
        assert "is not allowed when subscription_status is 'active'" in update.json()["detail"]


def test_admin_subscription_update_canonicalizes_legacy_status_aliases(tmp_path: Path):
    with _build_client(tmp_path) as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-legacy-status-alias",
                "workspace_id": "workspace-legacy",
                "customer_ref": "customer-legacy",
                "metadata": {"source": "test"},
            },
        )
        assert register.status_code == 200

        update_grace = client.put(
            "/v1/admin/installations/cp-legacy-status-alias/subscription",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "subscription_status": "past_due",
                "plan_code": "monthly",
                "customer_ref": "customer-legacy",
                "valid_until": "2026-12-31T00:00:00Z",
            },
        )
        assert update_grace.status_code == 200
        assert update_grace.json()["subscription_status"] == "grace"
        assert update_grace.json()["entitlement"]["status"] == "grace"

        update_none = client.put(
            "/v1/admin/installations/cp-legacy-status-alias/subscription",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "subscription_status": "canceled",
                "plan_code": None,
                "customer_ref": "customer-legacy",
                "valid_until": None,
            },
        )
        assert update_none.status_code == 200
        assert update_none.json()["subscription_status"] == "none"
        assert update_none.json()["entitlement"]["plan_code"] is None
        assert update_none.json()["entitlement"]["valid_until"] is None

        get_installation = client.get(
            "/v1/admin/installations/cp-legacy-status-alias",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert get_installation.status_code == 200
        assert get_installation.json()["installation"]["subscription_status"] == "none"
        assert get_installation.json()["installation"]["plan_code"] is None
        assert get_installation.json()["installation"]["subscription_valid_until"] is None


def test_admin_list_installations_status_filter_matches_legacy_rows(tmp_path: Path):
    with _build_client(tmp_path) as client:
        for installation_id in ["cp-legacy-grace", "cp-legacy-none"]:
            register = client.post(
                "/v1/installations/register",
                headers={"Authorization": "Bearer control-plane-token"},
                json={
                    "installation_id": installation_id,
                    "workspace_id": "workspace-legacy-filter",
                    "customer_ref": "customer-legacy-filter",
                    "metadata": {"source": "test"},
                },
            )
            assert register.status_code == 200

        import license_control_plane.main as lcp_main

        with lcp_main.SessionLocal() as db:
            grace_installation = db.execute(
                lcp_main.select(lcp_main.Installation).where(
                    lcp_main.Installation.installation_id == "cp-legacy-grace"
                )
            ).scalar_one()
            grace_installation.subscription_status = "past_due"

            none_installation = db.execute(
                lcp_main.select(lcp_main.Installation).where(
                    lcp_main.Installation.installation_id == "cp-legacy-none"
                )
            ).scalar_one()
            none_installation.subscription_status = "canceled"
            db.commit()

        filtered_grace = client.get(
            "/v1/admin/installations?status=grace&limit=50&offset=0",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert filtered_grace.status_code == 200
        grace_payload = filtered_grace.json()
        grace_ids = {item["installation"]["installation_id"] for item in grace_payload["items"]}
        assert "cp-legacy-grace" in grace_ids

        filtered_none = client.get(
            "/v1/admin/installations?status=none&limit=50&offset=0",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert filtered_none.status_code == 200
        none_payload = filtered_none.json()
        none_ids = {item["installation"]["installation_id"] for item in none_payload["items"]}
        assert "cp-legacy-none" in none_ids


def test_admin_delete_installation_removes_record_permanently(tmp_path: Path):
    with _build_client(tmp_path) as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-delete-installation",
                "workspace_id": "workspace-delete",
                "customer_ref": "customer-delete",
                "metadata": {"source": "test"},
            },
        )
        assert register.status_code == 200

        deleted = client.delete(
            "/v1/admin/installations/cp-delete-installation",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert deleted.status_code == 200
        deleted_payload = deleted.json()
        assert deleted_payload["ok"] is True
        assert deleted_payload["installation_id"] == "cp-delete-installation"

        get_installation = client.get(
            "/v1/admin/installations/cp-delete-installation",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert get_installation.status_code == 404

        listed = client.get(
            "/v1/admin/installations",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert listed.status_code == 200
        ids = {item["installation"]["installation_id"] for item in listed.json()["items"]}
        assert "cp-delete-installation" not in ids


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


def test_admin_installation_includes_customer_email_from_metadata(tmp_path: Path):
    with _build_client(tmp_path) as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-customer-email",
                "workspace_id": "workspace-customer-email",
                "metadata": {
                    "source": "test",
                    "issued_to_email": "Owner@Example.com",
                },
            },
        )
        assert register.status_code == 200
        register_payload = register.json()
        assert register_payload["installation"]["customer_email"] == "owner@example.com"
        assert register_payload["installation"]["created_at"]

        listed = client.get(
            "/v1/admin/installations?limit=50&offset=0",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert listed.status_code == 200
        listed_payload = listed.json()
        listed_item = next(
            item
            for item in listed_payload["items"]
            if item["installation"]["installation_id"] == "cp-customer-email"
        )
        assert listed_item["installation"]["customer_email"] == "owner@example.com"
        assert listed_item["installation"]["created_at"]

        details = client.get(
            "/v1/admin/installations/cp-customer-email",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert details.status_code == 200
        detail_payload = details.json()
        assert detail_payload["installation"]["customer_email"] == "owner@example.com"
        assert detail_payload["installation"]["created_at"]


def test_admin_installation_customer_email_lookup_fallback_from_customer_ref(tmp_path: Path):
    with _build_client(tmp_path) as client:
        create_code = client.post(
            "/v1/admin/activation-codes",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-email-lookup",
                "plan_code": "monthly",
                "valid_until": "2026-12-31T00:00:00Z",
                "max_installations": 3,
                "metadata": {"issued_to_email": "lookup@example.com"},
            },
        )
        assert create_code.status_code == 200

        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-customer-email-lookup",
                "workspace_id": "workspace-customer-email-lookup",
                "customer_ref": "customer-email-lookup",
                "metadata": {"source": "tests"},
            },
        )
        assert register.status_code == 200
        register_payload = register.json()
        assert register_payload["installation"]["customer_email"] is None

        listed = client.get(
            "/v1/admin/installations?limit=50&offset=0",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert listed.status_code == 200
        listed_payload = listed.json()
        listed_item = next(
            item
            for item in listed_payload["items"]
            if item["installation"]["installation_id"] == "cp-customer-email-lookup"
        )
        assert listed_item["installation"]["customer_email"] == "lookup@example.com"
        assert listed_item["installation"]["created_at"]

        details = client.get(
            "/v1/admin/installations/cp-customer-email-lookup",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert details.status_code == 200
        detail_payload = details.json()
        assert detail_payload["installation"]["customer_email"] == "lookup@example.com"
        assert detail_payload["installation"]["created_at"]


def test_activation_propagates_customer_email_from_activation_code_metadata(tmp_path: Path):
    with _build_client(tmp_path) as client:
        waitlist = client.post(
            "/v1/public/waitlist",
            json={"email": "propagation@example.com", "source": "marketing-site"},
        )
        assert waitlist.status_code == 200

        contact = client.post(
            "/v1/public/contact-requests",
            json={
                "request_type": "onboarding",
                "email": "propagation@example.com",
                "source": "marketing-site",
            },
        )
        assert contact.status_code == 200

        create_code = client.post(
            "/v1/admin/activation-codes",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-email-propagation",
                "plan_code": "monthly",
                "valid_until": "2026-12-31T00:00:00Z",
                "max_installations": 3,
                "metadata": {"issued_to_email": "propagation@example.com"},
            },
        )
        assert create_code.status_code == 200
        activation_code = create_code.json()["activation_code"]

        activate = client.post(
            "/v1/installations/activate",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-email-propagation",
                "workspace_id": "workspace-email-propagation",
                "activation_code": activation_code,
                "metadata": {"source": "tests"},
            },
        )
        assert activate.status_code == 200
        activate_payload = activate.json()
        assert activate_payload["installation"]["customer_email"] == "propagation@example.com"
        assert activate_payload["lead_status_updates"]["updated_total"] == 2
        assert activate_payload["lead_status_updates"]["updated_waitlist"] == 1
        assert activate_payload["lead_status_updates"]["updated_contact_requests"] == 1

        details = client.get(
            "/v1/admin/installations/cp-email-propagation",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert details.status_code == 200
        detail_payload = details.json()
        assert detail_payload["installation"]["customer_email"] == "propagation@example.com"

        waitlist_list = client.get(
            "/v1/admin/waitlist?q=propagation@example.com",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert waitlist_list.status_code == 200
        waitlist_payload = waitlist_list.json()
        assert waitlist_payload["total"] == 1
        assert waitlist_payload["items"][0]["status"] == "converted"

        contact_list = client.get(
            "/v1/admin/contact-requests?q=propagation@example.com",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert contact_list.status_code == 200
        contact_payload = contact_list.json()
        assert contact_payload["total"] == 1
        assert contact_payload["items"][0]["status"] == "converted"


def test_startup_backfills_customer_email_for_existing_installations(tmp_path: Path):
    with _build_client(tmp_path) as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-email-backfill",
                "workspace_id": "workspace-email-backfill",
                "customer_ref": "customer-email-backfill",
                "metadata": {"source": "tests"},
            },
        )
        assert register.status_code == 200
        assert register.json()["installation"]["customer_email"] is None

        create_code = client.post(
            "/v1/admin/activation-codes",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-email-backfill",
                "plan_code": "monthly",
                "valid_until": "2026-12-31T00:00:00Z",
                "max_installations": 3,
                "metadata": {"issued_to_email": "backfill@example.com"},
            },
        )
        assert create_code.status_code == 200

    with _build_client(tmp_path) as client:
        details = client.get(
            "/v1/admin/installations/cp-email-backfill",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert details.status_code == 200
        payload = details.json()
        assert payload["installation"]["customer_email"] == "backfill@example.com"
        assert payload["installation"]["metadata"]["customer_email_backfilled"] is True


def test_admin_customer_subscription_update_applies_to_all_installations(tmp_path: Path):
    with _build_client(tmp_path) as client:
        for installation_id in ["cp-customer-a1", "cp-customer-a2"]:
            register = client.post(
                "/v1/installations/register",
                headers={"Authorization": "Bearer control-plane-token"},
                json={
                    "installation_id": installation_id,
                    "workspace_id": "workspace-customer-a",
                    "metadata": {"source": "test"},
                },
            )
            assert register.status_code == 200
            assign_customer = client.put(
                f"/v1/admin/installations/{installation_id}/subscription",
                headers={"Authorization": "Bearer control-plane-token"},
                json={
                    "subscription_status": "active",
                    "plan_code": "monthly",
                    "customer_ref": "customer-a",
                    "valid_until": "2026-12-31T00:00:00Z",
                },
            )
            assert assign_customer.status_code == 200

        bulk_update = client.put(
            "/v1/admin/customers/customer-a/subscription",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "subscription_status": "lifetime",
                "plan_code": "lifetime",
                "valid_until": None,
            },
        )
        assert bulk_update.status_code == 200
        bulk_payload = bulk_update.json()
        assert bulk_payload["ok"] is True
        assert bulk_payload["customer_ref"] == "customer-a"
        assert bulk_payload["updated_installations"] == 2

        for installation_id in ["cp-customer-a1", "cp-customer-a2"]:
            get_installation = client.get(
                f"/v1/admin/installations/{installation_id}",
                headers={"Authorization": "Bearer control-plane-token"},
            )
            assert get_installation.status_code == 200
            payload = get_installation.json()
            assert payload["installation"]["subscription_status"] == "lifetime"
            assert payload["installation"]["subscription_valid_until"] is None
            assert payload["entitlement"]["status"] == "active"
            assert payload["entitlement"]["plan_code"] == "lifetime"


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
                headers={
                    "Authorization": "Bearer control-plane-token",
                    "X-Forwarded-For": "203.0.113.10",
                },
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
            assert body["installation"]["activation_ip"] == "203.0.113.10"

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


def test_register_auto_assigns_customer_ref_when_missing(tmp_path: Path):
    with _build_client(tmp_path) as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-auto-customer-installation",
                "workspace_id": "workspace-auto-customer",
                "metadata": {"source": "tests"},
            },
        )
        assert register.status_code == 200
        payload = register.json()
        assert payload["installation"]["customer_ref"] == "cust_unassigned"


def test_activation_code_lifetime_plan_maps_to_lifetime_subscription(tmp_path: Path):
    with _build_client(tmp_path, beta_plan_valid_until="2099-12-31T23:59:59Z") as client:
        create_code = client.post(
            "/v1/admin/activation-codes",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-lifetime-activation",
                "plan_code": "lifetime",
                "valid_until": "2026-12-31T00:00:00Z",
                "max_installations": 3,
            },
        )
        assert create_code.status_code == 200
        create_payload = create_code.json()
        activation_code = create_payload["activation_code"]
        assert create_payload["activation_code_record"]["plan_code"] == "lifetime"
        assert create_payload["activation_code_record"]["valid_until"] is None

        activate = client.post(
            "/v1/installations/activate",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-lifetime-seat-1",
                "workspace_id": "workspace-lifetime",
                "activation_code": activation_code,
            },
        )
        assert activate.status_code == 200
        payload = activate.json()
        assert payload["ok"] is True
        assert payload["entitlement"]["status"] == "active"
        assert payload["entitlement"]["plan_code"] == "lifetime"
        assert payload["entitlement"]["valid_until"] is None
        assert payload["installation"]["subscription_status"] == "lifetime"
        assert payload["installation"]["subscription_valid_until"] is None


def test_activation_code_trial_plan_is_auto_mapped_to_beta_subscription(tmp_path: Path):
    with _build_client(tmp_path, beta_plan_valid_until="2099-12-31T23:59:59Z") as client:
        create_code = client.post(
            "/v1/admin/activation-codes",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-trial-activation",
                "plan_code": "trial",
                "valid_until": "2026-12-31T00:00:00Z",
                "max_installations": 3,
            },
        )
        assert create_code.status_code == 200
        activation_code = create_code.json()["activation_code"]

        activate = client.post(
            "/v1/installations/activate",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-trial-seat-1",
                "workspace_id": "workspace-trial",
                "activation_code": activation_code,
            },
        )
        assert activate.status_code == 200
        payload = activate.json()
        assert payload["installation"]["subscription_status"] == "beta"
        assert payload["entitlement"]["plan_code"] == "beta"
        assert payload["entitlement"]["status"] == "active"
        assert payload["entitlement"]["valid_until"] == "2099-12-31T23:59:59+00:00"


def test_admin_subscription_update_none_clears_existing_trial_plan_state(tmp_path: Path):
    with _build_client(tmp_path) as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-none-clears-trial",
                "workspace_id": "workspace-none-clears-trial",
                "customer_ref": "customer-none-clears-trial",
                "metadata": {"source": "test"},
            },
        )
        assert register.status_code == 200

        set_trialing = client.put(
            "/v1/admin/installations/cp-none-clears-trial/subscription",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "subscription_status": "trialing",
                "plan_code": "trial",
                "customer_ref": "customer-none-clears-trial",
                "valid_until": "2026-12-31T00:00:00Z",
            },
        )
        assert set_trialing.status_code == 200
        assert set_trialing.json()["subscription_status"] == "trialing"

        set_none = client.put(
            "/v1/admin/installations/cp-none-clears-trial/subscription",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "subscription_status": "none",
                "customer_ref": "customer-none-clears-trial",
            },
        )
        assert set_none.status_code == 200
        payload = set_none.json()
        assert payload["subscription_status"] == "none"
        assert payload["entitlement"]["plan_code"] is None
        assert payload["entitlement"]["valid_until"] is None
        assert payload["entitlement"]["status"] == "expired"
        assert payload["entitlement"]["metadata"]["entitlement_reason"] == "subscription_none"

        get_installation = client.get(
            "/v1/admin/installations/cp-none-clears-trial",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert get_installation.status_code == 200
        installation_payload = get_installation.json()["installation"]
        assert installation_payload["subscription_status"] == "none"
        assert installation_payload["plan_code"] is None
        assert installation_payload["subscription_valid_until"] is None


def test_install_exchange_issues_client_token_for_activation_code(tmp_path: Path):
    with _build_client(tmp_path) as client:
        create_code = client.post(
            "/v1/admin/activation-codes",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-install-exchange",
                "plan_code": "monthly",
                "valid_until": "2026-12-31T00:00:00Z",
                "max_installations": 3,
                "metadata": {
                    "image_tag": "main",
                    "install_script_url": "https://raw.githubusercontent.com/nirm3l/constructos/main/install.sh",
                },
            },
        )
        assert create_code.status_code == 200
        activation_code = create_code.json()["activation_code"]

        exchange = client.post(
            "/v1/install/exchange",
            headers={"X-Forwarded-For": "203.0.113.27"},
            json={"activation_code": activation_code},
        )
        assert exchange.status_code == 200
        payload = exchange.json()
        assert payload["ok"] is True
        assert payload["customer_ref"] == "customer-install-exchange"
        assert str(payload["license_server_token"]).startswith("lcp_")
        assert payload["image_tag"] == "main"
        assert payload["install_script_url"] == "https://raw.githubusercontent.com/nirm3l/constructos/main/install.sh"
        assert payload["activation_code_record"]["metadata"]["install_exchange_count"] == 1
        assert payload["activation_code_record"]["metadata"]["install_exchange_last_ip"] == "203.0.113.27"

        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": f"Bearer {payload['license_server_token']}"},
            json={
                "installation_id": "cp-exchange-installation",
                "workspace_id": "workspace-exchange",
                "metadata": {"source": "tests"},
            },
        )
        assert register.status_code == 200
        assert register.json()["installation"]["customer_ref"] == "customer-install-exchange"

        second_exchange = client.post(
            "/v1/install/exchange",
            json={"activation_code": activation_code},
        )
        assert second_exchange.status_code == 200
        second_payload = second_exchange.json()
        assert str(second_payload["license_server_token"]).startswith("lcp_")
        assert second_payload["license_server_token"] != payload["license_server_token"]
        assert second_payload["activation_code_record"]["metadata"]["install_exchange_count"] == 2


def test_register_with_client_token_marks_onboarding_contact_as_converted(tmp_path: Path):
    with _build_client(tmp_path) as client:
        create_contact = client.post(
            "/v1/public/contact-requests",
            json={
                "request_type": "onboarding",
                "email": "convert-via-register@example.com",
                "source": "marketing-site",
            },
        )
        assert create_contact.status_code == 200
        assert create_contact.json()["contact_request"]["status"] == "pending"

        create_code = client.post(
            "/v1/admin/activation-codes",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-convert-register",
                "plan_code": "monthly",
                "valid_until": "2026-12-31T00:00:00Z",
                "max_installations": 3,
                "metadata": {"issued_to_email": "convert-via-register@example.com"},
            },
        )
        assert create_code.status_code == 200
        activation_code = create_code.json()["activation_code"]

        exchange = client.post(
            "/v1/install/exchange",
            json={"activation_code": activation_code},
        )
        assert exchange.status_code == 200
        client_token = exchange.json()["license_server_token"]

        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": f"Bearer {client_token}"},
            json={
                "installation_id": "cp-register-convert-1",
                "workspace_id": "workspace-register-convert",
                "metadata": {"source": "tests"},
            },
        )
        assert register.status_code == 200
        register_payload = register.json()
        assert register_payload["lead_status_updates"]["target_status"] == "converted"
        assert register_payload["lead_status_updates"]["updated_total"] == 1

        listed = client.get(
            "/v1/admin/contact-requests?q=convert-via-register@example.com&request_type=onboarding",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert listed.status_code == 200
        listed_payload = listed.json()
        assert listed_payload["total"] == 1
        assert listed_payload["items"][0]["status"] == "converted"


def test_install_exchange_register_lifetime_plan_sets_lifetime_subscription(tmp_path: Path):
    with _build_client(tmp_path) as client:
        create_code = client.post(
            "/v1/admin/activation-codes",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-install-lifetime",
                "plan_code": "lifetime",
                "valid_until": "2026-12-31T00:00:00Z",
                "max_installations": 3,
                "metadata": {"issued_to_email": "lifetime-register@example.com"},
            },
        )
        assert create_code.status_code == 200
        activation_code = create_code.json()["activation_code"]

        exchange = client.post(
            "/v1/install/exchange",
            json={"activation_code": activation_code},
        )
        assert exchange.status_code == 200
        client_token = exchange.json()["license_server_token"]

        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": f"Bearer {client_token}"},
            json={
                "installation_id": "cp-exchange-lifetime-1",
                "workspace_id": "workspace-exchange-lifetime",
                "metadata": {"source": "tests"},
            },
        )
        assert register.status_code == 200
        payload = register.json()
        assert payload["installation"]["subscription_status"] == "lifetime"
        assert payload["entitlement"]["status"] == "active"
        assert payload["entitlement"]["plan_code"] == "lifetime"
        assert payload["entitlement"]["valid_until"] is None

        details = client.get(
            "/v1/admin/installations/cp-exchange-lifetime-1",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert details.status_code == 200
        detail_payload = details.json()
        assert detail_payload["installation"]["subscription_status"] == "lifetime"
        assert detail_payload["installation"]["plan_code"] == "lifetime"
        assert detail_payload["installation"]["subscription_valid_until"] is None
        assert "beta_auto_assigned" not in detail_payload["installation"]["metadata"]


def test_install_exchange_register_enforces_customer_seat_limit(tmp_path: Path):
    with _build_client(tmp_path) as client:
        create_code = client.post(
            "/v1/admin/activation-codes",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-install-exchange-limit",
                "plan_code": "monthly",
                "valid_until": "2026-12-31T00:00:00Z",
                "max_installations": 3,
            },
        )
        assert create_code.status_code == 200
        activation_code = create_code.json()["activation_code"]

        for index in range(1, 4):
            exchange = client.post(
                "/v1/install/exchange",
                json={"activation_code": activation_code},
            )
            assert exchange.status_code == 200
            token = exchange.json()["license_server_token"]

            register = client.post(
                "/v1/installations/register",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "installation_id": f"cp-exchange-limit-{index}",
                    "workspace_id": "workspace-exchange-limit",
                    "metadata": {"source": "tests"},
                },
            )
            assert register.status_code == 200
            assert register.json()["installation"]["customer_ref"] == "customer-install-exchange-limit"

        re_register_existing = client.post(
            "/v1/installations/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "installation_id": "cp-exchange-limit-1",
                "workspace_id": "workspace-exchange-limit",
                "metadata": {"source": "tests"},
            },
        )
        assert re_register_existing.status_code == 200

        extra_exchange = client.post(
            "/v1/install/exchange",
            json={"activation_code": activation_code},
        )
        assert extra_exchange.status_code == 200
        extra_token = extra_exchange.json()["license_server_token"]

        fourth_register = client.post(
            "/v1/installations/register",
            headers={"Authorization": f"Bearer {extra_token}"},
            json={
                "installation_id": "cp-exchange-limit-4",
                "workspace_id": "workspace-exchange-limit",
                "metadata": {"source": "tests"},
            },
        )
        assert fourth_register.status_code == 409
        assert "Seat limit exceeded (3/3)" in fourth_register.json()["detail"]


def test_install_exchange_rejects_invalid_and_inactive_codes(tmp_path: Path):
    with _build_client(tmp_path) as client:
        invalid = client.post(
            "/v1/install/exchange",
            json={"activation_code": "ACT-INVALID-0000-0000-0000"},
        )
        assert invalid.status_code == 404
        assert invalid.json()["detail"] == "Invalid activation code"

        create_code = client.post(
            "/v1/admin/activation-codes",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-install-inactive",
                "plan_code": "monthly",
                "valid_until": "2026-12-31T00:00:00Z",
                "max_installations": 3,
            },
        )
        assert create_code.status_code == 200
        code_id = create_code.json()["activation_code_record"]["id"]
        activation_code = create_code.json()["activation_code"]

        deactivate = client.post(
            f"/v1/admin/activation-codes/{code_id}/deactivate",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert deactivate.status_code == 200

        inactive = client.post(
            "/v1/install/exchange",
            json={"activation_code": activation_code},
        )
        assert inactive.status_code == 400
        assert inactive.json()["detail"] == "Activation code is inactive"


def test_activation_code_trial_plan_requires_valid_until(tmp_path: Path):
    with _build_client(tmp_path) as client:
        create_code = client.post(
            "/v1/admin/activation-codes",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-trial-invalid",
                "plan_code": "trial",
                "max_installations": 3,
            },
        )
        assert create_code.status_code == 400
        assert "valid_until is required for trial plan_code" in create_code.json()["detail"]


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


def test_client_token_embeds_bundle_password_segment_when_configured(tmp_path: Path):
    with _build_client(tmp_path, client_token_bundle_password="bundle-pass-segment") as client:
        create_client_token = client.post(
            "/v1/admin/client-tokens",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "customer_ref": "customer-client-token",
                "metadata": {"source": "tests"},
            },
        )
        assert create_client_token.status_code == 200
        payload = create_client_token.json()
        assert payload["ok"] is True
        client_token = payload["client_token"]
        assert isinstance(client_token, str)
        segments = client_token.split(".")
        assert len(segments) >= 3
        assert segments[0].startswith("lcp_")
        assert segments[2] == "bundle-pass-segment"


def test_public_waitlist_join_creates_and_deduplicates_email(tmp_path: Path):
    with _build_client(tmp_path) as client:
        first = client.post(
            "/v1/public/waitlist",
            json={
                "email": "Engineer@Example.com",
                "source": "marketing-site",
                "metadata": {"campaign": "landing"},
            },
            headers={"User-Agent": "pytest-waitlist"},
        )
        assert first.status_code == 200
        first_payload = first.json()
        assert first_payload["ok"] is True
        assert first_payload["created"] is True
        assert first_payload["waitlist_entry"]["email"] == "engineer@example.com"
        assert first_payload["waitlist_entry"]["source"] == "marketing-site"

        second = client.post(
            "/v1/public/waitlist",
            json={
                "email": "engineer@example.com",
                "source": "marketing-site",
                "metadata": {"campaign": "landing-repeat"},
            },
        )
        assert second.status_code == 200
        second_payload = second.json()
        assert second_payload["ok"] is True
        assert second_payload["created"] is False
        assert second_payload["waitlist_entry"]["email"] == "engineer@example.com"

        listed = client.get(
            "/v1/admin/waitlist?q=engineer@example.com",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert listed.status_code == 200
        listed_payload = listed.json()
        assert listed_payload["ok"] is True
        assert listed_payload["total"] == 1
        assert listed_payload["items"][0]["email"] == "engineer@example.com"


def test_public_waitlist_join_rejects_invalid_email(tmp_path: Path):
    with _build_client(tmp_path) as client:
        invalid = client.post(
            "/v1/public/waitlist",
            json={"email": "not-an-email"},
        )
        assert invalid.status_code == 400
        assert invalid.json()["detail"] == "Invalid email format"


def test_public_contact_request_create_list_and_deduplicate(tmp_path: Path):
    with _build_client(tmp_path) as client:
        first = client.post(
            "/v1/public/contact-requests",
            json={
                "request_type": "onboarding",
                "email": "ops@example.com",
                "source": "marketing-site",
                "metadata": {"team_size": "6"},
            },
        )
        assert first.status_code == 200
        first_payload = first.json()
        assert first_payload["ok"] is True
        assert first_payload["created"] is True
        assert first_payload["contact_request"]["request_type"] == "onboarding"
        assert first_payload["contact_request"]["email"] == "ops@example.com"

        second = client.post(
            "/v1/public/contact-requests",
            json={
                "request_type": "onboarding",
                "email": "ops@example.com",
                "source": "marketing-site",
            },
        )
        assert second.status_code == 200
        second_payload = second.json()
        assert second_payload["ok"] is True
        assert second_payload["created"] is False

        demo = client.post(
            "/v1/public/contact-requests",
            json={
                "request_type": "demo",
                "email": "ops@example.com",
                "source": "marketing-site",
            },
        )
        assert demo.status_code == 200
        assert demo.json()["created"] is True

        listed = client.get(
            "/v1/admin/contact-requests?request_type=onboarding",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert listed.status_code == 200
        listed_payload = listed.json()
        assert listed_payload["ok"] is True
        assert listed_payload["total"] == 1
        assert listed_payload["items"][0]["request_type"] == "onboarding"


def test_public_contact_request_rejects_unsupported_request_type(tmp_path: Path):
    with _build_client(tmp_path) as client:
        invalid = client.post(
            "/v1/public/contact-requests",
            json={
                "request_type": "unknown_type",
                "email": "ops@example.com",
            },
        )
        assert invalid.status_code == 400
        assert "Unsupported request_type" in invalid.json()["detail"]


def test_register_auto_assigns_beta_subscription(tmp_path: Path):
    with _build_client(tmp_path, beta_plan_valid_until="2099-12-31T23:59:59Z") as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-beta-cutoff-only-installation",
                "workspace_id": "workspace-beta",
                "metadata": {"source": "tests"},
            },
        )
        assert register.status_code == 200
        payload = register.json()
        assert payload["installation"]["subscription_status"] == "beta"
        entitlement = payload["entitlement"]
        assert entitlement["status"] == "active"
        assert entitlement["plan_code"] == "beta"
        assert entitlement["valid_until"] == "2099-12-31T23:59:59+00:00"
        assert entitlement["metadata"]["entitlement_reason"] == "subscription_beta"

        health = client.get("/api/health")
        assert health.status_code == 200
        health_payload = health.json()
        assert health_payload["beta_plan_active"] is True
        assert health_payload["beta_plan_valid_until"] == "2099-12-31T23:59:59+00:00"
        assert health_payload["public_beta_active"] is True
        assert health_payload["public_beta_free_until"] == "2099-12-31T23:59:59+00:00"


def test_beta_subscription_status_grants_active_entitlement(tmp_path: Path):
    with _build_client(tmp_path, beta_plan_valid_until="2099-12-31T23:59:59Z") as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-beta-subscription-installation",
                "workspace_id": "workspace-beta",
                "metadata": {"source": "tests"},
            },
        )
        assert register.status_code == 200

        update = client.put(
            "/v1/admin/installations/cp-beta-subscription-installation/subscription",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "subscription_status": "beta",
                "plan_code": "beta",
                "customer_ref": "customer-beta",
                "valid_until": None,
            },
        )
        assert update.status_code == 200
        update_payload = update.json()
        assert update_payload["ok"] is True
        assert update_payload["subscription_status"] == "beta"
        assert update_payload["entitlement"]["status"] == "active"
        assert update_payload["entitlement"]["plan_code"] == "beta"
        assert update_payload["entitlement"]["valid_until"] == "2099-12-31T23:59:59+00:00"
        assert update_payload["entitlement"]["metadata"]["entitlement_reason"] == "subscription_beta"


def test_support_bug_report_create_deduplicate_and_admin_triage(tmp_path: Path):
    with _build_client(tmp_path) as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-bug-installation",
                "workspace_id": "workspace-bugs",
                "metadata": {"source": "tests"},
            },
        )
        assert register.status_code == 200

        first = client.post(
            "/v1/support/bug-reports",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-bug-installation",
                "workspace_id": "workspace-bugs",
                "source": "task-app-ui",
                "title": "Cannot save task from drawer",
                "description": "Save action returns 500 when description includes markdown table.",
                "steps_to_reproduce": "Open task drawer, paste table, click save.",
                "expected_behavior": "Task should save successfully.",
                "actual_behavior": "API responds with 500.",
                "severity": "high",
                "reporter_user_id": "user-001",
                "reporter_username": "engineer-1",
                "metadata": {"app_version": "dev"},
            },
        )
        assert first.status_code == 200
        first_payload = first.json()
        assert first_payload["ok"] is True
        assert first_payload["created"] is True
        assert first_payload["bug_report"]["installation_id"] == "cp-bug-installation"
        assert first_payload["bug_report"]["status"] == "new"
        assert first_payload["bug_report"]["severity"] == "high"
        assert str(first_payload["bug_report"]["report_id"]).startswith("bug_")

        second = client.post(
            "/v1/support/bug-reports",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-bug-installation",
                "workspace_id": "workspace-bugs",
                "source": "task-app-ui",
                "title": "Cannot save task from drawer",
                "description": "Save action returns 500 when description includes markdown table.",
                "severity": "high",
            },
        )
        assert second.status_code == 200
        second_payload = second.json()
        assert second_payload["ok"] is True
        assert second_payload["created"] is False
        report_id = second_payload["bug_report"]["report_id"]

        listed = client.get(
            "/v1/admin/bug-reports?status=new&severity=high&installation_id=cp-bug-installation",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert listed.status_code == 200
        listed_payload = listed.json()
        assert listed_payload["ok"] is True
        assert listed_payload["total"] == 1
        assert listed_payload["items"][0]["report_id"] == report_id

        updated = client.patch(
            f"/v1/admin/bug-reports/{report_id}",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "status": "triaged",
                "triage_note": "Reproduced locally. Investigate markdown serializer.",
                "assignee": "backend-team",
            },
        )
        assert updated.status_code == 200
        updated_payload = updated.json()
        assert updated_payload["ok"] is True
        assert updated_payload["bug_report"]["status"] == "triaged"
        assert updated_payload["bug_report"]["assignee"] == "backend-team"

        triaged = client.get(
            "/v1/admin/bug-reports?status=triaged",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert triaged.status_code == 200
        triaged_payload = triaged.json()
        assert triaged_payload["ok"] is True
        assert triaged_payload["total"] == 1
        assert triaged_payload["items"][0]["report_id"] == report_id


def test_support_bug_report_rejects_invalid_severity(tmp_path: Path):
    with _build_client(tmp_path) as client:
        invalid = client.post(
            "/v1/support/bug-reports",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-bug-installation",
                "title": "Issue title",
                "description": "Detailed issue description.",
                "severity": "urgent",
            },
        )
        assert invalid.status_code == 400
        assert "Unsupported severity" in invalid.json()["detail"]


def test_admin_send_email_requires_configuration(tmp_path: Path):
    with _build_client(tmp_path) as client:
        response = client.post(
            "/v1/admin/email/send",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "to_email": "ops@example.com",
                "subject": "Smoke test",
                "text_body": "Hello from control-plane.",
            },
        )
        assert response.status_code == 503
        assert "Email delivery is not configured" in response.json()["detail"]


def test_admin_send_email_succeeds_with_configured_sender(monkeypatch, tmp_path: Path):
    with _build_client(tmp_path) as client:
        import license_control_plane.main as lcp_main

        captured: dict[str, str] = {}

        def _fake_send(*, to_email: str, subject: str, text_body: str) -> str:
            captured["to_email"] = to_email
            captured["subject"] = subject
            captured["text_body"] = text_body
            return "re_test_message_id"

        monkeypatch.setattr(lcp_main, "_send_email_via_resend", _fake_send)

        response = client.post(
            "/v1/admin/email/send",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "to_email": "ops@example.com",
                "subject": "Smoke test",
                "text_body": "Hello from control-plane.",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["provider"] == "resend"
        assert payload["to_email"] == "ops@example.com"
        assert payload["message_id"] == "re_test_message_id"
        assert captured["to_email"] == "ops@example.com"
        assert captured["subject"] == "Smoke test"
        assert captured["text_body"] == "Hello from control-plane."


def test_admin_send_onboarding_email_succeeds_with_template(monkeypatch, tmp_path: Path):
    with _build_client(tmp_path) as client:
        import license_control_plane.main as lcp_main

        captured: dict[str, str] = {}

        def _fake_send(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> str:
            captured["to_email"] = to_email
            captured["subject"] = subject
            captured["text_body"] = text_body
            captured["html_body"] = str(html_body or "")
            return "re_onboarding_message_id"

        monkeypatch.setattr(lcp_main, "_send_email_via_resend", _fake_send)

        waitlist = client.post(
            "/v1/public/waitlist",
            json={"email": "ops@example.com", "source": "marketing-site"},
        )
        assert waitlist.status_code == 200

        contact = client.post(
            "/v1/public/contact-requests",
            json={
                "request_type": "onboarding",
                "email": "ops@example.com",
                "source": "marketing-site",
            },
        )
        assert contact.status_code == 200

        response = client.post(
            "/v1/admin/email/send-onboarding",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "to_email": "ops@example.com",
                "customer_ref": "cust_example",
                "activation_code": "ACT-TEST-0001",
                "image_tag": "main",
                "install_script_url": "https://raw.githubusercontent.com/nirm3l/constructos/main/install.sh",
                "support_email": "support@constructos.dev",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["provider"] == "resend"
        assert payload["to_email"] == "ops@example.com"
        assert payload["customer_ref"] == "cust_example"
        assert payload["message_id"] == "re_onboarding_message_id"
        assert payload["lead_status_updates"]["updated_total"] == 2
        assert payload["lead_status_updates"]["updated_waitlist"] == 1
        assert payload["lead_status_updates"]["updated_contact_requests"] == 1
        assert "ConstructOS onboarding package" in payload["subject"]
        assert captured["to_email"] == "ops@example.com"
        assert "ACTIVATION_CODE=ACT-TEST-0001" in captured["text_body"]
        assert "INSTALL_COS=true" in captured["text_body"]
        assert "AUTO_DEPLOY=1" in captured["text_body"]
        assert "INSTALL_DESKTOP_APP=ask" in captured["text_body"]
        assert "Windows installer (cmd.exe)" in captured["text_body"]
        assert "curl -fsSL -o install.ps1" in captured["text_body"]
        assert "set INSTALL_DESKTOP_APP=ask && powershell" in captured["text_body"]
        assert "-ExecutionPolicy Bypass -File .\\install.ps1" in captured["text_body"]
        assert "deploy.sh" not in captured["text_body"]
        assert "LICENSE_SERVER_TOKEN=" not in captured["text_body"]
        assert "ACT-TEST-0001" in captured["text_body"]
        assert "ConstructOS" in captured["html_body"]
        assert "cust_example" in captured["html_body"]
        assert "Windows (cmd.exe):" in captured["html_body"]
        assert "install.ps1" in captured["html_body"]
        assert "Manual deploy command (optional):" not in captured["html_body"]

        waitlist_list = client.get(
            "/v1/admin/waitlist?q=ops@example.com",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert waitlist_list.status_code == 200
        waitlist_payload = waitlist_list.json()
        assert waitlist_payload["total"] == 1
        assert waitlist_payload["items"][0]["status"] == "onboarding_sent"

        contact_list = client.get(
            "/v1/admin/contact-requests?q=ops@example.com&request_type=onboarding",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert contact_list.status_code == 200
        contact_payload = contact_list.json()
        assert contact_payload["total"] == 1
        assert contact_payload["items"][0]["status"] == "onboarding_sent"


def test_admin_send_onboarding_email_rejects_non_https_script_url(tmp_path: Path):
    with _build_client(tmp_path) as client:
        response = client.post(
            "/v1/admin/email/send-onboarding",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "to_email": "ops@example.com",
                "customer_ref": "cust_example",
                "client_token": "lcp_test.client.bundle",
                "activation_code": "ACT-TEST-0001",
                "install_script_url": "http://example.com/install.sh",
            },
        )
        assert response.status_code == 400
        assert "install_script_url must start with https://" in response.json()["detail"]


def test_admin_provision_onboarding_requires_customer_ref_secret(tmp_path: Path):
    with _build_client(tmp_path) as client:
        response = client.post(
            "/v1/admin/onboarding/provision",
            headers={"Authorization": "Bearer control-plane-token"},
            json={"to_email": "ops@example.com"},
        )
        assert response.status_code == 503
        assert "LCP_CUSTOMER_REF_SECRET" in response.json()["detail"]


def test_admin_provision_onboarding_generates_and_sends_package(monkeypatch, tmp_path: Path):
    with _build_client(tmp_path, customer_ref_secret="test-customer-ref-secret") as client:
        import license_control_plane.main as lcp_main

        captured: dict[str, str] = {}

        def _fake_send(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> str:
            captured["to_email"] = to_email
            captured["subject"] = subject
            captured["text_body"] = text_body
            captured["html_body"] = str(html_body or "")
            return "re_onboarding_package_message_id"

        monkeypatch.setattr(lcp_main, "_send_email_via_resend", _fake_send)

        waitlist = client.post(
            "/v1/public/waitlist",
            json={"email": "ops@example.com", "source": "marketing-site"},
        )
        assert waitlist.status_code == 200

        contact = client.post(
            "/v1/public/contact-requests",
            json={
                "request_type": "onboarding",
                "email": "ops@example.com",
                "source": "marketing-site",
            },
        )
        assert contact.status_code == 200

        response = client.post(
            "/v1/admin/onboarding/provision",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "to_email": "ops@example.com",
                "max_installations": 3,
                "image_tag": "main",
                "install_script_url": "https://raw.githubusercontent.com/nirm3l/constructos/main/install.sh",
                "support_email": "support@constructos.dev",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["provider"] == "resend"
        assert payload["to_email"] == "ops@example.com"
        assert payload["message_id"] == "re_onboarding_package_message_id"
        assert str(payload["customer_ref"]).startswith("cust_")
        assert str(payload["client_token"]).startswith("lcp_")
        assert str(payload["activation_code"]).startswith("ACT-")
        assert payload["activation_code_record"]["customer_ref"] == payload["customer_ref"]
        assert payload["client_token_record"]["customer_ref"] == payload["customer_ref"]
        assert payload["activation_code_record"]["max_installations"] == 3
        assert payload["lead_status_updates"]["updated_total"] == 2
        assert payload["lead_status_updates"]["updated_waitlist"] == 1
        assert payload["lead_status_updates"]["updated_contact_requests"] == 1
        assert captured["to_email"] == "ops@example.com"
        assert f"ACTIVATION_CODE={payload['activation_code']}" in captured["text_body"]
        assert "INSTALL_COS=true" in captured["text_body"]
        assert "AUTO_DEPLOY=1" in captured["text_body"]
        assert "INSTALL_DESKTOP_APP=ask" in captured["text_body"]
        assert "Windows installer (cmd.exe)" in captured["text_body"]
        assert "curl -fsSL -o install.ps1" in captured["text_body"]
        assert "set INSTALL_DESKTOP_APP=ask && powershell" in captured["text_body"]
        assert "-ExecutionPolicy Bypass -File .\\install.ps1" in captured["text_body"]
        assert "deploy.sh" not in captured["text_body"]
        assert "LICENSE_SERVER_TOKEN=" not in captured["text_body"]
        assert payload["activation_code"] in captured["text_body"]
        assert payload["customer_ref"] in captured["html_body"]
        assert "Windows (cmd.exe):" in captured["html_body"]
        assert "install.ps1" in captured["html_body"]
        assert "Manual deploy command (optional):" not in captured["html_body"]

        waitlist_list = client.get(
            "/v1/admin/waitlist?q=ops@example.com",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert waitlist_list.status_code == 200
        waitlist_payload = waitlist_list.json()
        assert waitlist_payload["total"] == 1
        assert waitlist_payload["items"][0]["status"] == "onboarding_sent"

        contact_list = client.get(
            "/v1/admin/contact-requests?q=ops@example.com&request_type=onboarding",
            headers={"Authorization": "Bearer control-plane-token"},
        )
        assert contact_list.status_code == 200
        contact_payload = contact_list.json()
        assert contact_payload["total"] == 1
        assert contact_payload["items"][0]["status"] == "onboarding_sent"


def test_admin_provision_onboarding_lifetime_plan_ignores_valid_until(monkeypatch, tmp_path: Path):
    with _build_client(tmp_path, customer_ref_secret="test-customer-ref-secret") as client:
        import license_control_plane.main as lcp_main

        def _fake_send(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> str:
            return "re_onboarding_lifetime_message_id"

        monkeypatch.setattr(lcp_main, "_send_email_via_resend", _fake_send)

        response = client.post(
            "/v1/admin/onboarding/provision",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "to_email": "lifetime@example.com",
                "plan_code": "lifetime",
                "valid_until": "2026-12-31T00:00:00Z",
                "max_installations": 3,
                "image_tag": "main",
                "install_script_url": "https://raw.githubusercontent.com/nirm3l/constructos/main/install.sh",
                "support_email": "support@constructos.dev",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["activation_code_record"]["plan_code"] == "lifetime"
        assert payload["activation_code_record"]["valid_until"] is None


def test_admin_events_stream_requires_admin_token(tmp_path: Path):
    with _build_client(tmp_path) as client:
        unauthorized = client.get("/v1/admin/events")
        assert unauthorized.status_code == 401
        assert "Invalid control-plane admin token" in unauthorized.json()["detail"]
