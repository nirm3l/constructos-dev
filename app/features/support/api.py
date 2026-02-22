from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from shared.core import User, get_current_user, get_db
from shared.licensing import resolve_license_installation_id
from shared.settings import APP_VERSION, LICENSE_SERVER_TOKEN, LICENSE_SERVER_URL

router = APIRouter()
BUG_REPORT_SEVERITIES = {"low", "medium", "high", "critical"}


class WaitlistJoinProxyRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    source: str | None = Field(default="marketing-site", max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContactRequestProxyRequest(BaseModel):
    request_type: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=5, max_length=320)
    source: str | None = Field(default="marketing-site", max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BugReportSubmitRequest(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    description: str = Field(min_length=5, max_length=4000)
    steps_to_reproduce: str | None = Field(default=None, max_length=4000)
    expected_behavior: str | None = Field(default=None, max_length=2000)
    actual_behavior: str | None = Field(default=None, max_length=2000)
    severity: str = Field(default="medium", min_length=3, max_length=16)
    include_diagnostics: bool = Field(default=True)
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _control_plane_url(path: str) -> str:
    base = str(LICENSE_SERVER_URL or "").strip().rstrip("/")
    return f"{base}{path}"


def _forward_headers(request: Request) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if LICENSE_SERVER_TOKEN:
        headers["Authorization"] = f"Bearer {LICENSE_SERVER_TOKEN}"

    forwarded = str(request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        headers["X-Forwarded-For"] = forwarded
    elif request.client and request.client.host:
        headers["X-Forwarded-For"] = str(request.client.host)

    user_agent = str(request.headers.get("user-agent") or "").strip()
    if user_agent:
        headers["User-Agent"] = user_agent[:512]

    return headers


def _control_plane_error_detail(response: httpx.Response) -> str:
    fallback = f"Control-plane request failed ({response.status_code})"
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


def _post_to_control_plane(path: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                _control_plane_url(path),
                headers=_forward_headers(request),
                json=payload,
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Control-plane request failed: {exc}") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=_control_plane_error_detail(response))

    body = response.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="Control-plane response must be a JSON object")
    return body


def _normalize_bug_report_severity(value: str | None) -> str:
    normalized = str(value or "").strip().lower() or "medium"
    if normalized not in BUG_REPORT_SEVERITIES:
        allowed = ", ".join(sorted(BUG_REPORT_SEVERITIES))
        raise HTTPException(status_code=400, detail=f"Unsupported severity. Allowed values: {allowed}")
    return normalized


@router.post("/api/public/waitlist")
def proxy_waitlist_join(payload: WaitlistJoinProxyRequest, request: Request) -> dict[str, Any]:
    return _post_to_control_plane(
        "/v1/public/waitlist",
        {
            "email": payload.email,
            "source": payload.source,
            "metadata": payload.metadata or {},
        },
        request,
    )


@router.post("/api/support/bug-reports")
def submit_bug_report(
    payload: BugReportSubmitRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    installation_id = resolve_license_installation_id(db)
    severity = _normalize_bug_report_severity(payload.severity)
    context = dict(payload.context or {})

    metadata = dict(payload.metadata or {})
    metadata["context"] = context
    if payload.include_diagnostics:
        metadata["diagnostics"] = {
            "app_version": APP_VERSION,
            "reported_via": "task-app-ui",
        }

    response = _post_to_control_plane(
        "/v1/support/bug-reports",
        {
            "installation_id": installation_id,
            "workspace_id": str(context.get("workspace_id") or "").strip() or None,
            "source": "task-app-ui",
            "title": str(payload.title or "").strip(),
            "description": str(payload.description or "").strip(),
            "steps_to_reproduce": str(payload.steps_to_reproduce or "").strip() or None,
            "expected_behavior": str(payload.expected_behavior or "").strip() or None,
            "actual_behavior": str(payload.actual_behavior or "").strip() or None,
            "severity": severity,
            "reporter_user_id": str(user.id or "").strip() or None,
            "reporter_username": str(user.username or "").strip() or None,
            "metadata": metadata,
        },
        request,
    )
    bug_report = response.get("bug_report") if isinstance(response.get("bug_report"), dict) else {}
    report_id = str(bug_report.get("report_id") or "").strip() or None
    return {
        "ok": bool(response.get("ok")),
        "created": bool(response.get("created")),
        "report_id": report_id,
        "bug_report": bug_report,
    }


@router.post("/api/public/contact-requests")
def proxy_contact_request(payload: ContactRequestProxyRequest, request: Request) -> dict[str, Any]:
    return _post_to_control_plane(
        "/v1/public/contact-requests",
        {
            "request_type": payload.request_type,
            "email": payload.email,
            "source": payload.source,
            "metadata": payload.metadata or {},
        },
        request,
    )
