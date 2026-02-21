from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import settings
from .models import LicenseInstallation

_cached_installation_id: str | None = None


def _normalize_installation_id(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def configured_license_installation_id() -> str | None:
    return _normalize_installation_id(settings.LICENSE_INSTALLATION_ID)


def resolve_license_installation_id(db: Session) -> str:
    global _cached_installation_id

    configured = configured_license_installation_id()
    if configured:
        _cached_installation_id = configured
        return configured

    if _cached_installation_id:
        cached_exists = db.execute(
            select(LicenseInstallation.id).where(LicenseInstallation.installation_id == _cached_installation_id)
        ).scalar_one_or_none()
        if cached_exists is not None:
            return _cached_installation_id
        _cached_installation_id = None

    existing = db.execute(
        select(LicenseInstallation.installation_id).order_by(LicenseInstallation.id.asc()).limit(1)
    ).scalar_one_or_none()
    if existing:
        _cached_installation_id = existing
        return existing

    generated = f"inst-{uuid.uuid4()}"
    _cached_installation_id = generated
    settings.logger.info("Generated license installation id: %s", generated)
    return generated


def reset_license_installation_id_cache() -> None:
    global _cached_installation_id
    _cached_installation_id = None
