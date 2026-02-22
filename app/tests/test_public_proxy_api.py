import os
from importlib import reload
from pathlib import Path

from fastapi.testclient import TestClient


def build_anonymous_client(tmp_path: Path) -> TestClient:
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""

    import main

    main = reload(main)
    main.bootstrap_data()
    return TestClient(main.app)


def test_public_waitlist_proxy_forwards_to_control_plane(tmp_path: Path, monkeypatch):
    client = build_anonymous_client(tmp_path)

    import features.support.api as support_api

    captured: dict[str, object] = {}

    class _MockResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "ok": True,
                "created": True,
                "waitlist_entry": {
                    "email": "engineer@example.com",
                },
            }

    class _MockClient:
        def __init__(self, timeout: float):
            assert timeout == 8.0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            captured["url"] = url
            captured["headers"] = dict(headers)
            captured["json"] = dict(json)
            return _MockResponse()

    monkeypatch.setattr(support_api.httpx, "Client", _MockClient)

    res = client.post(
        "/api/public/waitlist",
        json={
            "email": "engineer@example.com",
            "source": "marketing-site",
            "metadata": {"campaign": "beta"},
        },
        headers={"User-Agent": "pytest-browser"},
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    assert payload["created"] is True
    assert payload["waitlist_entry"]["email"] == "engineer@example.com"

    assert str(captured.get("url") or "").endswith("/v1/public/waitlist")
    forwarded_headers = captured.get("headers")
    assert isinstance(forwarded_headers, dict)
    assert str(forwarded_headers.get("X-Forwarded-For") or "").strip() != ""
    assert str(forwarded_headers.get("User-Agent") or "") == "pytest-browser"



def test_public_contact_proxy_surfaces_control_plane_detail(tmp_path: Path, monkeypatch):
    client = build_anonymous_client(tmp_path)

    import features.support.api as support_api

    class _MockResponse:
        status_code = 400
        text = ""

        @staticmethod
        def json():
            return {
                "detail": "Unsupported request_type. Allowed values: demo, onboarding, plan_details",
            }

    class _MockClient:
        def __init__(self, timeout: float):
            assert timeout == 8.0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            return _MockResponse()

    monkeypatch.setattr(support_api.httpx, "Client", _MockClient)

    res = client.post(
        "/api/public/contact-requests",
        json={
            "request_type": "unknown",
            "email": "ops@example.com",
            "source": "marketing-site",
        },
    )

    assert res.status_code == 400
    assert "Unsupported request_type" in res.json()["detail"]
