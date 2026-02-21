from __future__ import annotations

import base64
import json
from functools import lru_cache
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class LicenseTokenError(ValueError):
    pass


def _normalize_pem(raw: str) -> str:
    return str(raw or "").replace("\\n", "\n").strip()


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _decode_base64url(raw: str) -> bytes:
    text = str(raw or "").strip()
    if not text:
        raise LicenseTokenError("Token signature is empty")
    padding = "=" * ((4 - len(text) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except Exception as exc:  # pragma: no cover - defensive
        raise LicenseTokenError(f"Invalid base64url signature: {exc}") from exc


@lru_cache(maxsize=2)
def _load_public_key(pem_text: str) -> Ed25519PublicKey:
    normalized = _normalize_pem(pem_text)
    if not normalized:
        raise LicenseTokenError("LICENSE_PUBLIC_KEY is not configured")
    try:
        loaded = serialization.load_pem_public_key(normalized.encode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise LicenseTokenError(f"Failed to parse public key: {exc}") from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise LicenseTokenError("Public key must be Ed25519")
    return loaded


def verify_entitlement_token(token: dict[str, Any], public_key_pem: str) -> dict[str, Any]:
    if not isinstance(token, dict):
        raise LicenseTokenError("entitlement_token must be a JSON object")

    alg = str(token.get("alg") or "").strip().lower()
    if alg != "ed25519":
        raise LicenseTokenError(f"Unsupported token algorithm: {alg or 'missing'}")

    payload = token.get("payload")
    if not isinstance(payload, dict):
        raise LicenseTokenError("entitlement_token.payload must be an object")

    signature_raw = token.get("signature")
    signature = _decode_base64url(str(signature_raw or ""))

    public_key = _load_public_key(_normalize_pem(public_key_pem))
    message = _canonical_json(payload)
    try:
        public_key.verify(signature, message)
    except Exception as exc:
        raise LicenseTokenError(f"Token signature verification failed: {exc}") from exc
    return payload
