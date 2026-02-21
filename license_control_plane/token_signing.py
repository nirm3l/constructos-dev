from __future__ import annotations

import base64
import json
from functools import lru_cache
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class SigningError(ValueError):
    pass


def _normalize_pem(raw: str) -> str:
    return str(raw or "").replace("\\n", "\n").strip()


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _encode_base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@lru_cache(maxsize=2)
def _load_private_key(pem_text: str) -> Ed25519PrivateKey:
    normalized = _normalize_pem(pem_text)
    if not normalized:
        raise SigningError("Signing private key is not configured")
    try:
        loaded = serialization.load_pem_private_key(normalized.encode("utf-8"), password=None)
    except Exception as exc:  # pragma: no cover - defensive
        raise SigningError(f"Failed to parse private key: {exc}") from exc
    if not isinstance(loaded, Ed25519PrivateKey):
        raise SigningError("Private key must be Ed25519")
    return loaded


def sign_entitlement_payload(
    payload: dict[str, Any],
    *,
    private_key_pem: str,
    key_id: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SigningError("Entitlement payload must be an object")
    message = _canonical_json(payload)
    private_key = _load_private_key(_normalize_pem(private_key_pem))
    signature = private_key.sign(message)
    return {
        "alg": "ed25519",
        "kid": str(key_id or "").strip() or None,
        "payload": payload,
        "signature": _encode_base64url(signature),
    }
