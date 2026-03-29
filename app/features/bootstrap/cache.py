from __future__ import annotations

import copy
import threading
import time
from typing import Any, Callable

_LOCK = threading.Lock()
_ENTRIES: dict[str, dict[str, Any]] = {}


def clear_bootstrap_cache(*, key: str | None = None) -> None:
    with _LOCK:
        if key is None:
            _ENTRIES.clear()
            return
        _ENTRIES.pop(str(key or "").strip(), None)


def bootstrap_cache_status(*, key: str) -> dict[str, Any]:
    normalized_key = str(key or "").strip()
    now = time.monotonic()
    with _LOCK:
        entry = _ENTRIES.get(normalized_key) or {}
        expires_at = float(entry.get("expires_at") or 0.0)
        payload = entry.get("payload")
        hit_count = int(entry.get("hit_count") or 0)
        miss_count = int(entry.get("miss_count") or 0)
    return {
        "key": normalized_key,
        "has_payload": payload is not None,
        "hit_count": hit_count,
        "miss_count": miss_count,
        "expires_in_seconds": round(max(0.0, expires_at - now), 3) if expires_at > 0 else 0.0,
    }


def get_or_compute_bootstrap_cache(
    *,
    key: str,
    ttl_seconds: float,
    force_refresh: bool,
    compute: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    normalized_key = str(key or "").strip()
    now = time.monotonic()
    with _LOCK:
        entry = _ENTRIES.get(normalized_key)
        if (
            not force_refresh
            and entry is not None
            and entry.get("payload") is not None
            and now < float(entry.get("expires_at") or 0.0)
        ):
            entry["hit_count"] = int(entry.get("hit_count") or 0) + 1
            return copy.deepcopy(entry["payload"]), True

    computed = dict(compute() or {})
    with _LOCK:
        previous = _ENTRIES.get(normalized_key) or {}
        _ENTRIES[normalized_key] = {
            "payload": copy.deepcopy(computed),
            "expires_at": time.monotonic() + max(1.0, float(ttl_seconds)),
            "hit_count": int(previous.get("hit_count") or 0),
            "miss_count": int(previous.get("miss_count") or 0) + 1,
        }
    return computed, False

