from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.models import LicenseEntitlement, LicenseInstallation
from shared.settings import (
    LICENSE_ENFORCEMENT_ENABLED,
    LICENSE_GRACE_HOURS,
    LICENSE_INSTALLATION_ID,
    LICENSE_SERVER_URL,
)

from .domain import (
    LICENSE_STATUS_ACTIVE,
    LICENSE_STATUS_EXPIRED,
    LICENSE_STATUS_GRACE,
    LICENSE_STATUS_TRIAL,
    LICENSE_STATUS_UNLICENSED,
    WRITE_ALLOWED_STATUSES,
)


def _ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _latest_entitlement(db: Session, installation_db_id: int) -> LicenseEntitlement | None:
    return db.execute(
        select(LicenseEntitlement)
        .where(LicenseEntitlement.installation_id == installation_db_id)
        .order_by(LicenseEntitlement.valid_from.desc(), LicenseEntitlement.id.desc())
    ).scalar_one_or_none()


def _coerce_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def license_status_read_model(db: Session) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    installation = db.execute(
        select(LicenseInstallation).where(LicenseInstallation.installation_id == LICENSE_INSTALLATION_ID)
    ).scalar_one_or_none()
    if installation is None:
        return {
            "installation_id": LICENSE_INSTALLATION_ID,
            "status": LICENSE_STATUS_UNLICENSED,
            "plan_code": None,
            "enforcement_enabled": bool(LICENSE_ENFORCEMENT_ENABLED),
            "write_access": not bool(LICENSE_ENFORCEMENT_ENABLED),
            "trial_ends_at": None,
            "grace_ends_at": None,
            "last_validated_at": None,
            "token_expires_at": None,
            "license_server_url": LICENSE_SERVER_URL or None,
            "metadata": {},
        }

    entitlement = _latest_entitlement(db, installation.id)
    trial_ends_at = _ensure_aware(installation.trial_ends_at)
    grace_ends_at = (trial_ends_at + timedelta(hours=max(0, int(LICENSE_GRACE_HOURS)))) if trial_ends_at else None

    status = str(installation.status or LICENSE_STATUS_TRIAL).strip().lower() or LICENSE_STATUS_TRIAL
    plan_code = str(installation.plan_code or "").strip() or None

    ent_status = str(entitlement.status or "").strip().lower() if entitlement else ""
    ent_valid_until = _ensure_aware(entitlement.valid_until) if entitlement else None
    if entitlement and ent_status in {LICENSE_STATUS_ACTIVE, LICENSE_STATUS_TRIAL} and (
        ent_valid_until is None or ent_valid_until > now
    ):
        status = ent_status
        if not plan_code:
            plan_code = str(entitlement.plan_code or "").strip() or None
    elif trial_ends_at:
        if trial_ends_at > now:
            status = LICENSE_STATUS_TRIAL
        elif grace_ends_at and grace_ends_at > now:
            status = LICENSE_STATUS_GRACE
        else:
            status = LICENSE_STATUS_EXPIRED
    elif status not in {LICENSE_STATUS_ACTIVE, LICENSE_STATUS_TRIAL, LICENSE_STATUS_GRACE, LICENSE_STATUS_EXPIRED}:
        status = LICENSE_STATUS_UNLICENSED

    enforcement_enabled = bool(LICENSE_ENFORCEMENT_ENABLED)
    write_access = (not enforcement_enabled) or (status in WRITE_ALLOWED_STATUSES)

    return {
        "installation_id": installation.installation_id,
        "status": status,
        "plan_code": plan_code,
        "enforcement_enabled": enforcement_enabled,
        "write_access": write_access,
        "trial_ends_at": trial_ends_at.isoformat() if trial_ends_at else None,
        "grace_ends_at": grace_ends_at.isoformat() if grace_ends_at else None,
        "last_validated_at": _ensure_aware(installation.last_validated_at).isoformat() if installation.last_validated_at else None,
        "token_expires_at": _ensure_aware(installation.token_expires_at).isoformat() if installation.token_expires_at else None,
        "license_server_url": LICENSE_SERVER_URL or None,
        "metadata": _coerce_metadata(installation.metadata_json),
    }


def license_health_summary_read_model(db: Session) -> dict[str, Any]:
    payload = license_status_read_model(db)
    return {
        "status": payload["status"],
        "enforcement_enabled": payload["enforcement_enabled"],
        "write_access": payload["write_access"],
    }

