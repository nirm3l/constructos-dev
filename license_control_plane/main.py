from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Integer, String, Text, create_engine, func, or_, select
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
    }


@app.post("/v1/installations/register")
def register_installation(
    payload: InstallationRegisterRequest,
    _auth: None = Depends(_require_api_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    installation = _upsert_installation(db, payload)
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
    _auth: None = Depends(_require_api_token),
    db: Session = Depends(_get_db),
) -> dict[str, Any]:
    installation = _upsert_installation(db, payload)
    entitlement = _compute_entitlement(installation)
    entitlement, entitlement_token = _build_entitlement_bundle(entitlement)
    db.commit()
    return {"ok": True, "entitlement": entitlement, "entitlement_token": entitlement_token}


@app.get("/v1/admin/installations")
def admin_list_installations(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _auth: None = Depends(_require_api_token),
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
    _auth: None = Depends(_require_api_token),
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
