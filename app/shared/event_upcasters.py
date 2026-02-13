from __future__ import annotations

from copy import deepcopy
from typing import Any


def upcast_event(
    event_type: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    p = deepcopy(payload)
    m = deepcopy(metadata)
    schema_version = int(m.get("schema_version", 1))

    if schema_version < 2 and event_type in {"TaskCreated", "TaskUpdated"}:
        if "projectId" in p and "project_id" not in p:
            p["project_id"] = p.pop("projectId")
        if p.get("priority") == "Medium":
            p["priority"] = "Med"
        m["schema_version"] = 2

    return p, m
