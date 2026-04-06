from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.models import SessionLocal, SupportBugReportOutbox
from shared.settings import (
    SUPPORT_API_TOKEN,
    SUPPORT_API_URL,
    SUPPORT_BUG_REPORT_OUTBOX_BATCH_SIZE,
    SUPPORT_BUG_REPORT_OUTBOX_ENABLED,
    SUPPORT_BUG_REPORT_OUTBOX_INITIAL_BACKOFF_SECONDS,
    SUPPORT_BUG_REPORT_OUTBOX_MAX_ATTEMPTS,
    SUPPORT_BUG_REPORT_OUTBOX_POLL_SECONDS,
)

logger = logging.getLogger(__name__)

_retry_worker_stop_event = threading.Event()
_retry_worker_thread: threading.Thread | None = None
_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class SupportApiSubmitError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int | None = None):
        super().__init__(detail)
        self.detail = str(detail or "Support API request failed")
        self.status_code = int(status_code) if status_code is not None else None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _normalize_dedup_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return " ".join(part for part in text.split() if part)


def build_bug_report_dedup_key(payload: dict[str, Any]) -> str:
    installation_id = _normalize_dedup_text(payload.get("installation_id"))
    severity = _normalize_dedup_text(payload.get("severity"))
    title = _normalize_dedup_text(payload.get("title"))
    description = _normalize_dedup_text(payload.get("description"))
    raw = f"{installation_id}|{severity}|{title}|{description}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return f"bug-outbox:{digest}"


def is_retryable_status_code(status_code: int | None) -> bool:
    if status_code is None:
        return True
    if status_code >= 500:
        return True
    return status_code in _RETRYABLE_STATUS_CODES


def enqueue_bug_report(
    db: Session,
    payload: dict[str, Any],
    *,
    last_error: str | None = None,
) -> tuple[SupportBugReportOutbox, bool]:
    now = _now_utc()
    normalized_payload = dict(payload or {})
    dedup_key = build_bug_report_dedup_key(normalized_payload)

    existing = db.execute(
        select(SupportBugReportOutbox).where(
            SupportBugReportOutbox.dedup_key == dedup_key,
            SupportBugReportOutbox.sent_at.is_(None),
        )
    ).scalar_one_or_none()

    payload_json = _json_dumps(normalized_payload)
    if existing is not None:
        existing.payload_json = payload_json
        existing.next_attempt_at = now
        if last_error:
            existing.last_error = str(last_error).strip()[:2000]
        return existing, False

    record = SupportBugReportOutbox(
        dedup_key=dedup_key,
        payload_json=payload_json,
        attempt_count=0,
        next_attempt_at=now,
        last_error=str(last_error or "").strip()[:2000] or None,
        sent_at=None,
    )
    db.add(record)
    db.flush()
    return record, True


def _support_api_url(path: str) -> str:
    base = str(SUPPORT_API_URL or "").strip().rstrip("/")
    return f"{base}{path}"


def _support_api_headers() -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "task-app-support-outbox/1.0",
    }
    if SUPPORT_API_TOKEN:
        headers["Authorization"] = f"Bearer {SUPPORT_API_TOKEN}"
    return headers


def _support_api_error_detail(response: httpx.Response) -> str:
    fallback = f"Support API request failed ({response.status_code})"
    try:
        payload = response.json()
    except Exception:
        text = str(response.text or "").strip()
        return text or fallback
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    text = str(response.text or "").strip()
    return text or fallback


def _submit_bug_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                _support_api_url("/v1/support/bug-reports"),
                headers=_support_api_headers(),
                json=payload,
            )
    except Exception as exc:
        raise SupportApiSubmitError(f"Support API request failed: {exc}") from exc

    if response.status_code >= 400:
        raise SupportApiSubmitError(
            _support_api_error_detail(response),
            status_code=response.status_code,
        )

    body = response.json()
    if not isinstance(body, dict):
        raise SupportApiSubmitError("Support API response must be a JSON object", status_code=502)
    return body


def _next_retry_delay_seconds(attempt_count: int) -> float:
    exponent = max(0, int(attempt_count) - 1)
    delay = SUPPORT_BUG_REPORT_OUTBOX_INITIAL_BACKOFF_SECONDS * (2**exponent)
    return max(1.0, min(delay, 3600.0))


def _mark_failure(
    record: SupportBugReportOutbox,
    *,
    error_detail: str,
    retryable: bool,
) -> None:
    now = _now_utc()
    next_attempt_count = int(record.attempt_count or 0) + 1
    if not retryable:
        next_attempt_count = max(next_attempt_count, SUPPORT_BUG_REPORT_OUTBOX_MAX_ATTEMPTS)
    record.attempt_count = next_attempt_count
    record.last_error = str(error_detail or "Support API request failed")[:2000]

    if next_attempt_count >= SUPPORT_BUG_REPORT_OUTBOX_MAX_ATTEMPTS:
        record.next_attempt_at = now
        return

    record.next_attempt_at = now + timedelta(seconds=_next_retry_delay_seconds(next_attempt_count))


def sync_bug_report_outbox_once(*, batch_size: int | None = None) -> int:
    if not SUPPORT_BUG_REPORT_OUTBOX_ENABLED:
        return 0

    limit = max(1, int(batch_size or SUPPORT_BUG_REPORT_OUTBOX_BATCH_SIZE))
    now = _now_utc()
    processed = 0

    with SessionLocal() as db:
        rows = db.execute(
            select(SupportBugReportOutbox)
            .where(
                SupportBugReportOutbox.sent_at.is_(None),
                SupportBugReportOutbox.attempt_count < SUPPORT_BUG_REPORT_OUTBOX_MAX_ATTEMPTS,
                SupportBugReportOutbox.next_attempt_at <= now,
            )
            .order_by(SupportBugReportOutbox.next_attempt_at.asc(), SupportBugReportOutbox.id.asc())
            .limit(limit)
        ).scalars().all()

        for row in rows:
            try:
                payload = json.loads(row.payload_json or "{}")
                if not isinstance(payload, dict):
                    raise ValueError("Outbox payload must be a JSON object")
                _submit_bug_report_payload(payload)
                row.sent_at = _now_utc()
                row.last_error = None
                db.commit()
                processed += 1
            except SupportApiSubmitError as exc:
                db.rollback()
                _mark_failure(
                    row,
                    error_detail=exc.detail,
                    retryable=is_retryable_status_code(exc.status_code),
                )
                db.commit()
                logger.warning(
                    "support.outbox.delivery_failed id=%s attempt=%s status=%s error=%s",
                    row.id,
                    row.attempt_count,
                    exc.status_code,
                    exc.detail,
                )
            except Exception as exc:
                db.rollback()
                _mark_failure(
                    row,
                    error_detail=f"Unexpected outbox failure: {exc}",
                    retryable=True,
                )
                db.commit()
                logger.warning(
                    "support.outbox.delivery_failed id=%s attempt=%s error=%s",
                    row.id,
                    row.attempt_count,
                    exc,
                )

    return processed


def _retry_worker_loop() -> None:
    while not _retry_worker_stop_event.is_set():
        try:
            sent_count = sync_bug_report_outbox_once()
            if sent_count > 0:
                continue
        except Exception as exc:
            logger.warning("support.outbox.worker_iteration_failed error=%s", exc)
        _retry_worker_stop_event.wait(max(5.0, SUPPORT_BUG_REPORT_OUTBOX_POLL_SECONDS))


def start_bug_report_outbox_worker() -> None:
    global _retry_worker_thread
    if not SUPPORT_BUG_REPORT_OUTBOX_ENABLED:
        return
    if _retry_worker_thread and _retry_worker_thread.is_alive():
        return
    _retry_worker_stop_event.clear()
    _retry_worker_thread = threading.Thread(target=_retry_worker_loop, name="support-bug-report-outbox", daemon=True)
    _retry_worker_thread.start()


def stop_bug_report_outbox_worker() -> None:
    global _retry_worker_thread
    _retry_worker_stop_event.set()
    if _retry_worker_thread and _retry_worker_thread.is_alive():
        _retry_worker_thread.join(timeout=3)
    _retry_worker_thread = None
