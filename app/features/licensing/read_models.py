from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.models import LicenseEntitlement, LicenseInstallation
from shared.licensing import resolve_license_installation_id
from shared.settings import (
    APP_BUILD,
    APP_VERSION,
    LICENSE_ENFORCEMENT_ENABLED,
    LICENSE_GRACE_HOURS,
)

from .domain import (
    LICENSE_STATUS_ACTIVE,
    LICENSE_STATUS_EXPIRED,
    LICENSE_STATUS_GRACE,
    LICENSE_STATUS_TRIAL,
    LICENSE_STATUS_UNLICENSED,
    WRITE_ALLOWED_STATUSES,
)

_VERSION_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


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
    ).scalars().first()


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


def _sanitize_license_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(metadata)
    subscription_status = str(cleaned.get("subscription_status") or "").strip().lower()
    if subscription_status != "beta":
        # Legacy control-plane payloads could leave beta markers in local metadata.
        # Do not expose beta flags for non-beta subscriptions.
        for key in (
            "public_beta",
            "public_beta_free_until",
            "public_beta_active",
            "beta_plan_valid_until",
            "beta_plan_active",
        ):
            cleaned.pop(key, None)
    return cleaned


def _public_license_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    cleaned = _sanitize_license_metadata(metadata)
    cleaned.pop("control_plane_notifications", None)
    return cleaned


def _normalize_version_token(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if _VERSION_TOKEN_RE.fullmatch(token):
        return token
    return ""


def _license_notifications_read_model(
    *,
    status_payload: dict[str, Any],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    notifications: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_dedupe: set[str] = set()

    current_version = _normalize_version_token(status_payload.get("app_version"))
    current_build = _normalize_version_token(status_payload.get("app_build"))
    latest_version = _normalize_version_token(
        metadata.get("latest_app_version")
        or metadata.get("available_app_version")
        or metadata.get("latest_version")
        or metadata.get("app_update_version")
    )
    latest_image_tag = _normalize_version_token(
        metadata.get("latest_image_tag")
        or metadata.get("available_image_tag")
        or metadata.get("app_image_tag")
    )
    update_released_at = str(
        metadata.get("latest_release_at")
        or metadata.get("latest_release_date")
        or status_payload.get("last_validated_at")
        or ""
    ).strip() or None

    has_update_version = bool(latest_version and latest_version != current_version)
    has_update_tag = bool(latest_image_tag and latest_image_tag != current_version and latest_image_tag != current_build)
    if has_update_version or has_update_tag:
        target_version = latest_version or latest_image_tag
        dedupe_key = f"license-app-update:{target_version}"
        if dedupe_key not in seen_dedupe:
            seen_dedupe.add(dedupe_key)
            notification_id = dedupe_key
            if notification_id not in seen_ids:
                seen_ids.add(notification_id)
                notifications.append(
                    {
                        "id": notification_id,
                        "message": f"New application version is available: {target_version}",
                        "is_read": False,
                        "created_at": update_released_at,
                        "notification_type": "AppUpdateAvailable",
                        "severity": "info",
                        "dedupe_key": dedupe_key,
                        "source_event": "license.status",
                        "payload": {
                            "title": "New application version available",
                            "action": "auto_update_app_images",
                            "action_label": "Update app",
                            "description": "Pull latest task-app and mcp-tools images and restart those services.",
                            "target_image_tag": target_version,
                        },
                    }
                )

    control_plane_notifications = metadata.get("control_plane_notifications")
    if isinstance(control_plane_notifications, list):
        for item in control_plane_notifications:
            if not isinstance(item, dict):
                continue
            notification_id = str(item.get("id") or "").strip()
            if not notification_id or notification_id in seen_ids:
                continue
            dedupe_key = str(item.get("dedupe_key") or notification_id).strip() or notification_id
            if dedupe_key in seen_dedupe:
                continue
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            notifications.append(
                {
                    "id": notification_id,
                    "message": str(item.get("message") or "").strip() or "Notification",
                    "is_read": bool(item.get("is_read")),
                    "created_at": str(item.get("created_at") or "").strip() or None,
                    "notification_type": str(item.get("notification_type") or "ControlPlaneMessage").strip() or "ControlPlaneMessage",
                    "severity": str(item.get("severity") or "info").strip() or "info",
                    "dedupe_key": dedupe_key,
                    "source_event": str(item.get("source_event") or "control-plane.notification").strip() or "control-plane.notification",
                    "payload": payload,
                }
            )
            seen_ids.add(notification_id)
            seen_dedupe.add(dedupe_key)
    return notifications


def license_status_read_model(db: Session) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    installation_id = resolve_license_installation_id(db)
    installation = db.execute(
        select(LicenseInstallation).where(LicenseInstallation.installation_id == installation_id)
    ).scalar_one_or_none()
    if installation is None:
        payload = {
            "installation_id": installation_id,
            "status": LICENSE_STATUS_UNLICENSED,
            "plan_code": None,
            "enforcement_enabled": bool(LICENSE_ENFORCEMENT_ENABLED),
            "write_access": not bool(LICENSE_ENFORCEMENT_ENABLED),
            "trial_ends_at": None,
            "grace_ends_at": None,
            "last_validated_at": None,
            "token_expires_at": None,
            "metadata": {},
            "app_version": APP_VERSION,
            "app_build": APP_BUILD,
        }
        payload["notifications"] = _license_notifications_read_model(status_payload=payload, metadata={})
        return payload

    entitlement = _latest_entitlement(db, installation.id)
    trial_ends_at = _ensure_aware(installation.trial_ends_at)
    grace_ends_at = (trial_ends_at + timedelta(hours=max(0, int(LICENSE_GRACE_HOURS)))) if trial_ends_at else None

    status = str(installation.status or LICENSE_STATUS_TRIAL).strip().lower() or LICENSE_STATUS_TRIAL
    plan_code = str(installation.plan_code or "").strip() or None

    ent_status = str(entitlement.status or "").strip().lower() if entitlement else ""
    ent_valid_until = _ensure_aware(entitlement.valid_until) if entitlement else None
    if entitlement:
        if ent_status in {LICENSE_STATUS_ACTIVE, LICENSE_STATUS_TRIAL} and (ent_valid_until is None or ent_valid_until > now):
            status = ent_status
            if not plan_code:
                plan_code = str(entitlement.plan_code or "").strip() or None
        elif ent_status == LICENSE_STATUS_GRACE and (ent_valid_until is None or ent_valid_until > now):
            status = LICENSE_STATUS_GRACE
            if not plan_code:
                plan_code = str(entitlement.plan_code or "").strip() or None
        elif ent_status in {LICENSE_STATUS_EXPIRED, LICENSE_STATUS_UNLICENSED}:
            # Control-plane explicitly returned non-writable status.
            status = ent_status
            if not plan_code:
                plan_code = str(entitlement.plan_code or "").strip() or None
        elif ent_valid_until is not None and ent_valid_until <= now:
            # Stale entitlement with elapsed validity should not fall back to local trial window.
            status = LICENSE_STATUS_EXPIRED
        elif status not in {LICENSE_STATUS_ACTIVE, LICENSE_STATUS_TRIAL, LICENSE_STATUS_GRACE, LICENSE_STATUS_EXPIRED}:
            status = LICENSE_STATUS_UNLICENSED
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
    metadata = _sanitize_license_metadata(_coerce_metadata(installation.metadata_json))
    public_metadata = _public_license_metadata(metadata)

    payload = {
        "installation_id": installation.installation_id,
        "status": status,
        "plan_code": plan_code,
        "enforcement_enabled": enforcement_enabled,
        "write_access": write_access,
        "trial_ends_at": trial_ends_at.isoformat() if trial_ends_at else None,
        "grace_ends_at": grace_ends_at.isoformat() if grace_ends_at else None,
        "last_validated_at": _ensure_aware(installation.last_validated_at).isoformat() if installation.last_validated_at else None,
        "token_expires_at": _ensure_aware(installation.token_expires_at).isoformat() if installation.token_expires_at else None,
        "metadata": public_metadata,
        "app_version": APP_VERSION,
        "app_build": APP_BUILD,
    }
    payload["notifications"] = _license_notifications_read_model(status_payload=payload, metadata=metadata)
    return payload


def license_health_summary_read_model(db: Session) -> dict[str, Any]:
    payload = license_status_read_model(db)
    return {
        "status": payload["status"],
        "enforcement_enabled": payload["enforcement_enabled"],
        "write_access": payload["write_access"],
    }
