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


def test_public_beta_grants_active_entitlement_without_subscription(tmp_path: Path):
    with _build_client(tmp_path, public_beta_free_until="2099-12-31T23:59:59Z") as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-public-beta-installation",
                "workspace_id": "workspace-beta",
                "metadata": {"source": "tests"},
            },
        )
        assert register.status_code == 200
        payload = register.json()
        entitlement = payload["entitlement"]
        assert entitlement["status"] == "active"
        assert entitlement["plan_code"] == "beta_free"
        assert entitlement["valid_until"] == "2099-12-31T23:59:59+00:00"
        assert entitlement["metadata"]["public_beta"] is True
        assert entitlement["metadata"]["public_beta_free_until"] == "2099-12-31T23:59:59+00:00"

        health = client.get("/api/health")
        assert health.status_code == 200
        health_payload = health.json()
        assert health_payload["public_beta_active"] is True
        assert health_payload["public_beta_free_until"] == "2099-12-31T23:59:59+00:00"


def test_public_beta_expired_falls_back_to_trial(tmp_path: Path):
    with _build_client(tmp_path, public_beta_free_until="2000-01-01T00:00:00Z") as client:
        register = client.post(
            "/v1/installations/register",
            headers={"Authorization": "Bearer control-plane-token"},
            json={
                "installation_id": "cp-post-beta-installation",
                "workspace_id": "workspace-post-beta",
                "metadata": {"source": "tests"},
            },
        )
        assert register.status_code == 200
        payload = register.json()
        entitlement = payload["entitlement"]
        assert entitlement["status"] == "trial"
        assert entitlement["plan_code"] == "trial"
        assert entitlement["valid_until"].startswith(payload["installation"]["trial_ends_at"])

        health = client.get("/api/health")
        assert health.status_code == 200
        health_payload = health.json()
        assert health_payload["public_beta_active"] is False
        assert health_payload["public_beta_free_until"] == "2000-01-01T00:00:00+00:00"


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
