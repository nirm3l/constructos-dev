from __future__ import annotations

import json
from typing import Any


_RELATIONSHIP_KINDS = {"depends_on", "delivers_to", "hands_off_to", "escalates_to"}
_MATCH_MODES = {"any", "all"}


def _normalize_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = _normalize_string(raw)
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def normalize_task_relationships(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            parsed = []
    else:
        parsed = value
    if not isinstance(parsed, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...], tuple[str, ...], str]] = set()
    for item in parsed:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "depends_on").strip().lower()
        if kind not in _RELATIONSHIP_KINDS:
            continue
        task_ids = _normalize_string_list(item.get("task_ids"))
        if not task_ids:
            continue
        statuses = _normalize_string_list(item.get("statuses"))
        match_mode_raw = str(item.get("match_mode") or "all").strip().lower()
        match_mode = match_mode_raw if match_mode_raw in _MATCH_MODES else "all"
        relationship = {
            "kind": kind,
            "task_ids": task_ids,
            "match_mode": match_mode,
        }
        if statuses:
            relationship["statuses"] = statuses
        key = (
            kind,
            tuple(task_ids),
            tuple(statuses),
            match_mode,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(relationship)
    return out
