import os
from importlib import reload
from pathlib import Path


def bootstrap_app(tmp_path: Path):
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""

    import main

    main = reload(main)
    main.bootstrap_data()
    return main


def test_outbox_sync_marks_record_as_sent(tmp_path: Path, monkeypatch):
    bootstrap_app(tmp_path)

    import features.support.outbox as support_outbox
    from shared.models import SessionLocal, SupportBugReportOutbox

    with SessionLocal() as db:
        support_outbox.enqueue_bug_report(
            db,
            {
                "installation_id": "inst-outbox-1",
                "workspace_id": "ws-1",
                "source": "task-app-ui",
                "title": "Outbox bug",
                "description": "Control plane was temporarily unavailable.",
                "severity": "high",
            },
            last_error="temporary failure",
        )
        db.commit()

    class _MockResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"ok": True, "created": True, "bug_report": {"report_id": "bug_1"}}

    class _MockClient:
        def __init__(self, timeout: float):
            assert timeout == 8.0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            assert str(url).endswith("/v1/support/bug-reports")
            assert headers["Content-Type"] == "application/json"
            assert json["installation_id"] == "inst-outbox-1"
            return _MockResponse()

    monkeypatch.setattr(support_outbox.httpx, "Client", _MockClient)

    sent_count = support_outbox.sync_bug_report_outbox_once(batch_size=10)
    assert sent_count == 1

    with SessionLocal() as db:
        rows = db.query(SupportBugReportOutbox).all()
        assert len(rows) == 1
        assert rows[0].sent_at is not None
        assert rows[0].attempt_count == 0
        assert rows[0].last_error is None


def test_outbox_sync_increments_attempt_on_failure(tmp_path: Path, monkeypatch):
    bootstrap_app(tmp_path)

    import features.support.outbox as support_outbox
    from shared.models import SessionLocal, SupportBugReportOutbox

    with SessionLocal() as db:
        support_outbox.enqueue_bug_report(
            db,
            {
                "installation_id": "inst-outbox-2",
                "workspace_id": "ws-2",
                "source": "task-app-ui",
                "title": "Retry bug",
                "description": "Control plane still unavailable.",
                "severity": "medium",
            },
            last_error="initial submit failed",
        )
        db.commit()

    class _MockResponse:
        status_code = 503
        text = ""

        @staticmethod
        def json():
            return {"detail": "temporary outage"}

    class _MockClient:
        def __init__(self, timeout: float):
            assert timeout == 8.0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            return _MockResponse()

    monkeypatch.setattr(support_outbox.httpx, "Client", _MockClient)

    sent_count = support_outbox.sync_bug_report_outbox_once(batch_size=10)
    assert sent_count == 0

    with SessionLocal() as db:
        rows = db.query(SupportBugReportOutbox).all()
        assert len(rows) == 1
        assert rows[0].sent_at is None
        assert rows[0].attempt_count == 1
        assert rows[0].last_error == "temporary outage"
        assert rows[0].next_attempt_at is not None
