from __future__ import annotations

import json
import os
import secrets
import string
import hashlib
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine, func, or_, select
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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


LCP_DATABASE_URL = os.getenv("LCP_DATABASE_URL", "sqlite:////data/license-control-plane.db").strip() or "sqlite:////data/license-control-plane.db"
LCP_API_TOKEN = os.getenv("LCP_API_TOKEN", "").strip()
LCP_TRIAL_DAYS = max(1, _env_int("LCP_TRIAL_DAYS", 7))
LCP_TOKEN_TTL_SECONDS = max(60, _env_int("LCP_TOKEN_TTL_SECONDS", 3600))
LCP_SIGNING_PRIVATE_KEY_PEM = os.getenv("LCP_SIGNING_PRIVATE_KEY_PEM", "").strip()
LCP_SIGNING_KEY_ID = os.getenv("LCP_SIGNING_KEY_ID", "default-ed25519").strip() or "default-ed25519"
LCP_REQUIRE_SIGNED_TOKENS = _env_bool("LCP_REQUIRE_SIGNED_TOKENS", False)
LCP_DEFAULT_MAX_INSTALLATIONS = max(1, _env_int("LCP_DEFAULT_MAX_INSTALLATIONS", 3))
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_HTML = STATIC_DIR / "index.html"

Base = declarative_base()


class Installation(Base):
    __tablename__ = "installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    customer_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
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


engine = create_engine(
    LCP_DATABASE_URL,
    connect_args={"check_same_thread": False} if LCP_DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class InstallationRegisterRequest(BaseModel):
    installation_id: str = Field(min_length=3, max_length=128)
    workspace_id: str | None = None
    app_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InstallationHeartbeatRequest(BaseModel):
    installation_id: str = Field(min_length=3, max_length=128)
    workspace_id: str | None = None
    app_version: str | None = None
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
    app_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdminClientTokenCreateRequest(BaseModel):
    customer_ref: str = Field(min_length=2, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class InstallationAuthContext:
    auth_type: str
    customer_ref: str | None = None


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


def _require_admin_token(authorization: str | None = Header(default=None)) -> None:
    if not LCP_API_TOKEN:
        return
    provided = _extract_bearer_secret(authorization)
    if not provided or provided != LCP_API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid control-plane admin token")


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
            return InstallationAuthContext(auth_type="client", customer_ref=client_token.customer_ref)

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
    return f"lcp_{secrets.token_urlsafe(30)}"


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

    subscription_status = str(installation.subscription_status or "none").strip().lower()

    status = "expired"
    plan_code = installation.plan_code or None
    if subscription_status in {"active", "trialing"} and (valid_until is None or valid_until > now):
        status = "active"
    elif subscription_status in {"grace", "past_due"} and valid_until and valid_until > now:
        status = "grace"
    elif trial_ends_at > now:
        status = "trial"
        if not plan_code:
            plan_code = "trial"

    token_expires_at = now + timedelta(seconds=LCP_TOKEN_TTL_SECONDS)

    return {
        "installation_id": installation.installation_id,
        "status": status,
        "plan_code": plan_code,
        "valid_from": now.isoformat(),
        "valid_until": valid_until.isoformat() if valid_until else (trial_ends_at.isoformat() if status == "trial" else None),
        "trial_ends_at": trial_ends_at.isoformat(),
        "token_expires_at": token_expires_at.isoformat(),
        "metadata": _load_metadata(installation.metadata_json),
    }


def _upsert_installation(db: Session, payload: InstallationRegisterRequest | InstallationHeartbeatRequest) -> Installation:
    installation = db.execute(
        select(Installation).where(Installation.installation_id == payload.installation_id)
    ).scalar_one_or_none()

    now = _now_utc()
    if installation is None:
        trial_ends_at = now + timedelta(days=LCP_TRIAL_DAYS)
        installation = Installation(
            installation_id=payload.installation_id,
            workspace_id=payload.workspace_id,
            trial_started_at=now,
            trial_ends_at=trial_ends_at,
            metadata_json=_dump_metadata(payload.metadata or {}),
        )
        db.add(installation)
        db.flush()
        return installation

    changed = False
    if payload.workspace_id and installation.workspace_id != payload.workspace_id:
        installation.workspace_id = payload.workspace_id
        changed = True

    merged_metadata = _load_metadata(installation.metadata_json)
    if payload.metadata:
        merged_metadata.update(payload.metadata)
        installation.metadata_json = _dump_metadata(merged_metadata)
        changed = True

    if changed:
        db.flush()
    return installation


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


def _serialize_installation(installation: Installation) -> dict[str, Any]:
    return {
        "installation_id": installation.installation_id,
        "workspace_id": installation.workspace_id,
        "customer_ref": installation.customer_ref,
        "plan_code": installation.plan_code,
        "subscription_status": installation.subscription_status,
        "subscription_valid_until": installation.subscription_valid_until.isoformat() if installation.subscription_valid_until else None,
        "trial_started_at": installation.trial_started_at.isoformat(),
        "trial_ends_at": installation.trial_ends_at.isoformat(),
        "metadata": _load_metadata(installation.metadata_json),
        "updated_at": installation.updated_at.isoformat(),
    }


app = FastAPI(title="m4tr1x Licensing Control Plane")


@app.on_event("startup")
def _startup() -> None:
    Base.metadata.create_all(bind=engine)
    if LCP_REQUIRE_SIGNED_TOKENS and not LCP_SIGNING_PRIVATE_KEY_PEM:
        raise RuntimeError("LCP_REQUIRE_SIGNED_TOKENS is enabled but LCP_SIGNING_PRIVATE_KEY_PEM is not configured")
    if LCP_SIGNING_PRIVATE_KEY_PEM:
        # Fail fast on invalid keys during startup.
        try:
            _sign_entitlement_if_configured({"installation_id": "startup-check", "status": "trial"})
        except SigningError as exc:
            raise RuntimeError(f"Failed to initialize signing key: {exc}") from exc


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "timestamp": _now_utc().isoformat(),
        "trial_days": LCP_TRIAL_DAYS,
        "default_max_installations": LCP_DEFAULT_MAX_INSTALLATIONS,
    }


@app.post("/v1/installations/register")
def register_installation(
    payload: InstallationRegisterRequest,
    auth_context: InstallationAuthContext = Depends(_require_installation_auth),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    installation = _upsert_installation(db, payload)
    _enforce_installation_customer_scope(installation, auth_context)
    entitlement = _compute_entitlement(installation)
    entitlement, entitlement_token = _build_entitlement_bundle(entitlement)
    db.commit()
    return {
        "ok": True,
        "installation": {
            "installation_id": installation.installation_id,
            "workspace_id": installation.workspace_id,
            "customer_ref": installation.customer_ref,
            "subscription_status": installation.subscription_status,
            "trial_ends_at": installation.trial_ends_at.isoformat(),
        },
        "entitlement": entitlement,
        "entitlement_token": entitlement_token,
    }


@app.post("/v1/installations/heartbeat")
def heartbeat_installation(
    payload: InstallationHeartbeatRequest,
    auth_context: InstallationAuthContext = Depends(_require_installation_auth),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    installation = _upsert_installation(db, payload)
    _enforce_installation_customer_scope(installation, auth_context)
    entitlement = _compute_entitlement(installation)
    entitlement, entitlement_token = _build_entitlement_bundle(entitlement)
    db.commit()
    return {"ok": True, "entitlement": entitlement, "entitlement_token": entitlement_token}


@app.post("/v1/installations/activate")
def activate_installation(
    payload: InstallationActivateRequest,
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

    if (not already_counted) and len(active_ids) >= int(activation_code.max_installations):
        raise HTTPException(
            status_code=409,
            detail=f"Seat limit exceeded ({len(active_ids)}/{int(activation_code.max_installations)}) for customer {activation_code.customer_ref}",
        )

    installation = _upsert_installation(
        db,
        InstallationRegisterRequest(
            installation_id=payload.installation_id,
            workspace_id=payload.workspace_id,
            app_version=payload.app_version,
            metadata=payload.metadata,
        ),
    )
    _enforce_installation_customer_scope(installation, auth_context)
    installation.customer_ref = activation_code.customer_ref
    installation.plan_code = str(activation_code.plan_code or installation.plan_code or "monthly").strip() or "monthly"
    installation.subscription_status = "active"
    installation.subscription_valid_until = code_valid_until

    merged_metadata = _load_metadata(installation.metadata_json)
    merged_metadata.update(payload.metadata or {})
    merged_metadata.update(
        {
            "activation_code_suffix": activation_code.code_suffix,
            "activation_code_id": activation_code.id,
            "activated_at": now.isoformat(),
        }
    )
    installation.metadata_json = _dump_metadata(merged_metadata)

    if not already_counted:
        activation_code.usage_count = int(activation_code.usage_count) + 1
    activation_code.last_used_at = now

    entitlement = _compute_entitlement(installation)
    entitlement, entitlement_token = _build_entitlement_bundle(entitlement)
    db.commit()

    refreshed_active_count = len(_active_customer_installations(db, activation_code.customer_ref))

    return {
        "ok": True,
        "installation": _serialize_installation(installation),
        "entitlement": entitlement,
        "entitlement_token": entitlement_token,
        "seat_usage": {
            "active_installations": refreshed_active_count,
            "max_installations": int(activation_code.max_installations),
            "customer_ref": activation_code.customer_ref,
        },
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

    valid_until = _parse_iso_datetime(payload.valid_until)
    if valid_until and valid_until <= _now_utc():
        raise HTTPException(status_code=400, detail="valid_until must be in the future")

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
        plan_code=str(payload.plan_code or "").strip() or "monthly",
        valid_until=valid_until,
        max_installations=int(payload.max_installations or LCP_DEFAULT_MAX_INSTALLATIONS),
        is_active=True,
        usage_count=0,
        metadata_json=_dump_metadata(payload.metadata or {}),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
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
        metadata_json=_dump_metadata(payload.metadata or {}),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {
        "ok": True,
        "client_token": raw_token,
        "client_token_record": _serialize_client_token(record),
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
    return {"ok": True, "client_token_record": _serialize_client_token(record)}


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
        filters.append(func.lower(Installation.subscription_status) == status_text)

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

    items: list[dict[str, Any]] = []
    for installation in installations:
        entitlement = _compute_entitlement(installation)
        items.append(
            {
                "installation": _serialize_installation(installation),
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

    status_value = str(payload.subscription_status or "").strip().lower()
    if status_value not in {"none", "active", "trialing", "grace", "past_due", "canceled"}:
        raise HTTPException(status_code=400, detail="Unsupported subscription_status")

    installation.subscription_status = status_value
    installation.plan_code = str(payload.plan_code or "").strip() or installation.plan_code
    installation.customer_ref = str(payload.customer_ref or "").strip() or installation.customer_ref
    installation.subscription_valid_until = _parse_iso_datetime(payload.valid_until)

    merged_metadata = _load_metadata(installation.metadata_json)
    merged_metadata.update(payload.metadata or {})
    installation.metadata_json = _dump_metadata(merged_metadata)

    entitlement = _compute_entitlement(installation)
    entitlement, entitlement_token = _build_entitlement_bundle(entitlement)
    db.commit()

    return {
        "ok": True,
        "installation_id": installation_id,
        "subscription_status": installation.subscription_status,
        "entitlement": entitlement,
        "entitlement_token": entitlement_token,
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
    return {
        "ok": True,
        "installation": _serialize_installation(installation),
        "entitlement": entitlement,
        "entitlement_token": entitlement_token,
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
