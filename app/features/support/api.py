from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from shared.core import User, get_current_user
from shared.settings import SUPPORT_API_TOKEN, SUPPORT_API_URL, SUPPORT_INSTANCE_ID

router = APIRouter()
FEEDBACK_TYPES = {"general", "feature_request", "question", "other"}


class WaitlistJoinProxyRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    source: str | None = Field(default="constructos-site", max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContactRequestProxyRequest(BaseModel):
    request_type: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=5, max_length=320)
    source: str | None = Field(default="constructos-site", max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FeedbackSubmitRequest(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    description: str = Field(min_length=5, max_length=4000)
    feedback_type: str = Field(default="general", min_length=3, max_length=32)
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _support_api_url(path: str) -> str:
    base = str(SUPPORT_API_URL or "").strip().rstrip("/")
    return f"{base}{path}"


def _forward_headers(request: Request) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if SUPPORT_API_TOKEN:
        headers["Authorization"] = f"Bearer {SUPPORT_API_TOKEN}"

    forwarded = str(request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        headers["X-Forwarded-For"] = forwarded
    elif request.client and request.client.host:
        headers["X-Forwarded-For"] = str(request.client.host)

    user_agent = str(request.headers.get("user-agent") or "").strip()
    if user_agent:
        headers["User-Agent"] = user_agent[:512]

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


def _post_to_support_api(path: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                _support_api_url(path),
                headers=_forward_headers(request),
                json=payload,
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Support API request failed: {exc}") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=_support_api_error_detail(response))

    body = response.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="Support API response must be a JSON object")
    return body


def _normalize_feedback_type(value: str | None) -> str:
    normalized = str(value or "").strip().lower() or "general"
    if normalized not in FEEDBACK_TYPES:
        allowed = ", ".join(sorted(FEEDBACK_TYPES))
        raise HTTPException(status_code=400, detail=f"Unsupported feedback type. Allowed values: {allowed}")
    return normalized


def _feedback_identity_email(*, username: str | None, user_id: str | None, instance_id: str) -> str:
    raw = str(username or "").strip() or str(user_id or "").strip() or str(instance_id or "").strip() or "feedback"
    safe = "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "-" for ch in raw.lower()).strip(".-_")
    if not safe:
        safe = "feedback"
    return f"{safe[:64]}@feedback.local"


@router.post("/api/public/waitlist")
def proxy_waitlist_join(payload: WaitlistJoinProxyRequest, request: Request) -> dict[str, Any]:
    return _post_to_support_api(
        "/v1/public/waitlist",
        {
            "email": payload.email,
            "source": payload.source,
            "metadata": payload.metadata or {},
        },
        request,
    )


@router.post("/api/public/contact-requests")
def proxy_contact_request(payload: ContactRequestProxyRequest, request: Request) -> dict[str, Any]:
    return _post_to_support_api(
        "/v1/public/contact-requests",
        {
            "request_type": payload.request_type,
            "email": payload.email,
            "source": payload.source,
            "metadata": payload.metadata or {},
        },
        request,
    )


@router.post("/api/support/feedback")
def submit_feedback(
    payload: FeedbackSubmitRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    feedback_type = _normalize_feedback_type(payload.feedback_type)
    context = dict(payload.context or {})
    metadata = dict(payload.metadata or {})
    metadata["context"] = context
    reporter_user_id = str(user.id or "").strip() or None
    reporter_username = str(user.username or "").strip() or None
    normalized_title = str(payload.title or "").strip()
    normalized_description = str(payload.description or "").strip()

    primary_payload = {
        "instance_id": SUPPORT_INSTANCE_ID,
        "workspace_id": str(context.get("workspace_id") or "").strip() or None,
        "source": "task-app-ui",
        "title": normalized_title,
        "description": normalized_description,
        "feedback_type": feedback_type,
        "reporter_user_id": reporter_user_id,
        "reporter_username": reporter_username,
        "metadata": metadata,
    }
    try:
        support_response = _post_to_support_api("/v1/support/feedback", primary_payload, request)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        fallback_metadata = dict(metadata)
        fallback_metadata["submission_kind"] = "feedback"
        fallback_metadata["feedback_type"] = feedback_type
        fallback_metadata["instance_id"] = SUPPORT_INSTANCE_ID
        fallback_metadata["workspace_id"] = primary_payload["workspace_id"]
        fallback_metadata["reporter_user_id"] = reporter_user_id
        fallback_metadata["reporter_username"] = reporter_username
        fallback_metadata["title"] = normalized_title
        fallback_metadata["description"] = normalized_description
        fallback_payload = {
            "request_type": "feedback",
            "email": _feedback_identity_email(
                username=reporter_username,
                user_id=reporter_user_id,
                instance_id=SUPPORT_INSTANCE_ID,
            ),
            "source": "task-app-ui",
            "metadata": fallback_metadata,
        }
        try:
            support_response = _post_to_support_api("/v1/public/contact-requests", fallback_payload, request)
        except HTTPException as fallback_exc:
            # Compatibility fallback for support API versions that don't allow request_type=feedback yet.
            if fallback_exc.status_code != 400:
                raise
            fallback_payload["request_type"] = "onboarding"
            support_response = _post_to_support_api("/v1/public/contact-requests", fallback_payload, request)
        contact_request = (
            support_response.get("contact_request")
            if isinstance(support_response.get("contact_request"), dict)
            else {}
        )
        return {
            "ok": bool(support_response.get("ok")),
            "created": bool(support_response.get("created")),
            "feedback": contact_request,
        }
    feedback_record = (
        support_response.get("feedback")
        if isinstance(support_response.get("feedback"), dict)
        else {}
    )
    return {
        "ok": bool(support_response.get("ok")),
        "created": bool(support_response.get("created")),
        "feedback": feedback_record,
    }
