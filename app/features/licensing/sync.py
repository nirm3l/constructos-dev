from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select

from shared.models import LicenseEntitlement, LicenseInstallation, LicenseValidationLog, SessionLocal
from shared.settings import (
    APP_VERSION,
    LICENSE_HEARTBEAT_SECONDS,
    LICENSE_INSTALLATION_ID,
    LICENSE_PUBLIC_KEY,
    LICENSE_SERVER_TOKEN,
    LICENSE_SERVER_URL,
    logger,
)

from .token_crypto import LicenseTokenError, verify_entitlement_token

_worker_stop_event = threading.Event()
_worker_thread: threading.Thread | None = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
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


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _server_url(path: str) -> str:
    base = str(LICENSE_SERVER_URL or "").strip().rstrip("/")
    return f"{base}{path}"


def _server_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if LICENSE_SERVER_TOKEN:
        headers["Authorization"] = f"Bearer {LICENSE_SERVER_TOKEN}"
    return headers


def _register_payload(installation: LicenseInstallation) -> dict[str, Any]:
    metadata = {
        "source": "task-app",
    }
    return {
        "installation_id": installation.installation_id,
        "workspace_id": installation.workspace_id,
        "app_version": APP_VERSION,
        "metadata": metadata,
    }


def _heartbeat_payload(installation: LicenseInstallation) -> dict[str, Any]:
    metadata = {
        "status": installation.status,
        "plan_code": installation.plan_code,
        "last_validated_at": _to_iso(installation.last_validated_at),
    }
    return {
        "installation_id": installation.installation_id,
        "workspace_id": installation.workspace_id,
        "app_version": APP_VERSION,
        "metadata": metadata,
    }


def _append_validation_log(db, *, installation_db_id: int, result: str, reason: str, details: dict[str, Any]) -> None:
    db.add(
        LicenseValidationLog(
            installation_id=installation_db_id,
            checked_at=_now_utc(),
            result=result,
            reason=reason,
            details_json=_json_dumps(details),
        )
    )


def _apply_entitlement_payload(db, installation: LicenseInstallation, payload: dict[str, Any]) -> None:
    entitlement_payload = payload.get("entitlement") if isinstance(payload.get("entitlement"), dict) else payload
    status = str(entitlement_payload.get("status") or installation.status or "unlicensed").strip().lower() or "unlicensed"
    plan_code = str(entitlement_payload.get("plan_code") or installation.plan_code or "").strip() or None
    valid_from = _parse_iso(entitlement_payload.get("valid_from")) or _now_utc()
    valid_until = _parse_iso(entitlement_payload.get("valid_until"))
    trial_ends_at = _parse_iso(entitlement_payload.get("trial_ends_at"))
    token_expires_at = _parse_iso(entitlement_payload.get("token_expires_at"))
    metadata_payload = entitlement_payload.get("metadata") if isinstance(entitlement_payload.get("metadata"), dict) else {}

    installation.status = status
    installation.plan_code = plan_code
    if trial_ends_at is not None:
        installation.trial_ends_at = trial_ends_at
    installation.last_validated_at = _now_utc()
    installation.token_expires_at = token_expires_at

    current_metadata = {}
    try:
        current_metadata = json.loads(installation.metadata_json or "{}")
    except Exception:
        current_metadata = {}
    if not isinstance(current_metadata, dict):
        current_metadata = {}
    current_metadata.update(metadata_payload)
    installation.metadata_json = _json_dumps(current_metadata)

    latest = db.execute(
        select(LicenseEntitlement)
        .where(LicenseEntitlement.installation_id == installation.id)
        .order_by(LicenseEntitlement.valid_from.desc(), LicenseEntitlement.id.desc())
    ).scalar_one_or_none()

    should_insert = True
    if latest is not None:
        if (
            str(latest.status or "").strip().lower() == status
            and str(latest.plan_code or "").strip() == (plan_code or "")
            and _to_iso(latest.valid_until) == _to_iso(valid_until)
        ):
            latest.raw_payload_json = _json_dumps(entitlement_payload)
            should_insert = False

    if should_insert:
        db.add(
            LicenseEntitlement(
                installation_id=installation.id,
                source="control-plane",
                status=status,
                plan_code=plan_code,
                valid_from=valid_from,
                valid_until=valid_until,
                raw_payload_json=_json_dumps(entitlement_payload),
            )
        )

    _append_validation_log(
        db,
        installation_db_id=installation.id,
        result=status,
        reason="control_plane_sync_ok",
        details={
            "server": LICENSE_SERVER_URL,
            "status": status,
            "plan_code": plan_code,
            "token_expires_at": _to_iso(token_expires_at),
        },
    )


def _resolve_verified_entitlement_payload(server_payload: dict[str, Any]) -> dict[str, Any]:
    token_payload = server_payload.get("entitlement_token")
    public_key = str(LICENSE_PUBLIC_KEY or "").strip()

    if public_key:
        if not isinstance(token_payload, dict):
            raise LicenseTokenError("Signed entitlement token is required when LICENSE_PUBLIC_KEY is configured")
        verified = verify_entitlement_token(token_payload, public_key)
        return {"entitlement": verified}

    # Development fallback: when no public key is configured, accept plain payload.
    return server_payload


def sync_license_once() -> bool:
    if not str(LICENSE_SERVER_URL or "").strip():
        return False

    with SessionLocal() as db:
        installation_created = False
        installation = db.execute(
            select(LicenseInstallation).where(LicenseInstallation.installation_id == LICENSE_INSTALLATION_ID)
        ).scalar_one_or_none()
        if installation is None:
            installation_created = True
            now = _now_utc()
            installation = LicenseInstallation(
                installation_id=LICENSE_INSTALLATION_ID,
                workspace_id=None,
                status="trial",
                plan_code="trial",
                activated_at=now,
                trial_ends_at=now,
                metadata_json=_json_dumps({"source": "licensing-sync"}),
            )
            db.add(installation)
            db.flush()
        if installation_created:
            # Persist the installation record before external I/O so failed sync
            # does not erase the local installation identity.
            db.commit()

        try:
            with httpx.Client(timeout=8.0) as client:
                register_response = client.post(
                    _server_url("/v1/installations/register"),
                    headers=_server_headers(),
                    json=_register_payload(installation),
                )
                register_response.raise_for_status()

                heartbeat_response = client.post(
                    _server_url("/v1/installations/heartbeat"),
                    headers=_server_headers(),
                    json=_heartbeat_payload(installation),
                )
                heartbeat_response.raise_for_status()

            payload = heartbeat_response.json()
            if not isinstance(payload, dict):
                raise ValueError("Control-plane response must be a JSON object")
            verified_payload = _resolve_verified_entitlement_payload(payload)
            _apply_entitlement_payload(db, installation, verified_payload)
            db.commit()
            return True
        except Exception as exc:
            db.rollback()
            _append_validation_log(
                db,
                installation_db_id=installation.id,
                result="error",
                reason="control_plane_sync_failed",
                details={
                    "server": LICENSE_SERVER_URL,
                    "error": str(exc),
                },
            )
            db.commit()
            logger.warning("License sync failed: %s", exc)
            return False


def _worker_loop() -> None:
    while not _worker_stop_event.is_set():
        try:
            sync_license_once()
        except Exception as exc:
            logger.warning("License worker iteration failed: %s", exc)
        _worker_stop_event.wait(max(30, int(LICENSE_HEARTBEAT_SECONDS)))


def start_license_sync_worker() -> None:
    global _worker_thread
    if not str(LICENSE_SERVER_URL or "").strip():
        logger.info("License sync worker disabled: LICENSE_SERVER_URL is not configured")
        return
    if _worker_thread and _worker_thread.is_alive():
        return
    _worker_stop_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name="license-sync-worker", daemon=True)
    _worker_thread.start()


def stop_license_sync_worker() -> None:
    global _worker_thread
    _worker_stop_event.set()
    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=3)
    _worker_thread = None
