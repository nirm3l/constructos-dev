from __future__ import annotations

import asyncio
import base64
import html
import hmac
import json
import os
import secrets
import string
import hashlib
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine, func, inspect, or_, select, text
from sqlalchemy.orm import Mapped, Session, declarative_base, mapped_column, sessionmaker

try:
    from .token_signing import SigningError, sign_entitlement_payload
except Exception:  # pragma: no cover - runtime import fallback
    from token_signing import SigningError, sign_entitlement_payload


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    return float(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_datetime_utc(name: str) -> datetime | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    normalized = str(raw).strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO 8601 datetime (example: 2026-03-31T23:59:59Z)") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


LCP_DATABASE_URL = os.getenv("LCP_DATABASE_URL", "sqlite:////data/license-control-plane.db").strip() or "sqlite:////data/license-control-plane.db"
LCP_API_TOKEN = os.getenv("LCP_API_TOKEN", "").strip()
LCP_TRIAL_DAYS = max(1, _env_int("LCP_TRIAL_DAYS", 7))
LCP_TOKEN_TTL_SECONDS = max(60, _env_int("LCP_TOKEN_TTL_SECONDS", 3600))
LCP_SIGNING_PRIVATE_KEY_PEM = os.getenv("LCP_SIGNING_PRIVATE_KEY_PEM", "").strip()
LCP_SIGNING_KEY_ID = os.getenv("LCP_SIGNING_KEY_ID", "default-ed25519").strip() or "default-ed25519"
LCP_REQUIRE_SIGNED_TOKENS = _env_bool("LCP_REQUIRE_SIGNED_TOKENS", False)
LCP_DEFAULT_MAX_INSTALLATIONS = max(1, _env_int("LCP_DEFAULT_MAX_INSTALLATIONS", 3))
LCP_CLIENT_TOKEN_BUNDLE_PASSWORD = os.getenv(
    "LCP_CLIENT_TOKEN_BUNDLE_PASSWORD",
    os.getenv("APP_BUNDLE_PASSWORD", ""),
).strip()
LCP_CLIENT_TOKEN_DELIMITER = os.getenv("LCP_CLIENT_TOKEN_DELIMITER", ".").strip() or "."
LCP_CLIENT_TOKEN_BUNDLE_SEGMENT_INDEX = _env_int("LCP_CLIENT_TOKEN_BUNDLE_SEGMENT_INDEX", 2)
LCP_EMAIL_RESEND_API_KEY = os.getenv("LCP_EMAIL_RESEND_API_KEY", "").strip()
LCP_EMAIL_FROM = os.getenv("LCP_EMAIL_FROM", "").strip()
LCP_EMAIL_REPLY_TO = os.getenv("LCP_EMAIL_REPLY_TO", "").strip()
LCP_EMAIL_REQUEST_TIMEOUT_SECONDS = max(2.0, _env_float("LCP_EMAIL_REQUEST_TIMEOUT_SECONDS", 10.0))
LCP_CUSTOMER_REF_SECRET = os.getenv("LCP_CUSTOMER_REF_SECRET", "").strip()
LCP_CUSTOMER_REF_PREFIX = os.getenv("LCP_CUSTOMER_REF_PREFIX", "cust").strip() or "cust"
LCP_CUSTOMER_REF_LENGTH = max(8, min(48, _env_int("LCP_CUSTOMER_REF_LENGTH", 20)))
LCP_UNASSIGNED_CUSTOMER_REF = os.getenv("LCP_UNASSIGNED_CUSTOMER_REF", "cust_unassigned").strip() or "cust_unassigned"
LCP_ONBOARDING_IMAGE_TAG = os.getenv("LCP_ONBOARDING_IMAGE_TAG", "main").strip() or "main"
LCP_ONBOARDING_INSTALL_SCRIPT_URL = (
    os.getenv("LCP_ONBOARDING_INSTALL_SCRIPT_URL", "https://raw.githubusercontent.com/nirm3l/constructos/main/install.sh").strip()
    or "https://raw.githubusercontent.com/nirm3l/constructos/main/install.sh"
)
LCP_ONBOARDING_SUPPORT_EMAIL = os.getenv("LCP_ONBOARDING_SUPPORT_EMAIL", "support@constructos.dev").strip() or "support@constructos.dev"
# Beta plan is indefinite. Keep the legacy health fields, but without an expiry cutoff.
LCP_BETA_PLAN_VALID_UNTIL: datetime | None = None
LCP_ADMIN_SSE_POLL_SECONDS = max(0.5, _env_float("LCP_ADMIN_SSE_POLL_SECONDS", 1.0))
LCP_ADMIN_SSE_HEARTBEAT_SECONDS = max(5.0, _env_float("LCP_ADMIN_SSE_HEARTBEAT_SECONDS", 15.0))
LCP_CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "LCP_CORS_ORIGINS",
        (
            "http://localhost:8082,"
            "http://127.0.0.1:8082,"
            "https://constructos.dev,"
            "https://www.constructos.dev,"
            "https://constructis.dev,"
            "https://www.constructis.dev"
        ),
    ).split(",")
    if origin.strip()
]
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_HTML = STATIC_DIR / "index.html"
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
PUBLIC_REQUEST_TYPES = {"demo", "onboarding", "plan_details", "feedback"}
SUPPORT_FEEDBACK_TYPES = {"general", "feature_request", "question", "other"}
BUG_REPORT_SEVERITIES = {"low", "medium", "high", "critical"}
BUG_REPORT_STATUSES = {"new", "triaged", "in_progress", "resolved", "closed", "rejected"}
APP_NOTIFICATION_SEVERITIES = {"info", "warning", "critical"}
APP_NOTIFICATION_AUDIENCE_KINDS = {"all", "customer_ref", "customer_email", "installation_id"}
LEAD_STATUS_PENDING = "pending"
LEAD_STATUS_ONBOARDING_SENT = "onboarding_sent"
LEAD_STATUS_CONVERTED = "converted"
SUPPORTED_LEAD_STATUSES = {
    LEAD_STATUS_PENDING,
    LEAD_STATUS_ONBOARDING_SENT,
    LEAD_STATUS_CONVERTED,
}
SUPPORTED_SUBSCRIPTION_STATUSES = {"none", "active", "trialing", "grace", "lifetime", "beta"}
SUBSCRIPTION_STATUS_ALIASES = {
    "past_due": "grace",
    "canceled": "none",
}
SUBSCRIPTION_STATUS_FILTER_EQUIVALENTS = {
    "none": {"none", "canceled"},
    "grace": {"grace", "past_due"},
}
RESERVED_PLAN_CODES = {"lifetime", "beta", "trial"}
UNLIMITED_INSTALLATION_PLAN_CODES = {"lifetime", "beta"}
STATUS_CANONICAL_PLAN_CODE = {
    "lifetime": "lifetime",
    "beta": "beta",
    "trialing": "trial",
}

Base = declarative_base()


class Installation(Base):
    __tablename__ = "installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    customer_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    operating_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subscription_status: Mapped[str] = mapped_column(String(32), default="none")
    subscription_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    trial_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ActivationCode(Base):
    __tablename__ = "activation_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    code_suffix: Mapped[str] = mapped_column(String(16), index=True)
    customer_ref: Mapped[str] = mapped_column(String(128), index=True)
    plan_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_installations: Mapped[int] = mapped_column(Integer, default=LCP_DEFAULT_MAX_INSTALLATIONS)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ClientToken(Base):
    __tablename__ = "client_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    token_suffix: Mapped[str] = mapped_column(String(16), index=True)
    customer_ref: Mapped[str] = mapped_column(String(128), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(64), default="marketing-site", index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ContactRequest(Base):
    __tablename__ = "contact_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_type: Mapped[str] = mapped_column(String(32), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    source: Mapped[str] = mapped_column(String(64), default="marketing-site", index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AppNotificationCampaign(Base):
    __tablename__ = "app_notification_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notification_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16), default="info", index=True)
    notification_type: Mapped[str] = mapped_column(String(64), default="ControlPlaneMessage", index=True)
    audience_kind: Mapped[str] = mapped_column(String(32), default="all", index=True)
    audience_values_json: Mapped[str] = mapped_column(Text, default="[]")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    active_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class BugReport(Base):
    __tablename__ = "bug_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    installation_id: Mapped[str] = mapped_column(String(128), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    customer_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(64), default="task-app", index=True)
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium", index=True)
    title: Mapped[str] = mapped_column(String(140))
    description: Mapped[str] = mapped_column(Text)
    steps_to_reproduce: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_behavior: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_behavior: Mapped[str | None] = mapped_column(Text, nullable=True)
    reporter_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reporter_username: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    triage_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    dedup_key: Mapped[str] = mapped_column(String(128), index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


engine = create_engine(
    LCP_DATABASE_URL,
    connect_args={"check_same_thread": False} if LCP_DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class InstallationRegisterRequest(BaseModel):
    installation_id: str = Field(min_length=3, max_length=128)
    workspace_id: str | None = None
    customer_ref: str | None = Field(default=None, max_length=128)
    app_version: str | None = None
    operating_system: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InstallationHeartbeatRequest(BaseModel):
    installation_id: str = Field(min_length=3, max_length=128)
    workspace_id: str | None = None
    customer_ref: str | None = Field(default=None, max_length=128)
    app_version: str | None = None
    operating_system: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdminSubscriptionUpdateRequest(BaseModel):
    subscription_status: str = Field(min_length=2, max_length=32)
    plan_code: str | None = None
    customer_ref: str | None = None
    valid_until: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdminActivationCodeCreateRequest(BaseModel):
    customer_ref: str = Field(min_length=2, max_length=128)
    plan_code: str | None = None
    valid_until: str | None = None
    max_installations: int = Field(default=LCP_DEFAULT_MAX_INSTALLATIONS, ge=1, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InstallationActivateRequest(BaseModel):
    installation_id: str = Field(min_length=3, max_length=128)
    activation_code: str = Field(min_length=8, max_length=128)
    workspace_id: str | None = None
    customer_ref: str | None = Field(default=None, max_length=128)
    app_version: str | None = None
    operating_system: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InstallExchangeRequest(BaseModel):
    activation_code: str = Field(min_length=8, max_length=128)
    operating_system: str | None = Field(default=None, max_length=64)


class AdminClientTokenCreateRequest(BaseModel):
    customer_ref: str = Field(min_length=2, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdminEmailSendRequest(BaseModel):
    to_email: str = Field(min_length=5, max_length=320)
    subject: str = Field(min_length=1, max_length=200)
    text_body: str = Field(min_length=1, max_length=20000)


class AdminOnboardingEmailSendRequest(BaseModel):
    to_email: str = Field(min_length=5, max_length=320)
    customer_ref: str = Field(min_length=2, max_length=128)
    client_token: str | None = Field(default=None, max_length=4096)
    activation_code: str = Field(min_length=8, max_length=128)
    image_tag: str | None = Field(default=None, max_length=128)
    install_script_url: str | None = Field(default=None, max_length=1024)
    support_email: str | None = Field(default=None, max_length=320)


class AdminProvisionOnboardingRequest(BaseModel):
    to_email: str = Field(min_length=5, max_length=320)
    plan_code: str | None = Field(default="monthly", max_length=64)
    valid_until: str | None = None
    max_installations: int = Field(default=LCP_DEFAULT_MAX_INSTALLATIONS, ge=1, le=100)
    image_tag: str | None = Field(default=None, max_length=128)
    install_script_url: str | None = Field(default=None, max_length=1024)
    support_email: str | None = Field(default=None, max_length=320)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WaitlistJoinRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    source: str | None = Field(default="marketing-site", max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContactRequestCreateRequest(BaseModel):
    request_type: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=5, max_length=320)
    source: str | None = Field(default="marketing-site", max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdminAppNotificationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    message: str = Field(min_length=1, max_length=10000)
    severity: str = Field(default="info", min_length=2, max_length=16)
    notification_type: str = Field(default="ControlPlaneMessage", min_length=2, max_length=64)
    audience_kind: str = Field(default="all", min_length=2, max_length=32)
    audience_values: list[str] = Field(default_factory=list)
    active_from: str | None = None
    active_until: str | None = None
    is_active: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)


class SupportFeedbackCreateRequest(BaseModel):
    installation_id: str = Field(min_length=3, max_length=128)
    workspace_id: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default="task-app-ui", max_length=64)
    title: str = Field(min_length=3, max_length=140)
    description: str = Field(min_length=5, max_length=4000)
    feedback_type: str = Field(default="general", min_length=3, max_length=32)
    reporter_user_id: str | None = Field(default=None, max_length=64)
    reporter_username: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BugReportCreateRequest(BaseModel):
    installation_id: str = Field(min_length=3, max_length=128)
    workspace_id: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default="task-app", max_length=64)
    title: str = Field(min_length=3, max_length=140)
    description: str = Field(min_length=5, max_length=4000)
    steps_to_reproduce: str | None = Field(default=None, max_length=4000)
    expected_behavior: str | None = Field(default=None, max_length=2000)
    actual_behavior: str | None = Field(default=None, max_length=2000)
    severity: str = Field(default="medium", min_length=3, max_length=16)
    reporter_user_id: str | None = Field(default=None, max_length=64)
    reporter_username: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdminBugReportUpdateRequest(BaseModel):
    status: str | None = Field(default=None, max_length=32)
    triage_note: str | None = Field(default=None, max_length=4000)
    assignee: str | None = Field(default=None, max_length=128)


@dataclass(frozen=True)
class InstallationAuthContext:
    auth_type: str
    customer_ref: str | None = None
    activation_code_id: int | None = None
    issued_operating_system: str | None = None
    issued_ip: str | None = None


def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _extract_bearer_secret(authorization: str | None) -> str | None:
    raw = str(authorization or "").strip()
    if not raw:
        return None
    if not raw.lower().startswith("bearer "):
        return None
    secret = raw[7:].strip()
    return secret or None


def _secret_hash(value: str | None) -> str:
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_email(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="email is required")
    if len(normalized) > 320:
        raise HTTPException(status_code=400, detail="email is too long")
    if not EMAIL_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=400, detail="Invalid email format")
    return normalized


def _normalize_email_subject(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="subject is required")
    if len(normalized) > 200:
        raise HTTPException(status_code=400, detail="subject is too long")
    return normalized


def _normalize_email_body(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="text_body is required")
    if len(normalized) > 20000:
        raise HTTPException(status_code=400, detail="text_body is too long")
    return normalized


def _normalize_notification_message(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="message is required")
    if len(normalized) > 10000:
        raise HTTPException(status_code=400, detail="message is too long")
    return normalized


def _normalize_notification_title(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if len(normalized) > 160:
        raise HTTPException(status_code=400, detail="title is too long")
    return normalized


def _normalize_notification_type(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "ControlPlaneMessage"
    if len(normalized) > 64:
        raise HTTPException(status_code=400, detail="notification_type is too long")
    return normalized


def _normalize_notification_severity(value: str | None) -> str:
    normalized = str(value or "").strip().lower() or "info"
    if normalized not in APP_NOTIFICATION_SEVERITIES:
        raise HTTPException(status_code=400, detail="Unsupported notification severity")
    return normalized


def _normalize_notification_audience_kind(value: str | None) -> str:
    normalized = str(value or "").strip().lower() or "all"
    if normalized not in APP_NOTIFICATION_AUDIENCE_KINDS:
        raise HTTPException(status_code=400, detail="Unsupported notification audience_kind")
    return normalized


def _normalize_notification_audience_values(kind: str, values: list[str] | None) -> list[str]:
    raw_values = values if isinstance(values, list) else []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        candidate = str(item or "").strip()
        if not candidate:
            continue
        if kind == "customer_email":
            candidate = _normalize_email(candidate)
        elif kind == "customer_ref":
            candidate = _normalize_customer_ref(candidate)
        elif kind == "installation_id":
            if len(candidate) < 3 or len(candidate) > 128:
                raise HTTPException(status_code=400, detail="installation_id audience value is invalid")
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    if kind != "all" and not normalized:
        raise HTTPException(status_code=400, detail="audience_values is required for selected audience_kind")
    if kind == "all" and normalized:
        raise HTTPException(status_code=400, detail="audience_values must be empty when audience_kind is 'all'")
    return normalized


def _normalize_customer_ref(value: str | None) -> str:
    normalized = str(value or "").strip()
    if len(normalized) < 2:
        raise HTTPException(status_code=400, detail="customer_ref is required")
    if len(normalized) > 128:
        raise HTTPException(status_code=400, detail="customer_ref is too long")
    return normalized


def _normalize_client_token(value: str | None) -> str:
    normalized = str(value or "").strip()
    if len(normalized) < 8:
        raise HTTPException(status_code=400, detail="client_token is required")
    if len(normalized) > 4096:
        raise HTTPException(status_code=400, detail="client_token is too long")
    return normalized


def _normalize_activation_code_value(value: str | None) -> str:
    normalized = str(value or "").strip()
    if len(normalized) < 8:
        raise HTTPException(status_code=400, detail="activation_code is required")
    if len(normalized) > 128:
        raise HTTPException(status_code=400, detail="activation_code is too long")
    return normalized


def _normalize_image_tag(value: str | None) -> str:
    normalized = str(value or "").strip() or LCP_ONBOARDING_IMAGE_TAG
    if len(normalized) > 128:
        raise HTTPException(status_code=400, detail="image_tag is too long")
    return normalized


def _normalize_install_script_url(value: str | None) -> str:
    normalized = str(value or "").strip() or LCP_ONBOARDING_INSTALL_SCRIPT_URL
    if len(normalized) > 1024:
        raise HTTPException(status_code=400, detail="install_script_url is too long")
    if not normalized.startswith("https://"):
        raise HTTPException(status_code=400, detail="install_script_url must start with https://")
    return normalized


def _normalize_support_email(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return _normalize_email(LCP_ONBOARDING_SUPPORT_EMAIL)
    return _normalize_email(raw)


def _normalize_operating_system(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    aliases = {
        "windows": "windows",
        "win32": "windows",
        "win64": "windows",
        "windows nt": "windows",
        "mac": "macos",
        "macos": "macos",
        "osx": "macos",
        "mac os x": "macos",
        "darwin": "macos",
        "linux": "linux",
        "ubuntu": "ubuntu",
        "debian": "debian",
    }
    if normalized in aliases:
        return aliases[normalized]
    if "windows" in normalized:
        return "windows"
    if normalized.startswith("mac") or "darwin" in normalized or "osx" in normalized:
        return "macos"
    if "ubuntu" in normalized:
        return "ubuntu"
    if "debian" in normalized:
        return "debian"
    if "linux" in normalized:
        return "linux"
    return normalized[:64]


def _resolve_operating_system_from_payload(
    payload: InstallationRegisterRequest | InstallationHeartbeatRequest | InstallationActivateRequest,
) -> str | None:
    direct_value = _normalize_operating_system(payload.operating_system)
    if direct_value:
        return direct_value
    metadata = payload.metadata if isinstance(payload.metadata, dict) else {}
    for key in ("operating_system", "os", "platform", "platform_os", "system"):
        candidate = metadata.get(key)
        if isinstance(candidate, str):
            normalized = _normalize_operating_system(candidate)
            if normalized:
                return normalized
    return None


def _plan_code_skips_seat_limits(plan_code: str | None) -> bool:
    normalized = str(plan_code or "").strip().lower()
    return normalized in UNLIMITED_INSTALLATION_PLAN_CODES


def _customer_ref_prefix() -> str:
    raw = str(LCP_CUSTOMER_REF_PREFIX or "").strip().lower()
    safe = re.sub(r"[^a-z0-9_-]+", "", raw).strip("_-")
    return safe or "cust"


def _require_customer_ref_secret() -> str:
    secret = str(LCP_CUSTOMER_REF_SECRET or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Customer reference generation is not configured (LCP_CUSTOMER_REF_SECRET)")
    return secret


def _customer_ref_from_email(email: str) -> str:
    secret = _require_customer_ref_secret()
    digest = hmac.new(
        secret.encode("utf-8"),
        email.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    encoded = base64.b32encode(digest).decode("ascii").rstrip("=").lower()
    return f"{_customer_ref_prefix()}_{encoded[:LCP_CUSTOMER_REF_LENGTH]}"


def _require_email_delivery_config() -> None:
    missing: list[str] = []
    if not LCP_EMAIL_RESEND_API_KEY:
        missing.append("LCP_EMAIL_RESEND_API_KEY")
    if not LCP_EMAIL_FROM:
        missing.append("LCP_EMAIL_FROM")
    if missing:
        joined = ", ".join(missing)
        raise HTTPException(status_code=503, detail=f"Email delivery is not configured ({joined})")


def _resend_error_detail(response: httpx.Response) -> str:
    fallback = f"Resend API request failed ({response.status_code})"
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    text = str(response.text or "").strip()
    return text or fallback


def _send_email_via_resend(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> str | None:
    _require_email_delivery_config()
    headers = {
        "Authorization": f"Bearer {LCP_EMAIL_RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "from": LCP_EMAIL_FROM,
        "to": [to_email],
        "subject": subject,
        "text": text_body,
    }
    html_value = str(html_body or "").strip()
    if html_value:
        payload["html"] = html_value
    if LCP_EMAIL_REPLY_TO:
        payload["reply_to"] = LCP_EMAIL_REPLY_TO
    response = httpx.post(
        "https://api.resend.com/emails",
        headers=headers,
        json=payload,
        timeout=LCP_EMAIL_REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise RuntimeError(_resend_error_detail(response))
    try:
        parsed = response.json()
    except Exception:
        return None
    if isinstance(parsed, dict):
        raw_id = parsed.get("id")
        if raw_id is not None:
            normalized = str(raw_id).strip()
            return normalized or None
    return None


def _build_onboarding_email_template(
    *,
    customer_ref: str,
    activation_code: str,
    image_tag: str,
    install_script_url: str,
    support_email: str,
    max_installations: int = LCP_DEFAULT_MAX_INSTALLATIONS,
) -> tuple[str, str, str]:
    subject = "ConstructOS onboarding package"
    windows_install_script_url = re.sub(
        r"install\.sh(?=$|[?#])",
        "install.ps1",
        install_script_url,
        count=1,
    )
    install_env_segments = [
        f"ACTIVATION_CODE={activation_code}",
        f"IMAGE_TAG={image_tag}",
        "INSTALL_COS=true",
        "AUTO_DEPLOY=1",
    ]
    install_command = (
        f"curl -fsSL {install_script_url} | "
        f"{' '.join(install_env_segments)} bash"
    )
    windows_download_command = f"curl -fsSL -o install.ps1 {windows_install_script_url}"
    windows_install_command = (
        "powershell -NoProfile -ExecutionPolicy Bypass -File .\\install.ps1 "
        f"-ActivationCode {activation_code} -ImageTag {image_tag} -InstallCos true -AutoDeploy true"
    )
    windows_install_block = f"{windows_download_command}\n{windows_install_command}"

    text_body = (
        "Hello,\n\n"
        "Your ConstructOS onboarding package is ready.\n\n"
        "1) Linux/macOS installer (it will exchange activation code for token automatically):\n"
        f"{install_command}\n\n"
        "2) Windows installer (cmd.exe):\n"
        f"{windows_install_block}\n\n"
        "3) Activate license in app with this activation code:\n"
        f"{activation_code}\n\n"
        "Details:\n"
        f"- customer_ref: {customer_ref}\n"
        f"- seat limit: {int(max_installations)} installations max\n\n"
        f"Support: {support_email}\n"
    )

    html_body = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{html.escape(subject)}</title>
  </head>
  <body style="margin:0;padding:0;background:#0f1f18;color:#dfffe9;font-family:'Avenir Next','Trebuchet MS','Gill Sans',Segoe UI,Arial,sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:linear-gradient(180deg,#132920 0%,#0f1f18 45%,#11261d 100%);padding:28px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="width:640px;max-width:92%;background:linear-gradient(180deg,rgba(14,29,21,0.93),rgba(9,19,14,0.96));background-color:#0a140f;border:1px solid rgba(97,224,142,0.28);border-radius:20px;overflow:hidden;box-shadow:0 20px 40px rgba(0,0,0,0.45);">
            <tr>
              <td style="padding:20px 24px;background:linear-gradient(180deg,#143022 0%,#10241a 100%);border-bottom:1px solid rgba(122,255,170,0.46);">
                <div style="font-size:12px;letter-spacing:0.12em;text-transform:uppercase;color:#73e7a1;font-family:'JetBrains Mono','Fira Code','SFMono-Regular',Menlo,monospace;">ConstructOS.dev</div>
                <div style="font-size:22px;font-weight:800;color:#ebffef;margin-top:6px;font-family:'JetBrains Mono','Fira Code','SFMono-Regular',Menlo,monospace;">Onboarding Package</div>
                <div style="font-size:13px;color:#84bc98;margin-top:6px;">Customer reference: <code style="background:rgba(8,22,14,0.9);border:1px solid rgba(90,218,141,0.45);border-radius:8px;padding:2px 6px;color:#bfffd4;font-family:'JetBrains Mono','Fira Code','SFMono-Regular',Menlo,monospace;">{html.escape(customer_ref)}</code></div>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 24px;">
                <p style="margin:0 0 12px 0;color:#84bc98;font-size:14px;line-height:1.6;">Your deployment bundle is ready. Run one installer command for your platform:</p>
                <p style="margin:0 0 8px 0;color:#84bc98;font-size:14px;">Linux/macOS:</p>
                <pre style="margin:0 0 16px 0;background:rgba(6,17,11,0.92);border:1px solid rgba(89,220,141,0.3);border-radius:10px;padding:12px 14px;overflow:auto;color:#b0ffd0;font-size:13px;line-height:1.5;font-family:'JetBrains Mono','Fira Code','SFMono-Regular',Menlo,monospace;">{html.escape(install_command)}</pre>

                <p style="margin:0 0 8px 0;color:#84bc98;font-size:14px;">Windows (cmd.exe):</p>
                <pre style="margin:0 0 16px 0;background:rgba(6,17,11,0.92);border:1px solid rgba(89,220,141,0.3);border-radius:10px;padding:12px 14px;overflow:auto;color:#b0ffd0;font-size:13px;line-height:1.5;font-family:'JetBrains Mono','Fira Code','SFMono-Regular',Menlo,monospace;">{html.escape(windows_install_block)}</pre>

                <p style="margin:0 0 8px 0;color:#84bc98;font-size:14px;">Activation code:</p>
                <pre style="margin:0 0 16px 0;background:rgba(6,17,11,0.92);border:1px solid rgba(89,220,141,0.3);border-radius:10px;padding:12px 14px;overflow:auto;color:#dfffe9;font-size:13px;line-height:1.5;font-family:'JetBrains Mono','Fira Code','SFMono-Regular',Menlo,monospace;">{html.escape(activation_code)}</pre>

                <div style="margin:0;padding:10px 12px;background:rgba(11,25,18,0.86);border:1px solid rgba(122,255,170,0.46);border-radius:10px;color:#dfffe9;font-size:13px;line-height:1.55;">
                  Seat policy: up to {int(max_installations)} active installations per customer reference.
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:14px 24px;border-top:1px solid rgba(97,224,142,0.28);color:#84bc98;font-size:12px;">
                Need help? Contact <a href="mailto:{html.escape(support_email)}" style="color:#73e7a1;text-decoration:none;">{html.escape(support_email)}</a>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    return subject, text_body, html_body


def _create_client_token_record(
    db: Session,
    *,
    customer_ref: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, ClientToken]:
    raw_token = ""
    token_hash = ""
    for _ in range(10):
        candidate = _generate_client_token()
        candidate_hash = _secret_hash(candidate)
        exists = db.execute(
            select(ClientToken.id).where(ClientToken.token_hash == candidate_hash)
        ).scalar_one_or_none()
        if exists is None:
            raw_token = candidate
            token_hash = candidate_hash
            break
    if not raw_token:
        raise HTTPException(status_code=500, detail="Failed to allocate client token")

    record = ClientToken(
        token_hash=token_hash,
        token_suffix=_client_token_suffix(raw_token),
        customer_ref=customer_ref,
        is_active=True,
        metadata_json=_dump_metadata(metadata or {}),
    )
    db.add(record)
    db.flush()
    return raw_token, record


def _create_activation_code_record(
    db: Session,
    *,
    customer_ref: str,
    plan_code: str,
    valid_until: datetime | None,
    max_installations: int,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, ActivationCode]:
    activation_code_raw = ""
    activation_code_hash = ""
    for _ in range(10):
        candidate = _generate_activation_code()
        candidate_hash = _activation_code_hash(candidate)
        exists = db.execute(
            select(ActivationCode.id).where(ActivationCode.code_hash == candidate_hash)
        ).scalar_one_or_none()
        if exists is None:
            activation_code_raw = candidate
            activation_code_hash = candidate_hash
            break
    if not activation_code_raw:
        raise HTTPException(status_code=500, detail="Failed to allocate activation code")

    record = ActivationCode(
        code_hash=activation_code_hash,
        code_suffix=_activation_code_suffix(activation_code_raw),
        customer_ref=customer_ref,
        plan_code=plan_code,
        valid_until=valid_until,
        max_installations=max_installations,
        is_active=True,
        usage_count=0,
        metadata_json=_dump_metadata(metadata or {}),
    )
    db.add(record)
    db.flush()
    return activation_code_raw, record


def _normalize_public_request_type(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="request_type is required")
    if normalized not in PUBLIC_REQUEST_TYPES:
        allowed = ", ".join(sorted(PUBLIC_REQUEST_TYPES))
        raise HTTPException(status_code=400, detail=f"Unsupported request_type. Allowed values: {allowed}")
    return normalized


def _normalize_support_feedback_type(value: str | None) -> str:
    normalized = str(value or "").strip().lower() or "general"
    if normalized not in SUPPORT_FEEDBACK_TYPES:
        allowed = ", ".join(sorted(SUPPORT_FEEDBACK_TYPES))
        raise HTTPException(status_code=400, detail=f"Unsupported feedback_type. Allowed values: {allowed}")
    return normalized


def _normalize_bug_report_severity(value: str | None) -> str:
    normalized = str(value or "").strip().lower() or "medium"
    if normalized not in BUG_REPORT_SEVERITIES:
        allowed = ", ".join(sorted(BUG_REPORT_SEVERITIES))
        raise HTTPException(status_code=400, detail=f"Unsupported severity. Allowed values: {allowed}")
    return normalized


def _normalize_bug_report_status(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="status is required")
    if normalized not in BUG_REPORT_STATUSES:
        allowed = ", ".join(sorted(BUG_REPORT_STATUSES))
        raise HTTPException(status_code=400, detail=f"Unsupported status. Allowed values: {allowed}")
    return normalized


_admin_event_state_lock = threading.Lock()
_admin_event_revision = 0
_admin_event_payload: dict[str, Any] = {
    "revision": 0,
    "topic": "control-plane",
    "action": "startup",
    "at": datetime.now(timezone.utc).isoformat(),
    "details": {},
}


def _publish_admin_event(topic: str, action: str, details: dict[str, Any] | None = None) -> None:
    global _admin_event_revision, _admin_event_payload
    with _admin_event_state_lock:
        _admin_event_revision += 1
        _admin_event_payload = {
            "revision": _admin_event_revision,
            "topic": str(topic or "").strip() or "control-plane",
            "action": str(action or "").strip() or "changed",
            "at": _now_utc().isoformat(),
            "details": dict(details or {}),
        }


def _get_admin_event_snapshot() -> dict[str, Any]:
    with _admin_event_state_lock:
        return dict(_admin_event_payload)


def _format_sse_message(event: str, payload: dict[str, Any], *, event_id: str | None = None) -> str:
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=str)
    for line in serialized.splitlines() or ["{}"]:
        lines.append(f"data: {line}")
    lines.append("")
    return "\n".join(lines)


def _validate_admin_auth_token(
    *,
    token_query: str | None = None,
    authorization: str | None = None,
) -> None:
    if not LCP_API_TOKEN:
        return
    provided = str(token_query or "").strip() or (_extract_bearer_secret(authorization) or "")
    if not provided or provided != LCP_API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid control-plane admin token")


def _require_admin_token(authorization: str | None = Header(default=None)) -> None:
    _validate_admin_auth_token(authorization=authorization)


def _require_installation_auth(
    authorization: str | None = Header(default=None),
    db: Session = Depends(_get_db),
) -> InstallationAuthContext:
    provided = _extract_bearer_secret(authorization)
    if LCP_API_TOKEN and provided == LCP_API_TOKEN:
        return InstallationAuthContext(auth_type="admin", customer_ref=None)

    if provided:
        token_hash = _secret_hash(provided)
        client_token = db.execute(
            select(ClientToken).where(
                ClientToken.token_hash == token_hash,
                ClientToken.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if client_token is not None:
            token_metadata = _load_metadata(client_token.metadata_json)
            raw_activation_code_id = token_metadata.get("activation_code_id")
            activation_code_id: int | None = None
            try:
                candidate = int(raw_activation_code_id)
                if candidate > 0:
                    activation_code_id = candidate
            except Exception:
                activation_code_id = None
            return InstallationAuthContext(
                auth_type="client",
                customer_ref=client_token.customer_ref,
                activation_code_id=activation_code_id,
                issued_operating_system=_normalize_operating_system(token_metadata.get("issued_operating_system")),
                issued_ip=str(token_metadata.get("issued_ip") or "").strip()[:128] or None,
            )

    if not LCP_API_TOKEN:
        has_client_tokens = db.execute(
            select(ClientToken.id).where(ClientToken.is_active.is_(True)).limit(1)
        ).scalar_one_or_none()
        if has_client_tokens is None:
            return InstallationAuthContext(auth_type="anonymous", customer_ref=None)

    raise HTTPException(status_code=401, detail="Invalid control-plane token")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_beta_plan_active(now: datetime | None = None) -> bool:
    current = now or _now_utc()
    if LCP_BETA_PLAN_VALID_UNTIL is None:
        return True
    return current < LCP_BETA_PLAN_VALID_UNTIL


def _canonicalize_subscription_status(value: str | None) -> str:
    status_value = str(value or "").strip().lower()
    return SUBSCRIPTION_STATUS_ALIASES.get(status_value, status_value)


def _normalize_subscription_status(value: str | None) -> str:
    status_value = _canonicalize_subscription_status(value)
    if status_value not in SUPPORTED_SUBSCRIPTION_STATUSES:
        raise HTTPException(status_code=400, detail="Unsupported subscription_status")
    return status_value


def _normalize_plan_code_for_status(
    *,
    status_value: str,
    plan_code: str | None,
    existing_plan_code: str | None = None,
) -> str | None:
    requested = str(plan_code or "").strip()
    requested_lower = requested.lower()
    existing = str(existing_plan_code or "").strip()
    existing_lower = existing.lower()

    if status_value in STATUS_CANONICAL_PLAN_CODE:
        canonical = STATUS_CANONICAL_PLAN_CODE[status_value]
        if requested and requested_lower != canonical:
            raise HTTPException(
                status_code=400,
                detail=f"plan_code must be '{canonical}' when subscription_status is '{status_value}'",
            )
        return canonical

    resolved = requested or existing
    resolved_lower = resolved.lower() if resolved else ""

    if status_value in {"active", "grace"}:
        if not resolved:
            raise HTTPException(
                status_code=400,
                detail=f"plan_code is required when subscription_status is '{status_value}'",
            )
        if resolved_lower in RESERVED_PLAN_CODES:
            raise HTTPException(
                status_code=400,
                detail=f"plan_code '{resolved_lower}' is not allowed when subscription_status is '{status_value}'",
            )
        return resolved

    if status_value == "none":
        # "none" means no subscription attached; always clear plan code.
        return None

    return resolved or None


def _resolve_subscription_valid_until(
    *,
    status_value: str,
    requested_valid_until: str | None,
    existing_valid_until: datetime | None = None,
) -> datetime | None:
    normalized_existing_valid_until = existing_valid_until
    if normalized_existing_valid_until and normalized_existing_valid_until.tzinfo is None:
        normalized_existing_valid_until = normalized_existing_valid_until.replace(tzinfo=timezone.utc)
    if normalized_existing_valid_until:
        normalized_existing_valid_until = normalized_existing_valid_until.astimezone(timezone.utc)

    if status_value == "lifetime":
        return None
    if status_value == "trialing":
        parsed = _parse_iso_datetime(requested_valid_until)
        resolved = parsed or normalized_existing_valid_until
        if resolved is None:
            raise HTTPException(status_code=400, detail="valid_until is required for trialing subscriptions")
        if resolved <= _now_utc():
            raise HTTPException(status_code=400, detail="valid_until must be in the future")
        return resolved
    if status_value == "beta":
        parsed = _parse_iso_datetime(requested_valid_until)
        resolved = parsed or normalized_existing_valid_until
        if resolved and resolved <= _now_utc():
            raise HTTPException(status_code=400, detail="valid_until must be in the future")
        return resolved
    if status_value == "none":
        return None
    return _parse_iso_datetime(requested_valid_until)


def _ensure_installation_has_customer_ref(
    installation: Installation,
    payload_customer_ref: str | None = None,
) -> None:
    requested_customer_ref = str(payload_customer_ref or "").strip()
    if requested_customer_ref:
        normalized = _normalize_customer_ref(requested_customer_ref)
        current_customer_ref = str(installation.customer_ref or "").strip()
        if current_customer_ref and current_customer_ref != normalized:
            raise HTTPException(
                status_code=403,
                detail="customer_ref in request does not match existing installation customer_ref",
            )
        installation.customer_ref = normalized

    if str(installation.customer_ref or "").strip():
        return

    # Backfill any missing customer assignment with a deterministic shared bucket.
    installation.customer_ref = LCP_UNASSIGNED_CUSTOMER_REF
    merged_metadata = _load_metadata(installation.metadata_json)
    merged_metadata.setdefault("customer_ref_auto_assigned", True)
    merged_metadata.setdefault("customer_ref_auto_assigned_at", _now_utc().isoformat())
    installation.metadata_json = _dump_metadata(merged_metadata)


def _apply_subscription_update_to_installation(
    installation: Installation,
    *,
    status_value: str,
    plan_code: str | None,
    customer_ref: str | None,
    valid_until: datetime | None,
    metadata: dict[str, Any] | None,
) -> None:
    installation.subscription_status = status_value

    installation.plan_code = _normalize_plan_code_for_status(
        status_value=status_value,
        plan_code=plan_code,
        existing_plan_code=installation.plan_code,
    )

    requested_customer_ref = str(customer_ref or "").strip()
    if requested_customer_ref:
        installation.customer_ref = _normalize_customer_ref(requested_customer_ref)
    installation.subscription_valid_until = valid_until

    merged_metadata = _load_metadata(installation.metadata_json)
    merged_metadata.update(metadata or {})
    installation.metadata_json = _dump_metadata(merged_metadata)


def _load_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _load_json_string_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        candidate = str(item or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result


def _dump_metadata(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _normalize_activation_code(value: str | None) -> str:
    raw = str(value or "").upper()
    return "".join(ch for ch in raw if ch.isalnum())


def _activation_code_hash(value: str | None) -> str:
    normalized = _normalize_activation_code(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _activation_code_suffix(value: str | None) -> str:
    normalized = _normalize_activation_code(value)
    if len(normalized) <= 6:
        return normalized
    return normalized[-6:]


def _client_token_suffix(value: str | None) -> str:
    normalized = str(value or "").strip()
    if len(normalized) <= 8:
        return normalized
    return normalized[-8:]


def _generate_client_token() -> str:
    if not LCP_CLIENT_TOKEN_BUNDLE_PASSWORD:
        return f"lcp_{secrets.token_urlsafe(30)}"

    segment_index = LCP_CLIENT_TOKEN_BUNDLE_SEGMENT_INDEX
    if segment_index < 0:
        raise RuntimeError("LCP_CLIENT_TOKEN_BUNDLE_SEGMENT_INDEX must be zero or greater")

    # Keep the historical `lcp_` prefix while exposing a deterministic segment
    # for runtime bundle decryption.
    segments: list[str] = [f"lcp_{secrets.token_hex(16)}", secrets.token_hex(8), secrets.token_hex(8)]
    if segment_index >= len(segments):
        segments.extend(secrets.token_hex(8) for _ in range(segment_index - len(segments) + 1))
    segments[segment_index] = LCP_CLIENT_TOKEN_BUNDLE_PASSWORD
    return LCP_CLIENT_TOKEN_DELIMITER.join(segments)


def _generate_activation_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"ACT-{raw[0:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}"


def _serialize_activation_code(code: ActivationCode) -> dict[str, Any]:
    valid_until = code.valid_until
    if valid_until and valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=timezone.utc)
    if valid_until:
        valid_until = valid_until.astimezone(timezone.utc)
    return {
        "id": code.id,
        "customer_ref": code.customer_ref,
        "plan_code": code.plan_code,
        "valid_until": valid_until.isoformat() if valid_until else None,
        "max_installations": int(code.max_installations),
        "is_active": bool(code.is_active),
        "usage_count": int(code.usage_count),
        "code_suffix": code.code_suffix,
        "last_used_at": code.last_used_at.isoformat() if code.last_used_at else None,
        "metadata": _load_metadata(code.metadata_json),
        "updated_at": code.updated_at.isoformat(),
        "created_at": code.created_at.isoformat(),
    }


def _serialize_client_token(record: ClientToken) -> dict[str, Any]:
    return {
        "id": record.id,
        "customer_ref": record.customer_ref,
        "is_active": bool(record.is_active),
        "token_suffix": record.token_suffix,
        "metadata": _load_metadata(record.metadata_json),
        "updated_at": record.updated_at.isoformat(),
        "created_at": record.created_at.isoformat(),
    }


def _serialize_waitlist_entry(record: WaitlistEntry) -> dict[str, Any]:
    return {
        "id": record.id,
        "email": record.email,
        "source": record.source,
        "status": record.status,
        "metadata": _load_metadata(record.metadata_json),
        "updated_at": record.updated_at.isoformat(),
        "created_at": record.created_at.isoformat(),
    }


def _serialize_contact_request(record: ContactRequest) -> dict[str, Any]:
    return {
        "id": record.id,
        "request_type": record.request_type,
        "email": record.email,
        "source": record.source,
        "status": record.status,
        "metadata": _load_metadata(record.metadata_json),
        "updated_at": record.updated_at.isoformat(),
        "created_at": record.created_at.isoformat(),
    }


def _serialize_app_notification_campaign(record: AppNotificationCampaign) -> dict[str, Any]:
    return {
        "id": record.notification_id,
        "title": str(record.title or "").strip() or None,
        "message": record.message,
        "severity": record.severity,
        "notification_type": record.notification_type,
        "audience_kind": record.audience_kind,
        "audience_values": _load_json_string_list(record.audience_values_json),
        "is_active": bool(record.is_active),
        "active_from": record.active_from.isoformat() if record.active_from else None,
        "active_until": record.active_until.isoformat() if record.active_until else None,
        "payload": _load_metadata(record.payload_json),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def _serialize_bug_report(record: BugReport) -> dict[str, Any]:
    return {
        "id": record.id,
        "report_id": record.report_id,
        "installation_id": record.installation_id,
        "workspace_id": record.workspace_id,
        "customer_ref": record.customer_ref,
        "source": record.source,
        "status": record.status,
        "severity": record.severity,
        "title": record.title,
        "description": record.description,
        "steps_to_reproduce": record.steps_to_reproduce,
        "expected_behavior": record.expected_behavior,
        "actual_behavior": record.actual_behavior,
        "reporter_user_id": record.reporter_user_id,
        "reporter_username": record.reporter_username,
        "triage_note": record.triage_note,
        "assignee": record.assignee,
        "dedup_key": record.dedup_key,
        "metadata": _load_metadata(record.metadata_json),
        "updated_at": record.updated_at.isoformat(),
        "created_at": record.created_at.isoformat(),
    }


def _bug_report_dedup_key(*, installation_id: str, title: str, description: str, severity: str) -> str:
    normalized_title = str(title or "").strip().lower()
    normalized_description = str(description or "").strip().lower()
    normalized_severity = str(severity or "").strip().lower()
    raw = "||".join([installation_id, normalized_title, normalized_description, normalized_severity])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _feedback_identity_to_pseudo_email(*, identity: str | None, fallback: str) -> str:
    normalized_identity = str(identity or "").strip().lower()
    local_part = re.sub(r"[^a-z0-9._-]+", "-", normalized_identity).strip(".-_")
    if not local_part:
        local_part = re.sub(r"[^a-z0-9._-]+", "-", str(fallback or "").strip().lower()).strip(".-_") or "feedback"
    return f"{local_part[:64]}@feedback.local"


def _app_notification_matches_installation(
    *,
    campaign: AppNotificationCampaign,
    installation: Installation,
    customer_email: str | None,
    now: datetime,
) -> bool:
    if not bool(campaign.is_active):
        return False
    if campaign.active_from is not None:
        active_from = campaign.active_from
        if active_from.tzinfo is None:
            active_from = active_from.replace(tzinfo=timezone.utc)
        if active_from.astimezone(timezone.utc) > now:
            return False
    if campaign.active_until is not None:
        active_until = campaign.active_until
        if active_until.tzinfo is None:
            active_until = active_until.replace(tzinfo=timezone.utc)
        if active_until.astimezone(timezone.utc) <= now:
            return False

    audience_kind = str(campaign.audience_kind or "").strip().lower() or "all"
    if audience_kind == "all":
        return True

    audience_values = set(_load_json_string_list(campaign.audience_values_json))
    if not audience_values:
        return False

    if audience_kind == "installation_id":
        return str(installation.installation_id or "").strip() in audience_values
    if audience_kind == "customer_ref":
        return str(installation.customer_ref or "").strip() in audience_values
    if audience_kind == "customer_email":
        return str(customer_email or "").strip().lower() in audience_values
    return False


def _build_installation_notifications(db: Session, installation: Installation) -> list[dict[str, Any]]:
    now = _now_utc()
    customer_email = _resolve_customer_email_for_installation(db, installation)
    campaigns = db.execute(
        select(AppNotificationCampaign)
        .where(AppNotificationCampaign.is_active == True)  # noqa: E712
        .order_by(AppNotificationCampaign.created_at.desc(), AppNotificationCampaign.id.desc())
    ).scalars().all()

    notifications: list[dict[str, Any]] = []
    for campaign in campaigns:
        if not _app_notification_matches_installation(
            campaign=campaign,
            installation=installation,
            customer_email=customer_email,
            now=now,
        ):
            continue
        payload = _load_metadata(campaign.payload_json)
        title = str(campaign.title or "").strip()
        if title:
            payload = {"title": title, **payload}
        notifications.append(
            {
                "id": campaign.notification_id,
                "message": campaign.message,
                "is_read": False,
                "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
                "notification_type": campaign.notification_type,
                "severity": campaign.severity,
                "dedupe_key": campaign.notification_id,
                "source_event": "control-plane.notification",
                "payload": payload,
            }
        )
    return notifications


def _active_customer_installations(db: Session, customer_ref: str) -> list[Installation]:
    matches = db.execute(
        select(Installation).where(Installation.customer_ref == customer_ref)
    ).scalars().all()
    active: list[Installation] = []
    for installation in matches:
        status = str(_compute_entitlement(installation).get("status") or "").strip().lower()
        if status in {"active", "grace"}:
            active.append(installation)
    return active


def _resolve_customer_max_installations(
    db: Session,
    *,
    customer_ref: str,
    activation_code_id: int | None = None,
) -> int:
    normalized_customer_ref = str(customer_ref or "").strip()
    if not normalized_customer_ref:
        return int(LCP_DEFAULT_MAX_INSTALLATIONS)

    if activation_code_id is not None and activation_code_id > 0:
        code = db.execute(
            select(ActivationCode).where(
                ActivationCode.id == activation_code_id,
                ActivationCode.customer_ref == normalized_customer_ref,
            )
        ).scalar_one_or_none()
        if code is not None:
            return max(1, int(code.max_installations))

    limits = db.execute(
        select(ActivationCode.max_installations).where(
            ActivationCode.customer_ref == normalized_customer_ref,
            ActivationCode.is_active.is_(True),
        )
    ).scalars().all()
    normalized_limits: list[int] = []
    for raw_value in limits:
        try:
            parsed = int(raw_value)
        except Exception:
            continue
        if parsed > 0:
            normalized_limits.append(parsed)
    if normalized_limits:
        return max(normalized_limits)
    return int(LCP_DEFAULT_MAX_INSTALLATIONS)


def _activation_code_skips_seat_limits(
    db: Session,
    *,
    activation_code_id: int | None,
    customer_ref: str | None = None,
) -> bool:
    normalized_code_id = int(activation_code_id or 0)
    if normalized_code_id <= 0:
        return False
    query = select(ActivationCode.plan_code).where(ActivationCode.id == normalized_code_id)
    normalized_customer_ref = str(customer_ref or "").strip()
    if normalized_customer_ref:
        query = query.where(ActivationCode.customer_ref == normalized_customer_ref)
    code_plan = db.execute(query).scalar_one_or_none()
    return _plan_code_skips_seat_limits(code_plan)


def _enforce_installation_customer_scope(installation: Installation, auth_context: InstallationAuthContext) -> None:
    token_customer = str(auth_context.customer_ref or "").strip()
    if not token_customer:
        return
    current_customer = str(installation.customer_ref or "").strip()
    if current_customer and current_customer != token_customer:
        raise HTTPException(status_code=403, detail="Token is not allowed for this installation")
    if not current_customer:
        installation.customer_ref = token_customer


def _compute_entitlement(installation: Installation) -> dict[str, Any]:
    now = _now_utc()
    trial_ends_at = installation.trial_ends_at
    if trial_ends_at.tzinfo is None:
        trial_ends_at = trial_ends_at.replace(tzinfo=timezone.utc)
    trial_ends_at = trial_ends_at.astimezone(timezone.utc)

    valid_until = installation.subscription_valid_until
    if valid_until and valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=timezone.utc)
    if valid_until:
        valid_until = valid_until.astimezone(timezone.utc)

    subscription_status = _canonicalize_subscription_status(installation.subscription_status or "none")
    if subscription_status not in SUPPORTED_SUBSCRIPTION_STATUSES:
        subscription_status = "none"

    status = "expired"
    plan_code = installation.plan_code or None
    effective_valid_until = valid_until
    entitlement_reason = "expired"
    if subscription_status == "lifetime":
        status = "active"
        plan_code = plan_code or "lifetime"
        effective_valid_until = None
        entitlement_reason = "subscription_lifetime"
    elif subscription_status == "beta":
        plan_code = plan_code or "beta"
        if effective_valid_until is None or effective_valid_until > now:
            status = "active"
            entitlement_reason = "subscription_beta"
        else:
            status = "expired"
            entitlement_reason = "subscription_beta_expired"
    elif subscription_status == "trialing":
        plan_code = plan_code or "trial"
        if valid_until and valid_until > now:
            status = "active"
            effective_valid_until = valid_until
            entitlement_reason = "subscription_trialing"
        else:
            status = "expired"
            effective_valid_until = None
            entitlement_reason = "subscription_trialing_expired"
    elif subscription_status == "active" and (valid_until is None or valid_until > now):
        status = "active"
        entitlement_reason = "subscription_active"
    elif subscription_status == "grace" and valid_until and valid_until > now:
        status = "grace"
        entitlement_reason = "subscription_grace"
    elif subscription_status == "none":
        status = "expired"
        effective_valid_until = None
        entitlement_reason = "subscription_none"
    else:
        effective_valid_until = None

    token_expires_at = now + timedelta(seconds=LCP_TOKEN_TTL_SECONDS)
    metadata = dict(_load_metadata(installation.metadata_json))
    metadata["subscription_status"] = subscription_status
    metadata["subscription_valid_until"] = valid_until.isoformat() if valid_until else None
    metadata["effective_valid_until"] = effective_valid_until.isoformat() if effective_valid_until else None
    metadata["entitlement_reason"] = entitlement_reason

    return {
        "installation_id": installation.installation_id,
        "status": status,
        "plan_code": plan_code,
        "valid_from": now.isoformat(),
        "valid_until": effective_valid_until.isoformat() if effective_valid_until else None,
        "trial_ends_at": trial_ends_at.isoformat(),
        "token_expires_at": token_expires_at.isoformat(),
        "metadata": metadata,
    }


def _resolve_request_ip(request: Request) -> str | None:
    forwarded = str(request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:128]
    real_ip = str(request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return real_ip[:128]
    if request.client and request.client.host:
        return str(request.client.host).strip()[:128] or None
    return None


def _upsert_installation(
    db: Session,
    payload: InstallationRegisterRequest | InstallationHeartbeatRequest | InstallationActivateRequest,
) -> Installation:
    installation = db.execute(
        select(Installation).where(Installation.installation_id == payload.installation_id)
    ).scalar_one_or_none()

    now = _now_utc()
    if installation is None:
        trial_ends_at = now + timedelta(days=LCP_TRIAL_DAYS)
        metadata = dict(payload.metadata or {})
        metadata.setdefault("beta_auto_assigned", True)
        metadata.setdefault("beta_auto_assigned_reason", "install-registration")
        metadata.setdefault("beta_auto_assigned_at", now.isoformat())
        operating_system = _resolve_operating_system_from_payload(payload)
        installation = Installation(
            installation_id=payload.installation_id,
            workspace_id=payload.workspace_id,
            customer_ref=str(payload.customer_ref or "").strip() or None,
            operating_system=operating_system,
            plan_code="beta",
            subscription_status="beta",
            subscription_valid_until=LCP_BETA_PLAN_VALID_UNTIL,
            trial_started_at=now,
            trial_ends_at=trial_ends_at,
            metadata_json=_dump_metadata(metadata),
        )
        db.add(installation)
        db.flush()
        return installation

    changed = False
    if payload.workspace_id and installation.workspace_id != payload.workspace_id:
        installation.workspace_id = payload.workspace_id
        changed = True

    requested_customer_ref = str(payload.customer_ref or "").strip()
    if requested_customer_ref:
        normalized_customer_ref = _normalize_customer_ref(requested_customer_ref)
        current_customer_ref = str(installation.customer_ref or "").strip()
        if current_customer_ref and current_customer_ref != normalized_customer_ref:
            raise HTTPException(
                status_code=403,
                detail="customer_ref in request does not match existing installation customer_ref",
            )
        if installation.customer_ref != normalized_customer_ref:
            installation.customer_ref = normalized_customer_ref
            changed = True

    resolved_operating_system = _resolve_operating_system_from_payload(payload)
    if resolved_operating_system and installation.operating_system != resolved_operating_system:
        installation.operating_system = resolved_operating_system
        changed = True

    merged_metadata = _load_metadata(installation.metadata_json)
    if payload.metadata:
        merged_metadata.update(payload.metadata)
        installation.metadata_json = _dump_metadata(merged_metadata)
        changed = True

    if changed:
        db.flush()
    return installation


def _apply_activation_code_plan_for_client_auth(
    db: Session,
    *,
    installation: Installation,
    auth_context: InstallationAuthContext,
) -> bool:
    if auth_context.auth_type != "client":
        return False
    activation_code_id = int(auth_context.activation_code_id or 0)
    if activation_code_id <= 0:
        return False

    token_customer_ref = str(auth_context.customer_ref or "").strip()
    query = select(ActivationCode).where(ActivationCode.id == activation_code_id)
    if token_customer_ref:
        query = query.where(ActivationCode.customer_ref == token_customer_ref)
    activation_code = db.execute(query).scalar_one_or_none()
    if activation_code is None:
        return False

    activation_plan_code = str(activation_code.plan_code or "").strip().lower() or "monthly"
    if activation_plan_code != "lifetime":
        return False

    changed = False
    if installation.plan_code != "lifetime":
        installation.plan_code = "lifetime"
        changed = True
    if installation.subscription_status != "lifetime":
        installation.subscription_status = "lifetime"
        changed = True
    if installation.subscription_valid_until is not None:
        installation.subscription_valid_until = None
        changed = True

    metadata = _load_metadata(installation.metadata_json)
    metadata_changed = False
    if metadata.get("activation_code_id") != activation_code.id:
        metadata["activation_code_id"] = activation_code.id
        metadata_changed = True
    if metadata.get("activation_code_suffix") != activation_code.code_suffix:
        metadata["activation_code_suffix"] = activation_code.code_suffix
        metadata_changed = True
    if metadata.get("activation_plan_code") != activation_plan_code:
        metadata["activation_plan_code"] = activation_plan_code
        metadata_changed = True
    if not str(installation.operating_system or "").strip():
        activation_metadata = _load_metadata(activation_code.metadata_json)
        activation_operating_system = _normalize_operating_system(
            activation_metadata.get("install_exchange_last_operating_system")
        )
        if activation_operating_system:
            installation.operating_system = activation_operating_system
            metadata_changed = True
    for key in ("beta_auto_assigned", "beta_auto_assigned_reason", "beta_auto_assigned_at"):
        if key in metadata:
            metadata.pop(key, None)
            metadata_changed = True
    if metadata_changed:
        installation.metadata_json = _dump_metadata(metadata)
        changed = True

    if changed:
        db.flush()
    return changed


def _apply_client_token_operating_system(
    installation: Installation,
    auth_context: InstallationAuthContext,
) -> bool:
    if auth_context.auth_type != "client":
        return False
    if str(installation.operating_system or "").strip():
        return False

    issued_operating_system = _normalize_operating_system(auth_context.issued_operating_system)
    if not issued_operating_system:
        return False

    installation.operating_system = issued_operating_system
    return True


def _apply_client_token_activation_ip(
    installation: Installation,
    auth_context: InstallationAuthContext,
) -> bool:
    if auth_context.auth_type != "client":
        return False

    issued_ip = str(auth_context.issued_ip or "").strip()
    if not issued_ip:
        return False

    metadata = _load_metadata(installation.metadata_json)
    if str(metadata.get("activation_ip") or "").strip():
        return False

    metadata["activation_ip"] = issued_ip
    installation.metadata_json = _dump_metadata(metadata)
    return True


def _sign_entitlement_if_configured(entitlement_payload: dict[str, Any]) -> dict[str, Any] | None:
    if not LCP_SIGNING_PRIVATE_KEY_PEM:
        return None
    return sign_entitlement_payload(
        entitlement_payload,
        private_key_pem=LCP_SIGNING_PRIVATE_KEY_PEM,
        key_id=LCP_SIGNING_KEY_ID,
    )


def _build_entitlement_bundle(entitlement_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    signed_token = _sign_entitlement_if_configured(entitlement_payload)
    if LCP_REQUIRE_SIGNED_TOKENS and signed_token is None:
        raise HTTPException(status_code=500, detail="Signed tokens are required but signing key is not configured")
    return entitlement_payload, signed_token


def _installation_customer_email(metadata: dict[str, Any]) -> str | None:
    candidate_fields = ("issued_to_email", "customer_email", "to_email", "contact_email", "email")
    for key in candidate_fields:
        value = metadata.get(key)
        normalized = str(value or "").strip().lower()
        if normalized and EMAIL_PATTERN.fullmatch(normalized):
            return normalized
    return None


def _update_lead_status_by_email(
    db: Session,
    *,
    email: str,
    target_status: str,
    reason: str,
) -> dict[str, int | str]:
    normalized_email = _normalize_email(email)
    normalized_target_status = str(target_status or "").strip().lower()
    if normalized_target_status not in SUPPORTED_LEAD_STATUSES:
        raise HTTPException(status_code=400, detail=f"Unsupported lead status '{normalized_target_status}'")

    now_iso = _now_utc().isoformat()
    matched_waitlist = 0
    matched_contact_requests = 0
    updated_waitlist = 0
    updated_contact_requests = 0

    waitlist_rows = db.execute(select(WaitlistEntry).where(WaitlistEntry.email == normalized_email)).scalars().all()
    for row in waitlist_rows:
        matched_waitlist += 1
        current_status = str(row.status or "").strip().lower() or LEAD_STATUS_PENDING
        if current_status == LEAD_STATUS_CONVERTED and normalized_target_status != LEAD_STATUS_CONVERTED:
            continue
        if current_status == normalized_target_status:
            continue
        metadata = _load_metadata(row.metadata_json)
        metadata["lead_status_reason"] = reason
        metadata["lead_status_from"] = current_status
        metadata["lead_status_to"] = normalized_target_status
        metadata["lead_status_updated_at"] = now_iso
        if normalized_target_status == LEAD_STATUS_ONBOARDING_SENT:
            metadata.setdefault("onboarding_sent_at", now_iso)
        if normalized_target_status == LEAD_STATUS_CONVERTED:
            metadata["converted_at"] = now_iso
        row.status = normalized_target_status
        row.metadata_json = _dump_metadata(metadata)
        updated_waitlist += 1

    contact_rows = db.execute(select(ContactRequest).where(ContactRequest.email == normalized_email)).scalars().all()
    for row in contact_rows:
        matched_contact_requests += 1
        current_status = str(row.status or "").strip().lower() or LEAD_STATUS_PENDING
        if current_status == LEAD_STATUS_CONVERTED and normalized_target_status != LEAD_STATUS_CONVERTED:
            continue
        if current_status == normalized_target_status:
            continue
        metadata = _load_metadata(row.metadata_json)
        metadata["lead_status_reason"] = reason
        metadata["lead_status_from"] = current_status
        metadata["lead_status_to"] = normalized_target_status
        metadata["lead_status_updated_at"] = now_iso
        if normalized_target_status == LEAD_STATUS_ONBOARDING_SENT:
            metadata.setdefault("onboarding_sent_at", now_iso)
        if normalized_target_status == LEAD_STATUS_CONVERTED:
            metadata["converted_at"] = now_iso
        row.status = normalized_target_status
        row.metadata_json = _dump_metadata(metadata)
        updated_contact_requests += 1

    return {
        "email": normalized_email,
        "target_status": normalized_target_status,
        "matched_waitlist": matched_waitlist,
        "matched_contact_requests": matched_contact_requests,
        "updated_waitlist": updated_waitlist,
        "updated_contact_requests": updated_contact_requests,
        "matched_total": matched_waitlist + matched_contact_requests,
        "updated_total": updated_waitlist + updated_contact_requests,
    }


def _resolve_customer_email_for_installation(db: Session, installation: Installation) -> str | None:
    metadata = _load_metadata(installation.metadata_json)
    direct_email = _installation_customer_email(metadata)
    if direct_email:
        return direct_email

    customer_ref = str(installation.customer_ref or "").strip()
    if not customer_ref or customer_ref == LCP_UNASSIGNED_CUSTOMER_REF:
        return None
    return _lookup_customer_email_by_customer_ref(db, {customer_ref}).get(customer_ref)


def _maybe_mark_lead_converted_for_installation(
    db: Session,
    *,
    installation: Installation,
    entitlement: dict[str, Any],
    reason: str,
) -> dict[str, int | str] | None:
    entitlement_status = str(entitlement.get("status") or "").strip().lower()
    if entitlement_status not in {"active", "grace"}:
        return None

    customer_email = _resolve_customer_email_for_installation(db, installation)
    if not customer_email:
        return None

    return _update_lead_status_by_email(
        db,
        email=customer_email,
        target_status=LEAD_STATUS_CONVERTED,
        reason=reason,
    )


def _lookup_customer_email_by_customer_ref(db: Session, customer_refs: set[str]) -> dict[str, str]:
    normalized_refs = {str(customer_ref or "").strip() for customer_ref in customer_refs}
    normalized_refs = {customer_ref for customer_ref in normalized_refs if customer_ref}
    if not normalized_refs:
        return {}

    email_by_customer_ref: dict[str, str] = {}

    activation_rows = db.execute(
        select(ActivationCode)
        .where(ActivationCode.customer_ref.in_(sorted(normalized_refs)))
        .order_by(ActivationCode.updated_at.desc(), ActivationCode.id.desc())
    ).scalars().all()
    for record in activation_rows:
        customer_ref = str(record.customer_ref or "").strip()
        if not customer_ref or customer_ref in email_by_customer_ref:
            continue
        email = _installation_customer_email(_load_metadata(record.metadata_json))
        if email:
            email_by_customer_ref[customer_ref] = email

    client_token_rows = db.execute(
        select(ClientToken)
        .where(ClientToken.customer_ref.in_(sorted(normalized_refs)))
        .order_by(ClientToken.updated_at.desc(), ClientToken.id.desc())
    ).scalars().all()
    for record in client_token_rows:
        customer_ref = str(record.customer_ref or "").strip()
        if not customer_ref or customer_ref in email_by_customer_ref:
            continue
        email = _installation_customer_email(_load_metadata(record.metadata_json))
        if email:
            email_by_customer_ref[customer_ref] = email

    return email_by_customer_ref


def _serialize_installation(
    installation: Installation,
    *,
    customer_email_override: str | None = None,
) -> dict[str, Any]:
    metadata = _load_metadata(installation.metadata_json)
    activation_ip = (
        str(metadata.get("activation_ip") or "").strip()
        or str(metadata.get("install_exchange_last_ip") or "").strip()
        or None
    )
    customer_email = (
        str(customer_email_override or "").strip().lower() or _installation_customer_email(metadata)
    )
    subscription_status = _canonicalize_subscription_status(installation.subscription_status)
    if subscription_status not in SUPPORTED_SUBSCRIPTION_STATUSES:
        subscription_status = "none"
    subscription_valid_until = installation.subscription_valid_until
    if subscription_valid_until and subscription_valid_until.tzinfo is None:
        subscription_valid_until = subscription_valid_until.replace(tzinfo=timezone.utc)
    if subscription_valid_until:
        subscription_valid_until = subscription_valid_until.astimezone(timezone.utc)
    return {
        "installation_id": installation.installation_id,
        "workspace_id": installation.workspace_id,
        "customer_ref": installation.customer_ref,
        "operating_system": installation.operating_system,
        "plan_code": installation.plan_code,
        "subscription_status": subscription_status,
        "subscription_valid_until": subscription_valid_until.isoformat() if subscription_valid_until else None,
        "trial_started_at": installation.trial_started_at.isoformat(),
        "trial_ends_at": installation.trial_ends_at.isoformat(),
        "activation_ip": activation_ip,
        "customer_email": customer_email,
        "metadata": metadata,
        "created_at": installation.created_at.isoformat(),
        "updated_at": installation.updated_at.isoformat(),
    }


def _ensure_installation_schema_columns() -> None:
    required_columns: dict[str, str] = {
        "operating_system": "VARCHAR(64)",
    }
    try:
        existing_columns = {column["name"] for column in inspect(engine).get_columns("installations")}
    except Exception:
        return

    missing_columns = [name for name in required_columns if name not in existing_columns]
    if not missing_columns:
        return

    with engine.begin() as connection:
        for column_name in missing_columns:
            column_type = required_columns[column_name]
            connection.execute(text(f"ALTER TABLE installations ADD COLUMN {column_name} {column_type}"))


app = FastAPI(title="m4tr1x Licensing Control Plane")
app.add_middleware(
    CORSMiddleware,
    allow_origins=LCP_CORS_ORIGINS if LCP_CORS_ORIGINS else ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_installation_schema_columns()
    if LCP_REQUIRE_SIGNED_TOKENS and not LCP_SIGNING_PRIVATE_KEY_PEM:
        raise RuntimeError("LCP_REQUIRE_SIGNED_TOKENS is enabled but LCP_SIGNING_PRIVATE_KEY_PEM is not configured")
    if LCP_CLIENT_TOKEN_BUNDLE_SEGMENT_INDEX < 0:
        raise RuntimeError("LCP_CLIENT_TOKEN_BUNDLE_SEGMENT_INDEX must be zero or greater")
    if LCP_CLIENT_TOKEN_BUNDLE_PASSWORD and LCP_CLIENT_TOKEN_DELIMITER in LCP_CLIENT_TOKEN_BUNDLE_PASSWORD:
        raise RuntimeError("LCP_CLIENT_TOKEN_BUNDLE_PASSWORD must not contain LCP_CLIENT_TOKEN_DELIMITER")
    if LCP_SIGNING_PRIVATE_KEY_PEM:
        # Fail fast on invalid keys during startup.
        try:
            _sign_entitlement_if_configured({"installation_id": "startup-check", "status": "trial"})
        except SigningError as exc:
            raise RuntimeError(f"Failed to initialize signing key: {exc}") from exc

    # Keep data consistent for customer-first operations.
    with SessionLocal() as db:
        should_commit = False
        records = db.execute(
            select(Installation).where(
                or_(
                    Installation.customer_ref.is_(None),
                    Installation.customer_ref == "",
                )
            )
        ).scalars().all()
        if records:
            now_iso = _now_utc().isoformat()
            for installation in records:
                installation.customer_ref = LCP_UNASSIGNED_CUSTOMER_REF
                merged_metadata = _load_metadata(installation.metadata_json)
                merged_metadata.setdefault("customer_ref_auto_assigned", True)
                merged_metadata.setdefault("customer_ref_auto_assigned_at", now_iso)
                installation.metadata_json = _dump_metadata(merged_metadata)
            should_commit = True

        installations = db.execute(
            select(Installation).where(
                Installation.customer_ref.is_not(None),
                Installation.customer_ref != "",
            )
        ).scalars().all()
        customer_refs_for_email_lookup: set[str] = set()
        installations_missing_email: list[Installation] = []
        for installation in installations:
            metadata = _load_metadata(installation.metadata_json)
            if _installation_customer_email(metadata):
                continue
            customer_ref = str(installation.customer_ref or "").strip()
            if not customer_ref or customer_ref == LCP_UNASSIGNED_CUSTOMER_REF:
                continue
            customer_refs_for_email_lookup.add(customer_ref)
            installations_missing_email.append(installation)

        if installations_missing_email and customer_refs_for_email_lookup:
            email_by_customer_ref = _lookup_customer_email_by_customer_ref(db, customer_refs_for_email_lookup)
            if email_by_customer_ref:
                now_iso = _now_utc().isoformat()
                for installation in installations_missing_email:
                    customer_ref = str(installation.customer_ref or "").strip()
                    if not customer_ref:
                        continue
                    resolved_email = email_by_customer_ref.get(customer_ref)
                    if not resolved_email:
                        continue
                    merged_metadata = _load_metadata(installation.metadata_json)
                    if _installation_customer_email(merged_metadata):
                        continue
                    merged_metadata.setdefault("issued_to_email", resolved_email)
                    merged_metadata.setdefault("customer_email_backfilled", True)
                    merged_metadata.setdefault("customer_email_backfilled_at", now_iso)
                    installation.metadata_json = _dump_metadata(merged_metadata)
                    should_commit = True

        if should_commit:
            db.commit()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "timestamp": _now_utc().isoformat(),
        "trial_days": LCP_TRIAL_DAYS,
        "default_max_installations": LCP_DEFAULT_MAX_INSTALLATIONS,
        # Backward-compatible fields kept for existing UI clients.
        "public_beta_free_until": LCP_BETA_PLAN_VALID_UNTIL.isoformat() if LCP_BETA_PLAN_VALID_UNTIL else None,
        "public_beta_active": _is_beta_plan_active(),
        "beta_plan_valid_until": LCP_BETA_PLAN_VALID_UNTIL.isoformat() if LCP_BETA_PLAN_VALID_UNTIL else None,
        "beta_plan_active": _is_beta_plan_active(),
    }


@app.get("/v1/admin/events")
async def admin_events_stream(
    request: Request,
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    _validate_admin_auth_token(token_query=token, authorization=authorization)

    async def event_stream():
        last_revision = -1
        last_heartbeat = _now_utc()
        while True:
            if await request.is_disconnected():
                break

            snapshot = _get_admin_event_snapshot()
            revision = int(snapshot.get("revision") or 0)
            if revision != last_revision:
                yield _format_sse_message("refresh", snapshot, event_id=str(revision))
                last_revision = revision
                last_heartbeat = _now_utc()
            else:
                now = _now_utc()
                if (now - last_heartbeat).total_seconds() >= LCP_ADMIN_SSE_HEARTBEAT_SECONDS:
                    yield _format_sse_message(
                        "heartbeat",
                        {
                            "revision": revision,
                            "at": now.isoformat(),
                        },
                        event_id=str(revision),
                    )
                    last_heartbeat = now
            await asyncio.sleep(LCP_ADMIN_SSE_POLL_SECONDS)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/v1/public/waitlist")
def public_join_waitlist(
    payload: WaitlistJoinRequest,
    request: Request,
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    email = _normalize_email(payload.email)
    source = str(payload.source or "").strip()[:64] or "marketing-site"

    metadata = dict(payload.metadata or {})
    request_ip = _resolve_request_ip(request)
    user_agent = str(request.headers.get("user-agent") or "").strip()[:512]
    if request_ip:
        metadata["request_ip"] = request_ip
    if user_agent:
        metadata["user_agent"] = user_agent

    existing = db.execute(
        select(WaitlistEntry).where(WaitlistEntry.email == email)
    ).scalar_one_or_none()
    if existing is not None:
        merged_metadata = _load_metadata(existing.metadata_json)
        merged_metadata.update(metadata)
        existing.source = source
        existing.metadata_json = _dump_metadata(merged_metadata)
        db.commit()
        db.refresh(existing)
        _publish_admin_event(
            "waitlist",
            "upserted",
            {"email": existing.email, "created": False},
        )
        return {
            "ok": True,
            "created": False,
            "waitlist_entry": _serialize_waitlist_entry(existing),
        }

    record = WaitlistEntry(
        email=email,
        source=source,
        status="pending",
        metadata_json=_dump_metadata(metadata),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    _publish_admin_event(
        "waitlist",
        "created",
        {"email": record.email, "created": True},
    )
    return {
        "ok": True,
        "created": True,
        "waitlist_entry": _serialize_waitlist_entry(record),
    }


@app.post("/v1/public/contact-requests")
def public_create_contact_request(
    payload: ContactRequestCreateRequest,
    request: Request,
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    request_type = _normalize_public_request_type(payload.request_type)
    email = _normalize_email(payload.email)
    source = str(payload.source or "").strip()[:64] or "marketing-site"

    metadata = dict(payload.metadata or {})
    request_ip = _resolve_request_ip(request)
    user_agent = str(request.headers.get("user-agent") or "").strip()[:512]
    if request_ip:
        metadata["request_ip"] = request_ip
    if user_agent:
        metadata["user_agent"] = user_agent

    existing = db.execute(
        select(ContactRequest).where(
            ContactRequest.request_type == request_type,
            ContactRequest.email == email,
        )
    ).scalar_one_or_none()
    if existing is not None:
        merged_metadata = _load_metadata(existing.metadata_json)
        merged_metadata.update(metadata)
        existing.source = source
        existing.metadata_json = _dump_metadata(merged_metadata)
        db.commit()
        db.refresh(existing)
        _publish_admin_event(
            "contact_requests",
            "upserted",
            {"email": existing.email, "request_type": existing.request_type, "created": False},
        )
        return {
            "ok": True,
            "created": False,
            "contact_request": _serialize_contact_request(existing),
        }

    record = ContactRequest(
        request_type=request_type,
        email=email,
        source=source,
        status="pending",
        metadata_json=_dump_metadata(metadata),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    _publish_admin_event(
        "contact_requests",
        "created",
        {"email": record.email, "request_type": record.request_type, "created": True},
    )
    return {
        "ok": True,
        "created": True,
        "contact_request": _serialize_contact_request(record),
    }


@app.post("/v1/support/feedback")
def create_support_feedback(
    payload: SupportFeedbackCreateRequest,
    request: Request,
    auth_context: InstallationAuthContext = Depends(_require_installation_auth),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    installation_id = str(payload.installation_id or "").strip()
    if not installation_id:
        raise HTTPException(status_code=400, detail="installation_id is required")

    title = str(payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    description = str(payload.description or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description is required")

    feedback_type = _normalize_support_feedback_type(payload.feedback_type)
    source = str(payload.source or "").strip()[:64] or "task-app-ui"

    installation = db.execute(
        select(Installation).where(Installation.installation_id == installation_id)
    ).scalar_one_or_none()
    token_customer_ref = str(auth_context.customer_ref or "").strip() or None
    installation_customer_ref = str(installation.customer_ref or "").strip() if installation is not None else ""
    if token_customer_ref and installation_customer_ref and token_customer_ref != installation_customer_ref:
        raise HTTPException(status_code=403, detail="Token is not allowed for this installation")
    if installation is not None and token_customer_ref and not installation_customer_ref:
        installation.customer_ref = token_customer_ref

    workspace_id = str(payload.workspace_id or "").strip()[:64] or None
    customer_ref = token_customer_ref or installation_customer_ref or None
    reporter_username = str(payload.reporter_username or "").strip() or None
    reporter_user_id = str(payload.reporter_user_id or "").strip() or None
    identity_for_email = reporter_username or reporter_user_id or installation_id

    metadata = dict(payload.metadata or {})
    request_ip = _resolve_request_ip(request)
    user_agent = str(request.headers.get("user-agent") or "").strip()[:512]
    if request_ip:
        metadata["request_ip"] = request_ip
    if user_agent:
        metadata["user_agent"] = user_agent
    metadata["installation_id"] = installation_id
    metadata["workspace_id"] = workspace_id
    metadata["customer_ref"] = customer_ref
    metadata["feedback_type"] = feedback_type
    metadata["title"] = title
    metadata["description"] = description
    metadata["reporter_user_id"] = reporter_user_id
    metadata["reporter_username"] = reporter_username

    record = ContactRequest(
        request_type="feedback",
        email=_feedback_identity_to_pseudo_email(identity=identity_for_email, fallback=installation_id),
        source=source,
        status="pending",
        metadata_json=_dump_metadata(metadata),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    _publish_admin_event(
        "contact_requests",
        "created",
        {"id": record.id, "request_type": record.request_type, "created": True},
    )
    return {
        "ok": True,
        "created": True,
        "feedback": _serialize_contact_request(record),
    }


@app.post("/v1/support/bug-reports")
def create_bug_report(
    payload: BugReportCreateRequest,
    request: Request,
    auth_context: InstallationAuthContext = Depends(_require_installation_auth),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    installation_id = str(payload.installation_id or "").strip()
    if not installation_id:
        raise HTTPException(status_code=400, detail="installation_id is required")

    title = str(payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    description = str(payload.description or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description is required")

    severity = _normalize_bug_report_severity(payload.severity)
    source = str(payload.source or "").strip()[:64] or "task-app"

    installation = db.execute(
        select(Installation).where(Installation.installation_id == installation_id)
    ).scalar_one_or_none()
    token_customer_ref = str(auth_context.customer_ref or "").strip() or None
    installation_customer_ref = str(installation.customer_ref or "").strip() if installation is not None else ""
    if token_customer_ref and installation_customer_ref and token_customer_ref != installation_customer_ref:
        raise HTTPException(status_code=403, detail="Token is not allowed for this installation")
    if installation is not None and token_customer_ref and not installation_customer_ref:
        installation.customer_ref = token_customer_ref

    customer_ref = token_customer_ref or installation_customer_ref or None
    workspace_id = str(payload.workspace_id or "").strip()[:64] or None

    metadata = dict(payload.metadata or {})
    request_ip = _resolve_request_ip(request)
    user_agent = str(request.headers.get("user-agent") or "").strip()[:512]
    if request_ip:
        metadata["request_ip"] = request_ip
    if user_agent:
        metadata["user_agent"] = user_agent

    dedup_key = _bug_report_dedup_key(
        installation_id=installation_id,
        title=title,
        description=description,
        severity=severity,
    )
    existing = db.execute(
        select(BugReport).where(
            BugReport.installation_id == installation_id,
            BugReport.dedup_key == dedup_key,
        ).order_by(BugReport.created_at.desc(), BugReport.id.desc()).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        merged_metadata = _load_metadata(existing.metadata_json)
        merged_metadata.update(metadata)
        existing.metadata_json = _dump_metadata(merged_metadata)
        db.commit()
        db.refresh(existing)
        _publish_admin_event(
            "bug_reports",
            "upserted",
            {"report_id": existing.report_id, "installation_id": existing.installation_id, "created": False},
        )
        return {
            "ok": True,
            "created": False,
            "bug_report": _serialize_bug_report(existing),
        }

    record = BugReport(
        report_id=f"bug_{uuid.uuid4()}",
        installation_id=installation_id,
        workspace_id=workspace_id,
        customer_ref=customer_ref,
        source=source,
        status="new",
        severity=severity,
        title=title,
        description=description,
        steps_to_reproduce=str(payload.steps_to_reproduce or "").strip() or None,
        expected_behavior=str(payload.expected_behavior or "").strip() or None,
        actual_behavior=str(payload.actual_behavior or "").strip() or None,
        reporter_user_id=str(payload.reporter_user_id or "").strip() or None,
        reporter_username=str(payload.reporter_username or "").strip() or None,
        triage_note=None,
        assignee=None,
        dedup_key=dedup_key,
        metadata_json=_dump_metadata(metadata),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    _publish_admin_event(
        "bug_reports",
        "created",
        {"report_id": record.report_id, "installation_id": record.installation_id, "created": True},
    )
    return {
        "ok": True,
        "created": True,
        "bug_report": _serialize_bug_report(record),
    }


@app.post("/v1/installations/register")
def register_installation(
    payload: InstallationRegisterRequest,
    auth_context: InstallationAuthContext = Depends(_require_installation_auth),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    token_customer_ref = str(auth_context.customer_ref or "").strip()
    active_ids_before: set[str] = set()
    if auth_context.auth_type == "client" and token_customer_ref:
        active_ids_before = {
            item.installation_id
            for item in _active_customer_installations(db, token_customer_ref)
        }

    installation = _upsert_installation(db, payload)
    _enforce_installation_customer_scope(installation, auth_context)
    _apply_client_token_operating_system(installation, auth_context)
    _apply_client_token_activation_ip(installation, auth_context)
    _ensure_installation_has_customer_ref(installation, payload.customer_ref)
    _apply_activation_code_plan_for_client_auth(
        db,
        installation=installation,
        auth_context=auth_context,
    )
    entitlement = _compute_entitlement(installation)
    lead_status_updates = _maybe_mark_lead_converted_for_installation(
        db,
        installation=installation,
        entitlement=entitlement,
        reason="installation_registered",
    )

    if auth_context.auth_type == "client" and token_customer_ref:
        current_customer_ref = str(installation.customer_ref or "").strip()
        is_currently_active = str(entitlement.get("status") or "").strip().lower() in {"active", "grace"}
        consumes_new_seat = is_currently_active and payload.installation_id not in active_ids_before
        skip_seat_limit = _activation_code_skips_seat_limits(
            db,
            activation_code_id=auth_context.activation_code_id,
            customer_ref=current_customer_ref,
        )
        if consumes_new_seat and not skip_seat_limit:
            max_installations = _resolve_customer_max_installations(
                db,
                customer_ref=current_customer_ref,
                activation_code_id=auth_context.activation_code_id,
            )
            if len(active_ids_before) >= max_installations:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Seat limit exceeded ({len(active_ids_before)}/{max_installations}) "
                        f"for customer {current_customer_ref}"
                    ),
                )

    entitlement, entitlement_token = _build_entitlement_bundle(entitlement)
    db.commit()
    serialized_installation = _serialize_installation(installation)
    notifications = _build_installation_notifications(db, installation)
    _publish_admin_event(
        "installations",
        "registered",
        {"installation_id": installation.installation_id},
    )
    return {
        "ok": True,
        "installation": {
            "installation_id": installation.installation_id,
            "workspace_id": installation.workspace_id,
            "customer_ref": installation.customer_ref,
            "subscription_status": installation.subscription_status,
            "created_at": serialized_installation.get("created_at"),
            "updated_at": serialized_installation.get("updated_at"),
            "trial_ends_at": installation.trial_ends_at.isoformat(),
            "customer_email": serialized_installation.get("customer_email"),
        },
        "entitlement": entitlement,
        "entitlement_token": entitlement_token,
        "notifications": notifications,
        "lead_status_updates": lead_status_updates,
    }


@app.post("/v1/install/exchange")
def install_exchange_token(
    payload: InstallExchangeRequest,
    request: Request,
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    normalized_code = _normalize_activation_code(payload.activation_code)
    if not normalized_code:
        raise HTTPException(status_code=400, detail="Activation code is required")

    code_hash = _activation_code_hash(normalized_code)
    activation_code = db.execute(
        select(ActivationCode).where(ActivationCode.code_hash == code_hash)
    ).scalar_one_or_none()
    if activation_code is None:
        raise HTTPException(status_code=404, detail="Invalid activation code")
    if not activation_code.is_active:
        raise HTTPException(status_code=400, detail="Activation code is inactive")

    now = _now_utc()
    code_valid_until = activation_code.valid_until
    if code_valid_until and code_valid_until.tzinfo is None:
        code_valid_until = code_valid_until.replace(tzinfo=timezone.utc)
    if code_valid_until:
        code_valid_until = code_valid_until.astimezone(timezone.utc)
    if code_valid_until and code_valid_until <= now:
        raise HTTPException(status_code=400, detail="Activation code has expired")

    code_metadata = _load_metadata(activation_code.metadata_json)
    prior_exchange_count_raw = code_metadata.get("install_exchange_count", 0)
    try:
        prior_exchange_count = int(prior_exchange_count_raw)
    except Exception:
        prior_exchange_count = 0
    if prior_exchange_count < 0:
        prior_exchange_count = 0

    code_metadata["install_exchange_count"] = prior_exchange_count + 1
    code_metadata["install_exchange_last_at"] = now.isoformat()
    activation_ip = _resolve_request_ip(request)
    if activation_ip:
        code_metadata["install_exchange_last_ip"] = activation_ip
    exchange_operating_system = _normalize_operating_system(payload.operating_system)
    if exchange_operating_system:
        code_metadata["install_exchange_last_operating_system"] = exchange_operating_system
    activation_code.metadata_json = _dump_metadata(code_metadata)

    token_metadata = {
        "source": "install-exchange",
        "activation_code_id": activation_code.id,
        "activation_code_suffix": activation_code.code_suffix,
    }
    if activation_ip:
        token_metadata["issued_ip"] = activation_ip
    if exchange_operating_system:
        token_metadata["issued_operating_system"] = exchange_operating_system
    client_token_raw, client_token_record = _create_client_token_record(
        db,
        customer_ref=activation_code.customer_ref,
        metadata=token_metadata,
    )

    db.commit()
    db.refresh(client_token_record)
    db.refresh(activation_code)

    image_tag = str(code_metadata.get("image_tag") or "").strip() or LCP_ONBOARDING_IMAGE_TAG
    install_script_url = (
        str(code_metadata.get("install_script_url") or "").strip() or LCP_ONBOARDING_INSTALL_SCRIPT_URL
    )

    _publish_admin_event(
        "onboarding",
        "install_token_exchanged",
        {
            "customer_ref": activation_code.customer_ref,
            "activation_code_id": activation_code.id,
            "client_token_id": client_token_record.id,
            "exchange_count": code_metadata["install_exchange_count"],
        },
    )
    return {
        "ok": True,
        "customer_ref": activation_code.customer_ref,
        "license_server_token": client_token_raw,
        "image_tag": image_tag,
        "install_script_url": install_script_url,
        "activation_code_record": _serialize_activation_code(activation_code),
    }


@app.post("/v1/installations/heartbeat")
def heartbeat_installation(
    payload: InstallationHeartbeatRequest,
    auth_context: InstallationAuthContext = Depends(_require_installation_auth),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    installation = _upsert_installation(db, payload)
    _enforce_installation_customer_scope(installation, auth_context)
    _apply_client_token_operating_system(installation, auth_context)
    _apply_client_token_activation_ip(installation, auth_context)
    _ensure_installation_has_customer_ref(installation, payload.customer_ref)
    _apply_activation_code_plan_for_client_auth(
        db,
        installation=installation,
        auth_context=auth_context,
    )
    entitlement = _compute_entitlement(installation)
    lead_status_updates = _maybe_mark_lead_converted_for_installation(
        db,
        installation=installation,
        entitlement=entitlement,
        reason="installation_heartbeat",
    )
    entitlement, entitlement_token = _build_entitlement_bundle(entitlement)
    db.commit()
    notifications = _build_installation_notifications(db, installation)
    _publish_admin_event(
        "installations",
        "heartbeat",
        {"installation_id": installation.installation_id},
    )
    return {
        "ok": True,
        "entitlement": entitlement,
        "entitlement_token": entitlement_token,
        "notifications": notifications,
        "lead_status_updates": lead_status_updates,
    }


@app.post("/v1/installations/activate")
def activate_installation(
    payload: InstallationActivateRequest,
    request: Request,
    auth_context: InstallationAuthContext = Depends(_require_installation_auth),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    normalized_code = _normalize_activation_code(payload.activation_code)
    if not normalized_code:
        raise HTTPException(status_code=400, detail="Activation code is required")

    code_hash = _activation_code_hash(normalized_code)
    activation_code = db.execute(
        select(ActivationCode).where(ActivationCode.code_hash == code_hash)
    ).scalar_one_or_none()
    if activation_code is None:
        raise HTTPException(status_code=404, detail="Invalid activation code")
    if not activation_code.is_active:
        raise HTTPException(status_code=400, detail="Activation code is inactive")
    if auth_context.customer_ref and auth_context.customer_ref != activation_code.customer_ref:
        raise HTTPException(status_code=403, detail="Token is not allowed to activate this customer")

    now = _now_utc()
    code_valid_until = activation_code.valid_until
    if code_valid_until and code_valid_until.tzinfo is None:
        code_valid_until = code_valid_until.replace(tzinfo=timezone.utc)
    if code_valid_until:
        code_valid_until = code_valid_until.astimezone(timezone.utc)
    if code_valid_until and code_valid_until <= now:
        raise HTTPException(status_code=400, detail="Activation code has expired")

    existing_installation = db.execute(
        select(Installation).where(Installation.installation_id == payload.installation_id)
    ).scalar_one_or_none()
    active_installations = _active_customer_installations(db, activation_code.customer_ref)
    active_ids = {item.installation_id for item in active_installations}
    already_counted = (
        existing_installation is not None
        and existing_installation.customer_ref == activation_code.customer_ref
        and existing_installation.installation_id in active_ids
    )

    if (
        (not _plan_code_skips_seat_limits(activation_code.plan_code))
        and (not already_counted)
        and len(active_ids) >= int(activation_code.max_installations)
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Seat limit exceeded ({len(active_ids)}/{int(activation_code.max_installations)}) for customer {activation_code.customer_ref}",
        )

    installation = _upsert_installation(
        db,
        InstallationRegisterRequest(
            installation_id=payload.installation_id,
            workspace_id=payload.workspace_id,
            customer_ref=payload.customer_ref,
            app_version=payload.app_version,
            operating_system=payload.operating_system,
            metadata=payload.metadata,
        ),
    )
    _enforce_installation_customer_scope(installation, auth_context)
    _apply_client_token_operating_system(installation, auth_context)
    installation.customer_ref = activation_code.customer_ref
    activation_plan_code = str(activation_code.plan_code or "").strip().lower()
    activation_plan_code = activation_plan_code or "monthly"
    activation_uses_lifetime = activation_plan_code == "lifetime"
    if activation_uses_lifetime:
        installation.plan_code = "lifetime"
        installation.subscription_status = "lifetime"
        installation.subscription_valid_until = None
    else:
        # Keep beta entitlements as default for non-lifetime activations.
        installation.plan_code = "beta"
        installation.subscription_status = "beta"
        installation.subscription_valid_until = LCP_BETA_PLAN_VALID_UNTIL

    merged_metadata = _load_metadata(installation.metadata_json)
    merged_metadata.update(payload.metadata or {})
    activation_code_email = _installation_customer_email(_load_metadata(activation_code.metadata_json))
    resolved_activation_email = activation_code_email
    if not resolved_activation_email:
        resolved_activation_email = _lookup_customer_email_by_customer_ref(db, {activation_code.customer_ref}).get(
            activation_code.customer_ref
        )
    if resolved_activation_email:
        merged_metadata.setdefault("issued_to_email", resolved_activation_email)
    merged_metadata.update(
        {
            "activation_code_suffix": activation_code.code_suffix,
            "activation_code_id": activation_code.id,
            "activation_plan_code": activation_plan_code,
            "activated_at": now.isoformat(),
        }
    )
    if activation_uses_lifetime:
        merged_metadata.pop("beta_auto_assigned", None)
        merged_metadata.pop("beta_auto_assigned_reason", None)
        merged_metadata.pop("beta_auto_assigned_at", None)
    else:
        merged_metadata.update(
            {
                "beta_auto_assigned": True,
                "beta_auto_assigned_reason": "activation",
                "beta_auto_assigned_at": now.isoformat(),
            }
        )
    activation_ip = _resolve_request_ip(request)
    if activation_ip:
        merged_metadata["activation_ip"] = activation_ip
    installation.metadata_json = _dump_metadata(merged_metadata)

    if not already_counted:
        activation_code.usage_count = int(activation_code.usage_count) + 1
    activation_code.last_used_at = now

    lead_status_updates: dict[str, int | str] | None = None
    if resolved_activation_email:
        lead_status_updates = _update_lead_status_by_email(
            db,
            email=resolved_activation_email,
            target_status=LEAD_STATUS_CONVERTED,
            reason="installation_activated",
        )

    entitlement = _compute_entitlement(installation)
    entitlement, entitlement_token = _build_entitlement_bundle(entitlement)
    db.commit()
    notifications = _build_installation_notifications(db, installation)
    _publish_admin_event(
        "installations",
        "activated",
        {
            "installation_id": installation.installation_id,
            "customer_ref": installation.customer_ref,
            "lead_status_updates": lead_status_updates,
        },
    )

    refreshed_active_count = len(_active_customer_installations(db, activation_code.customer_ref))

    return {
        "ok": True,
        "installation": _serialize_installation(installation),
        "entitlement": entitlement,
        "entitlement_token": entitlement_token,
        "notifications": notifications,
        "seat_usage": {
            "active_installations": refreshed_active_count,
            "max_installations": int(activation_code.max_installations),
            "customer_ref": activation_code.customer_ref,
        },
        "lead_status_updates": lead_status_updates,
    }


@app.post("/v1/admin/activation-codes")
def admin_create_activation_code(
    payload: AdminActivationCodeCreateRequest,
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    customer_ref = str(payload.customer_ref or "").strip()
    if not customer_ref:
        raise HTTPException(status_code=400, detail="customer_ref is required")

    plan_code = str(payload.plan_code or "").strip() or "monthly"
    if plan_code.lower() == "lifetime":
        valid_until = None
    else:
        if plan_code.lower() == "beta" and not str(payload.valid_until or "").strip():
            valid_until = None
        else:
            try:
                valid_until = _parse_iso_datetime(payload.valid_until)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid valid_until value: {exc}") from exc
        if plan_code.lower() == "trial" and valid_until is None:
            raise HTTPException(status_code=400, detail="valid_until is required for trial plan_code")
        if valid_until and valid_until <= _now_utc():
            raise HTTPException(status_code=400, detail="valid_until must be in the future")

    activation_code_raw, record = _create_activation_code_record(
        db,
        customer_ref=customer_ref,
        plan_code=plan_code,
        valid_until=valid_until,
        max_installations=int(payload.max_installations or LCP_DEFAULT_MAX_INSTALLATIONS),
        metadata=payload.metadata or {},
    )
    db.commit()
    db.refresh(record)
    _publish_admin_event(
        "activation_codes",
        "created",
        {"code_id": record.id, "customer_ref": record.customer_ref},
    )
    return {
        "ok": True,
        "activation_code": activation_code_raw,
        "activation_code_record": _serialize_activation_code(record),
    }


@app.get("/v1/admin/activation-codes")
def admin_list_activation_codes(
    q: str | None = Query(default=None),
    customer_ref: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    filters = []
    query_text = str(q or "").strip().lower()
    if query_text:
        like = f"%{query_text}%"
        filters.append(
            or_(
                func.lower(ActivationCode.customer_ref).like(like),
                func.lower(func.coalesce(ActivationCode.plan_code, "")).like(like),
                func.lower(func.coalesce(ActivationCode.code_suffix, "")).like(like),
            )
        )

    customer_filter = str(customer_ref or "").strip()
    if customer_filter:
        filters.append(ActivationCode.customer_ref == customer_filter)
    if active is not None:
        filters.append(ActivationCode.is_active == bool(active))

    total_stmt = select(func.count()).select_from(ActivationCode)
    rows_stmt = select(ActivationCode)
    if filters:
        for clause in filters:
            total_stmt = total_stmt.where(clause)
            rows_stmt = rows_stmt.where(clause)

    total = int(db.execute(total_stmt).scalar_one())
    rows = db.execute(
        rows_stmt.order_by(ActivationCode.updated_at.desc(), ActivationCode.id.desc()).offset(offset).limit(limit)
    ).scalars().all()

    return {
        "ok": True,
        "items": [_serialize_activation_code(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/v1/admin/activation-codes/{code_id}/deactivate")
def admin_deactivate_activation_code(
    code_id: int,
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    record = db.get(ActivationCode, code_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Activation code not found")
    record.is_active = False
    db.commit()
    db.refresh(record)
    _publish_admin_event(
        "activation_codes",
        "deactivated",
        {"code_id": record.id, "customer_ref": record.customer_ref},
    )
    return {"ok": True, "activation_code_record": _serialize_activation_code(record)}


@app.post("/v1/admin/client-tokens")
def admin_create_client_token(
    payload: AdminClientTokenCreateRequest,
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    customer_ref = str(payload.customer_ref or "").strip()
    if not customer_ref:
        raise HTTPException(status_code=400, detail="customer_ref is required")

    raw_token, record = _create_client_token_record(
        db,
        customer_ref=customer_ref,
        metadata=payload.metadata or {},
    )
    db.commit()
    db.refresh(record)
    _publish_admin_event(
        "client_tokens",
        "created",
        {"token_id": record.id, "customer_ref": record.customer_ref},
    )
    return {
        "ok": True,
        "client_token": raw_token,
        "client_token_record": _serialize_client_token(record),
    }


@app.post("/v1/admin/email/send")
def admin_send_email(
    payload: AdminEmailSendRequest,
    _auth: None = Depends(_require_admin_token),
) -> dict[str, Any]:
    to_email = _normalize_email(payload.to_email)
    subject = _normalize_email_subject(payload.subject)
    text_body = _normalize_email_body(payload.text_body)
    try:
        message_id = _send_email_via_resend(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
        )
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to send email: {exc}") from exc

    _publish_admin_event(
        "email",
        "sent",
        {
            "to_email": to_email,
            "provider": "resend",
            "message_id": message_id,
        },
    )
    return {
        "ok": True,
        "provider": "resend",
        "to_email": to_email,
        "message_id": message_id,
    }


@app.post("/v1/admin/email/send-onboarding")
def admin_send_onboarding_email(
    payload: AdminOnboardingEmailSendRequest,
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    to_email = _normalize_email(payload.to_email)
    customer_ref = _normalize_customer_ref(payload.customer_ref)
    if str(payload.client_token or "").strip():
        _normalize_client_token(payload.client_token)
    activation_code = _normalize_activation_code_value(payload.activation_code)
    image_tag = _normalize_image_tag(payload.image_tag)
    install_script_url = _normalize_install_script_url(payload.install_script_url)
    support_email = _normalize_support_email(payload.support_email)

    subject, text_body, html_body = _build_onboarding_email_template(
        customer_ref=customer_ref,
        activation_code=activation_code,
        image_tag=image_tag,
        install_script_url=install_script_url,
        support_email=support_email,
    )
    try:
        message_id = _send_email_via_resend(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to send onboarding email: {exc}") from exc

    lead_status_updates = _update_lead_status_by_email(
        db,
        email=to_email,
        target_status=LEAD_STATUS_ONBOARDING_SENT,
        reason="onboarding_email_sent",
    )
    db.commit()

    _publish_admin_event(
        "email",
        "onboarding_sent",
        {
            "to_email": to_email,
            "customer_ref": customer_ref,
            "provider": "resend",
            "message_id": message_id,
            "lead_status_updates": lead_status_updates,
        },
    )
    return {
        "ok": True,
        "provider": "resend",
        "to_email": to_email,
        "customer_ref": customer_ref,
        "subject": subject,
        "message_id": message_id,
        "lead_status_updates": lead_status_updates,
    }


@app.post("/v1/admin/onboarding/provision")
def admin_provision_onboarding(
    payload: AdminProvisionOnboardingRequest,
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    to_email = _normalize_email(payload.to_email)
    customer_ref = _customer_ref_from_email(to_email)

    plan_code = str(payload.plan_code or "").strip() or "monthly"
    if plan_code.lower() == "lifetime":
        valid_until = None
    else:
        if plan_code.lower() == "beta" and not str(payload.valid_until or "").strip():
            valid_until = None
        else:
            try:
                valid_until = _parse_iso_datetime(payload.valid_until)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid valid_until value: {exc}") from exc
        if plan_code.lower() == "trial" and valid_until is None:
            raise HTTPException(status_code=400, detail="valid_until is required for trial plan_code")
        if valid_until and valid_until <= _now_utc():
            raise HTTPException(status_code=400, detail="valid_until must be in the future")
    max_installations = int(payload.max_installations or LCP_DEFAULT_MAX_INSTALLATIONS)
    image_tag = _normalize_image_tag(payload.image_tag)
    install_script_url = _normalize_install_script_url(payload.install_script_url)
    support_email = _normalize_support_email(payload.support_email)

    metadata = dict(payload.metadata or {})
    metadata.setdefault("issued_to_email", to_email)
    metadata.setdefault("source", "admin-onboarding-provision")
    metadata.setdefault("image_tag", image_tag)
    metadata.setdefault("install_script_url", install_script_url)

    try:
        client_token_raw, client_token_record = _create_client_token_record(
            db,
            customer_ref=customer_ref,
            metadata=metadata,
        )
        activation_code_raw, activation_code_record = _create_activation_code_record(
            db,
            customer_ref=customer_ref,
            plan_code=plan_code,
            valid_until=valid_until,
            max_installations=max_installations,
            metadata=metadata,
        )

        subject, text_body, html_body = _build_onboarding_email_template(
            customer_ref=customer_ref,
            activation_code=activation_code_raw,
            image_tag=image_tag,
            install_script_url=install_script_url,
            support_email=support_email,
            max_installations=max_installations,
        )
        message_id = _send_email_via_resend(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )

        lead_status_updates = _update_lead_status_by_email(
            db,
            email=to_email,
            target_status=LEAD_STATUS_ONBOARDING_SENT,
            reason="onboarding_package_provisioned",
        )

        db.commit()
        db.refresh(client_token_record)
        db.refresh(activation_code_record)
    except HTTPException:
        db.rollback()
        raise
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Failed to provision onboarding package: {exc}") from exc

    _publish_admin_event(
        "onboarding",
        "provisioned",
        {
            "to_email": to_email,
            "customer_ref": customer_ref,
            "client_token_id": client_token_record.id,
            "activation_code_id": activation_code_record.id,
            "message_id": message_id,
            "lead_status_updates": lead_status_updates,
        },
    )
    return {
        "ok": True,
        "provider": "resend",
        "to_email": to_email,
        "customer_ref": customer_ref,
        "subject": subject,
        "message_id": message_id,
        "client_token": client_token_raw,
        "client_token_record": _serialize_client_token(client_token_record),
        "activation_code": activation_code_raw,
        "activation_code_record": _serialize_activation_code(activation_code_record),
        "lead_status_updates": lead_status_updates,
    }


@app.get("/v1/admin/client-tokens")
def admin_list_client_tokens(
    q: str | None = Query(default=None),
    customer_ref: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    filters = []
    query_text = str(q or "").strip().lower()
    if query_text:
        like = f"%{query_text}%"
        filters.append(
            or_(
                func.lower(ClientToken.customer_ref).like(like),
                func.lower(func.coalesce(ClientToken.token_suffix, "")).like(like),
            )
        )

    customer_filter = str(customer_ref or "").strip()
    if customer_filter:
        filters.append(ClientToken.customer_ref == customer_filter)
    if active is not None:
        filters.append(ClientToken.is_active == bool(active))

    total_stmt = select(func.count()).select_from(ClientToken)
    rows_stmt = select(ClientToken)
    if filters:
        for clause in filters:
            total_stmt = total_stmt.where(clause)
            rows_stmt = rows_stmt.where(clause)

    total = int(db.execute(total_stmt).scalar_one())
    rows = db.execute(
        rows_stmt.order_by(ClientToken.updated_at.desc(), ClientToken.id.desc()).offset(offset).limit(limit)
    ).scalars().all()

    return {
        "ok": True,
        "items": [_serialize_client_token(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/v1/admin/client-tokens/{token_id}/deactivate")
def admin_deactivate_client_token(
    token_id: int,
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    record = db.get(ClientToken, token_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Client token not found")
    record.is_active = False
    db.commit()
    db.refresh(record)
    _publish_admin_event(
        "client_tokens",
        "deactivated",
        {"token_id": record.id, "customer_ref": record.customer_ref},
    )
    return {"ok": True, "client_token_record": _serialize_client_token(record)}


@app.get("/v1/admin/app-notifications")
def admin_list_app_notifications(
    audience_kind: str | None = Query(default=None),
    active_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    filters = []
    audience_filter = str(audience_kind or "").strip().lower()
    if audience_filter:
        filters.append(AppNotificationCampaign.audience_kind == _normalize_notification_audience_kind(audience_filter))
    if active_only:
        now = _now_utc()
        filters.append(AppNotificationCampaign.is_active == True)  # noqa: E712
        filters.append(
            or_(
                AppNotificationCampaign.active_from.is_(None),
                AppNotificationCampaign.active_from <= now,
            )
        )
        filters.append(
            or_(
                AppNotificationCampaign.active_until.is_(None),
                AppNotificationCampaign.active_until > now,
            )
        )

    total_stmt = select(func.count()).select_from(AppNotificationCampaign)
    rows_stmt = select(AppNotificationCampaign)
    for clause in filters:
        total_stmt = total_stmt.where(clause)
        rows_stmt = rows_stmt.where(clause)

    total = int(db.execute(total_stmt).scalar_one())
    rows = db.execute(
        rows_stmt.order_by(AppNotificationCampaign.created_at.desc(), AppNotificationCampaign.id.desc()).offset(offset).limit(limit)
    ).scalars().all()
    return {
        "ok": True,
        "items": [_serialize_app_notification_campaign(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/v1/admin/app-notifications")
def admin_create_app_notification(
    payload: AdminAppNotificationCreateRequest,
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    message = _normalize_notification_message(payload.message)
    title = _normalize_notification_title(payload.title)
    severity = _normalize_notification_severity(payload.severity)
    notification_type = _normalize_notification_type(payload.notification_type)
    audience_kind = _normalize_notification_audience_kind(payload.audience_kind)
    audience_values = _normalize_notification_audience_values(audience_kind, payload.audience_values)
    try:
        active_from = _parse_iso_datetime(payload.active_from)
        active_until = _parse_iso_datetime(payload.active_until)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid notification schedule value: {exc}") from exc
    if active_from and active_until and active_until <= active_from:
        raise HTTPException(status_code=400, detail="active_until must be later than active_from")
    if not isinstance(payload.payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    record = AppNotificationCampaign(
        notification_id=f"cpn-{uuid.uuid4().hex}",
        title=title,
        message=message,
        severity=severity,
        notification_type=notification_type,
        audience_kind=audience_kind,
        audience_values_json=json.dumps(audience_values, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        payload_json=_dump_metadata(payload.payload),
        is_active=bool(payload.is_active),
        active_from=active_from,
        active_until=active_until,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    _publish_admin_event(
        "app_notifications",
        "created",
        {"notification_id": record.notification_id, "audience_kind": record.audience_kind},
    )
    return {"ok": True, "notification": _serialize_app_notification_campaign(record)}


@app.post("/v1/admin/app-notifications/{notification_id}/deactivate")
def admin_deactivate_app_notification(
    notification_id: str,
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    normalized_notification_id = str(notification_id or "").strip()
    if not normalized_notification_id:
        raise HTTPException(status_code=400, detail="notification_id is required")

    record = db.execute(
        select(AppNotificationCampaign).where(AppNotificationCampaign.notification_id == normalized_notification_id)
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="App notification not found")

    record.is_active = False
    db.commit()
    db.refresh(record)
    _publish_admin_event(
        "app_notifications",
        "deactivated",
        {"notification_id": record.notification_id},
    )
    return {"ok": True, "notification": _serialize_app_notification_campaign(record)}


@app.get("/v1/admin/waitlist")
def admin_list_waitlist(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    filters = []
    query_text = str(q or "").strip().lower()
    if query_text:
        like = f"%{query_text}%"
        filters.append(
            or_(
                func.lower(WaitlistEntry.email).like(like),
                func.lower(func.coalesce(WaitlistEntry.source, "")).like(like),
            )
        )

    status_value = str(status or "").strip().lower()
    if status_value:
        filters.append(func.lower(WaitlistEntry.status) == status_value)

    source_value = str(source or "").strip().lower()
    if source_value:
        filters.append(func.lower(WaitlistEntry.source) == source_value)

    total_stmt = select(func.count()).select_from(WaitlistEntry)
    rows_stmt = select(WaitlistEntry)
    if filters:
        for clause in filters:
            total_stmt = total_stmt.where(clause)
            rows_stmt = rows_stmt.where(clause)

    total = int(db.execute(total_stmt).scalar_one())
    rows = db.execute(
        rows_stmt.order_by(WaitlistEntry.created_at.desc(), WaitlistEntry.id.desc()).offset(offset).limit(limit)
    ).scalars().all()

    return {
        "ok": True,
        "items": [_serialize_waitlist_entry(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/v1/admin/contact-requests")
def admin_list_contact_requests(
    q: str | None = Query(default=None),
    request_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    filters = []
    query_text = str(q or "").strip().lower()
    if query_text:
        like = f"%{query_text}%"
        filters.append(
            or_(
                func.lower(ContactRequest.email).like(like),
                func.lower(func.coalesce(ContactRequest.request_type, "")).like(like),
                func.lower(func.coalesce(ContactRequest.source, "")).like(like),
            )
        )

    request_type_value = str(request_type or "").strip().lower()
    if request_type_value:
        filters.append(func.lower(ContactRequest.request_type) == request_type_value)

    status_value = str(status or "").strip().lower()
    if status_value:
        filters.append(func.lower(ContactRequest.status) == status_value)

    source_value = str(source or "").strip().lower()
    if source_value:
        filters.append(func.lower(ContactRequest.source) == source_value)

    total_stmt = select(func.count()).select_from(ContactRequest)
    rows_stmt = select(ContactRequest)
    if filters:
        for clause in filters:
            total_stmt = total_stmt.where(clause)
            rows_stmt = rows_stmt.where(clause)

    total = int(db.execute(total_stmt).scalar_one())
    rows = db.execute(
        rows_stmt.order_by(ContactRequest.created_at.desc(), ContactRequest.id.desc()).offset(offset).limit(limit)
    ).scalars().all()

    return {
        "ok": True,
        "items": [_serialize_contact_request(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/v1/admin/bug-reports")
def admin_list_bug_reports(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    source: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    customer_ref: str | None = Query(default=None),
    installation_id: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    filters = []
    query_text = str(q or "").strip().lower()
    if query_text:
        like = f"%{query_text}%"
        filters.append(
            or_(
                func.lower(BugReport.report_id).like(like),
                func.lower(BugReport.installation_id).like(like),
                func.lower(func.coalesce(BugReport.workspace_id, "")).like(like),
                func.lower(func.coalesce(BugReport.customer_ref, "")).like(like),
                func.lower(func.coalesce(BugReport.reporter_username, "")).like(like),
                func.lower(func.coalesce(BugReport.title, "")).like(like),
                func.lower(func.coalesce(BugReport.description, "")).like(like),
            )
        )

    status_value = str(status or "").strip().lower()
    if status_value:
        filters.append(func.lower(BugReport.status) == status_value)

    severity_value = str(severity or "").strip().lower()
    if severity_value:
        filters.append(func.lower(BugReport.severity) == severity_value)

    source_value = str(source or "").strip().lower()
    if source_value:
        filters.append(func.lower(BugReport.source) == source_value)

    workspace_value = str(workspace_id or "").strip()
    if workspace_value:
        filters.append(BugReport.workspace_id == workspace_value)

    customer_value = str(customer_ref or "").strip()
    if customer_value:
        filters.append(BugReport.customer_ref == customer_value)

    installation_value = str(installation_id or "").strip()
    if installation_value:
        filters.append(BugReport.installation_id == installation_value)

    total_stmt = select(func.count()).select_from(BugReport)
    rows_stmt = select(BugReport)
    if filters:
        for clause in filters:
            total_stmt = total_stmt.where(clause)
            rows_stmt = rows_stmt.where(clause)

    total = int(db.execute(total_stmt).scalar_one())
    rows = db.execute(
        rows_stmt.order_by(BugReport.created_at.desc(), BugReport.id.desc()).offset(offset).limit(limit)
    ).scalars().all()

    return {
        "ok": True,
        "items": [_serialize_bug_report(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.patch("/v1/admin/bug-reports/{report_id}")
def admin_update_bug_report(
    report_id: str,
    payload: AdminBugReportUpdateRequest,
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    normalized_report_id = str(report_id or "").strip()
    if not normalized_report_id:
        raise HTTPException(status_code=400, detail="report_id is required")

    record = db.execute(
        select(BugReport).where(BugReport.report_id == normalized_report_id)
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Bug report not found")

    if payload.status is not None:
        record.status = _normalize_bug_report_status(payload.status)
    if payload.triage_note is not None:
        record.triage_note = str(payload.triage_note or "").strip() or None
    if payload.assignee is not None:
        record.assignee = str(payload.assignee or "").strip() or None

    db.commit()
    db.refresh(record)
    _publish_admin_event(
        "bug_reports",
        "updated",
        {"report_id": record.report_id, "status": record.status},
    )
    return {
        "ok": True,
        "bug_report": _serialize_bug_report(record),
    }


@app.get("/v1/admin/installations")
def admin_list_installations(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    filters = []
    query_text = str(q or "").strip()
    if query_text:
        like = f"%{query_text.lower()}%"
        filters.append(
            or_(
                func.lower(Installation.installation_id).like(like),
                func.lower(func.coalesce(Installation.customer_ref, "")).like(like),
                func.lower(func.coalesce(Installation.workspace_id, "")).like(like),
            )
        )

    status_text = str(status or "").strip().lower()
    if status_text:
        normalized_status = _normalize_subscription_status(status_text)
        matching_statuses = SUBSCRIPTION_STATUS_FILTER_EQUIVALENTS.get(normalized_status, {normalized_status})
        lowered_statuses = [value.lower() for value in matching_statuses]
        filters.append(func.lower(Installation.subscription_status).in_(lowered_statuses))

    total_stmt = select(func.count()).select_from(Installation)
    rows_stmt = select(Installation)
    if filters:
        for clause in filters:
            total_stmt = total_stmt.where(clause)
            rows_stmt = rows_stmt.where(clause)

    total = int(db.execute(total_stmt).scalar_one())
    installations = db.execute(
        rows_stmt.order_by(Installation.updated_at.desc(), Installation.id.desc()).offset(offset).limit(limit)
    ).scalars().all()

    customer_refs_for_email_lookup: set[str] = set()
    for installation in installations:
        metadata = _load_metadata(installation.metadata_json)
        if _installation_customer_email(metadata):
            continue
        customer_ref = str(installation.customer_ref or "").strip()
        if not customer_ref or customer_ref == LCP_UNASSIGNED_CUSTOMER_REF:
            continue
        customer_refs_for_email_lookup.add(customer_ref)
    email_by_customer_ref = (
        _lookup_customer_email_by_customer_ref(db, customer_refs_for_email_lookup)
        if customer_refs_for_email_lookup
        else {}
    )

    items: list[dict[str, Any]] = []
    for installation in installations:
        entitlement = _compute_entitlement(installation)
        customer_ref = str(installation.customer_ref or "").strip()
        customer_email_override = email_by_customer_ref.get(customer_ref) if customer_ref else None
        items.append(
            {
                "installation": _serialize_installation(
                    installation,
                    customer_email_override=customer_email_override,
                ),
                "entitlement": entitlement,
            }
        )

    return {
        "ok": True,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.put("/v1/admin/installations/{installation_id}/subscription")
def admin_update_subscription(
    installation_id: str,
    payload: AdminSubscriptionUpdateRequest,
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    installation = db.execute(
        select(Installation).where(Installation.installation_id == installation_id)
    ).scalar_one_or_none()
    if installation is None:
        raise HTTPException(status_code=404, detail="Installation not found")

    status_value = _normalize_subscription_status(payload.subscription_status)
    valid_until = _resolve_subscription_valid_until(
        status_value=status_value,
        requested_valid_until=payload.valid_until,
        existing_valid_until=installation.subscription_valid_until,
    )
    _apply_subscription_update_to_installation(
        installation,
        status_value=status_value,
        plan_code=payload.plan_code,
        customer_ref=payload.customer_ref,
        valid_until=valid_until,
        metadata=payload.metadata,
    )

    entitlement = _compute_entitlement(installation)
    entitlement, entitlement_token = _build_entitlement_bundle(entitlement)
    db.commit()
    _publish_admin_event(
        "installations",
        "subscription_updated",
        {"installation_id": installation.installation_id, "subscription_status": installation.subscription_status},
    )

    return {
        "ok": True,
        "installation_id": installation_id,
        "subscription_status": installation.subscription_status,
        "entitlement": entitlement,
        "entitlement_token": entitlement_token,
    }


@app.put("/v1/admin/customers/{customer_ref}/subscription")
def admin_update_customer_subscription(
    customer_ref: str,
    payload: AdminSubscriptionUpdateRequest,
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    source_customer_ref = str(customer_ref or "").strip()
    if not source_customer_ref:
        raise HTTPException(status_code=400, detail="customer_ref is required")
    target_customer_ref = str(payload.customer_ref or "").strip() or source_customer_ref

    installations = db.execute(
        select(Installation).where(Installation.customer_ref == source_customer_ref)
    ).scalars().all()
    if not installations:
        raise HTTPException(status_code=404, detail="No installations found for customer_ref")

    status_value = _normalize_subscription_status(payload.subscription_status)
    updated_ids: list[str] = []
    for installation in installations:
        valid_until = _resolve_subscription_valid_until(
            status_value=status_value,
            requested_valid_until=payload.valid_until,
            existing_valid_until=installation.subscription_valid_until,
        )
        _apply_subscription_update_to_installation(
            installation,
            status_value=status_value,
            plan_code=payload.plan_code,
            customer_ref=target_customer_ref,
            valid_until=valid_until,
            metadata=payload.metadata,
        )
        updated_ids.append(installation.installation_id)

    db.commit()
    _publish_admin_event(
        "customers",
        "subscription_updated",
        {
            "customer_ref": target_customer_ref,
            "source_customer_ref": source_customer_ref,
            "subscription_status": status_value,
            "updated_installations": len(updated_ids),
        },
    )

    return {
        "ok": True,
        "customer_ref": target_customer_ref,
        "source_customer_ref": source_customer_ref,
        "subscription_status": status_value,
        "updated_installations": len(updated_ids),
        "installation_ids": updated_ids,
    }


@app.get("/v1/admin/installations/{installation_id}")
def admin_get_installation(
    installation_id: str,
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    installation = db.execute(
        select(Installation).where(Installation.installation_id == installation_id)
    ).scalar_one_or_none()
    if installation is None:
        raise HTTPException(status_code=404, detail="Installation not found")

    entitlement = _compute_entitlement(installation)
    entitlement, entitlement_token = _build_entitlement_bundle(entitlement)
    customer_email_override: str | None = None
    metadata = _load_metadata(installation.metadata_json)
    if not _installation_customer_email(metadata):
        customer_ref = str(installation.customer_ref or "").strip()
        if customer_ref and customer_ref != LCP_UNASSIGNED_CUSTOMER_REF:
            customer_email_override = _lookup_customer_email_by_customer_ref(db, {customer_ref}).get(customer_ref)
    return {
        "ok": True,
        "installation": _serialize_installation(
            installation,
            customer_email_override=customer_email_override,
        ),
        "entitlement": entitlement,
        "entitlement_token": entitlement_token,
    }


@app.delete("/v1/admin/installations/{installation_id}")
def admin_delete_installation(
    installation_id: str,
    _auth: None = Depends(_require_admin_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    installation = db.execute(
        select(Installation).where(Installation.installation_id == installation_id)
    ).scalar_one_or_none()
    if installation is None:
        raise HTTPException(status_code=404, detail="Installation not found")

    deleted_customer_ref = installation.customer_ref
    deleted_workspace_id = installation.workspace_id
    db.delete(installation)
    db.commit()
    _publish_admin_event(
        "installations",
        "deleted",
        {
            "installation_id": installation_id,
            "customer_ref": deleted_customer_ref,
            "workspace_id": deleted_workspace_id,
        },
    )

    return {
        "ok": True,
        "installation_id": installation_id,
    }


@app.get("/", include_in_schema=False)
def ui_root():
    if INDEX_HTML.exists():
        return FileResponse(
            str(INDEX_HTML),
            headers={
                "Cache-Control": "no-store, max-age=0, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return Response(status_code=404)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    favicon_path = STATIC_DIR / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(str(favicon_path), media_type="image/x-icon")
    return Response(status_code=204)


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
