from __future__ import annotations

import copy
import hashlib
import json
from collections import OrderedDict
from threading import RLock
from typing import Any


def build_classification_cache_key(
    *,
    cache_name: str,
    workspace_id: str | None,
    project_id: str | None,
    classifier_version: str,
    schema_version: str,
    payload: dict[str, Any],
) -> str:
    normalized_payload = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    payload_digest = hashlib.sha256(normalized_payload.encode("utf-8")).hexdigest()
    return "|".join(
        [
            str(cache_name or "").strip(),
            str(classifier_version or "").strip(),
            str(schema_version or "").strip(),
            str(workspace_id or "").strip(),
            str(project_id or "").strip(),
            payload_digest,
        ]
    )


class ClassificationCache:
    def __init__(self, *, max_entries: int = 256) -> None:
        self._max_entries = max(1, int(max_entries))
        self._items: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> dict[str, Any] | None:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            return None
        with self._lock:
            cached = self._items.get(normalized_key)
            if cached is None:
                return None
            self._items.move_to_end(normalized_key)
            return copy.deepcopy(cached)

    def set(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        normalized_key = str(key or "").strip()
        normalized_value = copy.deepcopy(value if isinstance(value, dict) else {})
        if not normalized_key:
            return normalized_value
        with self._lock:
            self._items[normalized_key] = normalized_value
            self._items.move_to_end(normalized_key)
            while len(self._items) > self._max_entries:
                self._items.popitem(last=False)
            return copy.deepcopy(normalized_value)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

