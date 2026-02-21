from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import Mapped, Session, declarative_base, mapped_column, sessionmaker


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    return int(raw)


LCP_DATABASE_URL = os.getenv("LCP_DATABASE_URL", "sqlite:////data/license-control-plane.db").strip() or "sqlite:////data/license-control-plane.db"
LCP_API_TOKEN = os.getenv("LCP_API_TOKEN", "").strip()
LCP_TRIAL_DAYS = max(1, _env_int("LCP_TRIAL_DAYS", 7))
LCP_TOKEN_TTL_SECONDS = max(60, _env_int("LCP_TOKEN_TTL_SECONDS", 3600))

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


def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _require_api_token(authorization: str | None = Header(default=None)) -> None:
    if not LCP_API_TOKEN:
        return
    expected = f"Bearer {LCP_API_TOKEN}"
    if not authorization or authorization != expected:
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


app = FastAPI(title="m4tr1x Licensing Control Plane")


@app.on_event("startup")
def _startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "timestamp": _now_utc().isoformat(),
        "trial_days": LCP_TRIAL_DAYS,
    }


@app.post("/v1/installations/register")
def register_installation(
    payload: InstallationRegisterRequest,
    _auth: None = Depends(_require_api_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    installation = _upsert_installation(db, payload)
    entitlement = _compute_entitlement(installation)
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
    }


@app.post("/v1/installations/heartbeat")
def heartbeat_installation(
    payload: InstallationHeartbeatRequest,
    _auth: None = Depends(_require_api_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    installation = _upsert_installation(db, payload)
    entitlement = _compute_entitlement(installation)
    db.commit()
    return {"ok": True, "entitlement": entitlement}


@app.put("/v1/admin/installations/{installation_id}/subscription")
def admin_update_subscription(
    installation_id: str,
    payload: AdminSubscriptionUpdateRequest,
    _auth: None = Depends(_require_api_token),
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
    db.commit()

    return {
        "ok": True,
        "installation_id": installation_id,
        "subscription_status": installation.subscription_status,
        "entitlement": entitlement,
    }


@app.get("/v1/admin/installations/{installation_id}")
def admin_get_installation(
    installation_id: str,
    _auth: None = Depends(_require_api_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    installation = db.execute(
        select(Installation).where(Installation.installation_id == installation_id)
    ).scalar_one_or_none()
    if installation is None:
        raise HTTPException(status_code=404, detail="Installation not found")

    entitlement = _compute_entitlement(installation)
    return {
        "ok": True,
        "installation": {
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
        },
        "entitlement": entitlement,
    }
