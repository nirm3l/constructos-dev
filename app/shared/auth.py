from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

PBKDF2_ITERATIONS = 600_000
PBKDF2_HASH_NAME = "sha256"
PBKDF2_SALT_BYTES = 16
SESSION_TOKEN_BYTES = 32
TEMP_PASSWORD_ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64_decode(raw: str) -> bytes:
    padded = raw + "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def hash_password(password: str) -> str:
    text = str(password or "")
    if not text:
        raise ValueError("password cannot be empty")
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(PBKDF2_HASH_NAME, text.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_{PBKDF2_HASH_NAME}${PBKDF2_ITERATIONS}${_b64_encode(salt)}${_b64_encode(digest)}"


def verify_password(password: str, encoded_hash: str | None) -> bool:
    if not encoded_hash:
        return False
    text = str(password or "")
    if not text:
        return False
    try:
        method, iterations_raw, salt_b64, digest_b64 = encoded_hash.split("$", 3)
        if method != f"pbkdf2_{PBKDF2_HASH_NAME}":
            return False
        iterations = int(iterations_raw)
        salt = _b64_decode(salt_b64)
        expected = _b64_decode(digest_b64)
    except Exception:
        return False
    candidate = hashlib.pbkdf2_hmac(PBKDF2_HASH_NAME, text.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


def generate_session_token() -> str:
    return _b64_encode(secrets.token_bytes(SESSION_TOKEN_BYTES))


def hash_session_token(token: str) -> str:
    text = str(token or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def generate_temporary_password(length: int = 12) -> str:
    size = max(8, int(length))
    return "".join(secrets.choice(TEMP_PASSWORD_ALPHABET) for _ in range(size))
