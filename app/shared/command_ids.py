from __future__ import annotations

import hashlib


def derive_child_command_id(command_id: str | None, child_key: str, *, max_length: int = 64) -> str | None:
    normalized = str(command_id or "").strip()
    if not normalized:
        return None
    suffix = str(child_key or "").strip()
    if not suffix:
        return normalized[: max(1, int(max_length or 64))]
    candidate = f"{normalized}:{suffix}"
    target_length = max(8, int(max_length or 64))
    if len(candidate) <= target_length:
        return candidate
    suffix_digest = hashlib.sha1(suffix.encode("utf-8")).hexdigest()[:12]
    keep = max(1, target_length - len(suffix_digest) - 1)
    return f"{normalized[:keep]}:{suffix_digest}"


def derive_scoped_command_id(base: str, *parts: object, max_length: int = 64) -> str:
    normalized_base = str(base or "").strip() or "cmd"
    normalized_parts = [str(part or "").strip() for part in parts if str(part or "").strip()]
    target_length = max(8, int(max_length or 64))
    if not normalized_parts:
        return normalized_base[:target_length]
    suffix = ":".join(normalized_parts)
    candidate = f"{normalized_base}:{suffix}"
    if len(candidate) <= target_length:
        return candidate
    suffix_digest = hashlib.sha1(suffix.encode("utf-8")).hexdigest()[:12]
    keep = max(1, target_length - len(suffix_digest) - 1)
    return f"{normalized_base[:keep]}:{suffix_digest}"
