import os
from importlib import reload
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select


def build_client(tmp_path: Path) -> TestClient:
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""

    import main

    main = reload(main)
    main.bootstrap_data()
    client = TestClient(main.app)
    login = client.post('/api/auth/login', json={'username': 'm4tr1x', 'password': 'testtest'})
    assert login.status_code == 200
    return client


def test_submit_bug_report_forwards_to_control_plane(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)

    import features.support.api as support_api

    monkeypatch.setattr(support_api, "resolve_license_installation_id", lambda _db: "inst-test-001")

    captured: dict[str, object] = {}

    class _MockResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "ok": True,
                "created": True,
                "bug_report": {
                    "report_id": "bug_test_123",
                    "status": "new",
                    "severity": "high",
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
        "/api/support/bug-reports",
        json={
            "title": "Task save fails",
            "description": "Saving task returns 500 for markdown table body.",
            "steps_to_reproduce": "Open task drawer, paste table, save.",
            "expected_behavior": "Task should save.",
            "actual_behavior": "Server returns 500.",
            "severity": "high",
            "include_diagnostics": True,
            "context": {
                "workspace_id": "ws-123",
                "project_id": "project-123",
                "route": "/tasks",
                "tab": "tasks",
            },
            "metadata": {
                "ui_version": "dev",
            },
        },
        headers={"User-Agent": "pytest-app"},
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    assert payload["created"] is True
    assert payload["queued"] is False
    assert payload["queue_id"] is None
    assert payload["report_id"] == "bug_test_123"

    assert str(captured.get("url") or "").endswith("/v1/support/bug-reports")
    forwarded = captured.get("json")
    assert isinstance(forwarded, dict)
    assert forwarded["installation_id"] == "inst-test-001"
    assert forwarded["workspace_id"] == "ws-123"
    assert forwarded["reporter_username"] == "m4tr1x"
    assert forwarded["severity"] == "high"



def test_submit_bug_report_rejects_invalid_severity(tmp_path: Path):
    client = build_client(tmp_path)

    res = client.post(
        "/api/support/bug-reports",
        json={
            "title": "Task save fails",
            "description": "Saving task returns 500 for markdown table body.",
            "severity": "urgent",
        },
    )

    assert res.status_code == 400
    assert "Unsupported severity" in res.json()["detail"]


def test_submit_bug_report_queues_when_control_plane_unavailable(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)

    import features.support.api as support_api
    from shared.models import SessionLocal, SupportBugReportOutbox

    monkeypatch.setattr(support_api, "resolve_license_installation_id", lambda _db: "inst-test-queue")

    def _mock_post_to_control_plane(path: str, payload: dict[str, object], request):
        raise HTTPException(status_code=503, detail="Control-plane request failed: timeout")

    monkeypatch.setattr(support_api, "_post_to_control_plane", _mock_post_to_control_plane)

    res = client.post(
        "/api/support/bug-reports",
        json={
            "title": "Queued bug report",
            "description": "Cannot reach control plane from app.",
            "severity": "medium",
        },
    )

    assert res.status_code == 202
    body = res.json()
    assert body["ok"] is True
    assert body["created"] is False
    assert body["queued"] is True
    assert isinstance(body["queue_id"], int)
    assert body["report_id"] is None

    with SessionLocal() as db:
        rows = db.execute(
            select(SupportBugReportOutbox).where(SupportBugReportOutbox.sent_at.is_(None))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].attempt_count == 0
        assert rows[0].payload_json


def test_submit_bug_report_does_not_queue_non_retryable_errors(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)

    import features.support.api as support_api
    from shared.models import SessionLocal, SupportBugReportOutbox

    monkeypatch.setattr(support_api, "resolve_license_installation_id", lambda _db: "inst-test-queue")

    def _mock_post_to_control_plane(path: str, payload: dict[str, object], request):
        raise HTTPException(status_code=400, detail="title is required")

    monkeypatch.setattr(support_api, "_post_to_control_plane", _mock_post_to_control_plane)

    res = client.post(
        "/api/support/bug-reports",
        json={
            "title": "Invalid payload",
            "description": "Non retryable control-plane validation error.",
            "severity": "medium",
        },
    )

    assert res.status_code == 400
    assert "title is required" in res.json()["detail"]

    with SessionLocal() as db:
        rows = db.execute(select(SupportBugReportOutbox)).scalars().all()
        assert rows == []
