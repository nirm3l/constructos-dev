from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from shared.settings import SUPPORT_API_TOKEN, SUPPORT_API_URL

router = APIRouter()


class WaitlistJoinProxyRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    source: str | None = Field(default="constructos-site", max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContactRequestProxyRequest(BaseModel):
    request_type: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=5, max_length=320)
    source: str | None = Field(default="constructos-site", max_length=64)
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
