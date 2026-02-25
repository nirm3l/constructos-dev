from __future__ import annotations

from copy import deepcopy
from typing import Any

from .typed_notifications import (
    DEFAULT_NOTIFICATION_SEVERITY,
    DEFAULT_NOTIFICATION_TYPE,
    dumps_payload_json,
    normalize_dedupe_key,
    normalize_notification_type,
    normalize_severity,
)


def _normalize_optional_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


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

    if event_type in {"TaskCreated", "TaskUpdated"}:
        if "taskGroupId" in p and "task_group_id" not in p:
            p["task_group_id"] = p.pop("taskGroupId")
        if "specificationId" in p and "specification_id" not in p:
            p["specification_id"] = p.pop("specificationId")
        if "assigneeId" in p and "assignee_id" not in p:
            p["assignee_id"] = p.pop("assigneeId")
        for key in ("task_group_id", "specification_id", "assignee_id"):
            if key in p:
                p[key] = _normalize_optional_id(p.get(key))

    if event_type == "NotificationCreated":
        if "notification_type" not in p:
            p["notification_type"] = DEFAULT_NOTIFICATION_TYPE
        else:
            p["notification_type"] = normalize_notification_type(p.get("notification_type"))
        if "severity" not in p:
            p["severity"] = DEFAULT_NOTIFICATION_SEVERITY
        else:
            p["severity"] = normalize_severity(p.get("severity"))
        if "dedupe_key" in p:
            p["dedupe_key"] = normalize_dedupe_key(p.get("dedupe_key"))
        else:
            p["dedupe_key"] = None
        source_event = str(p.get("source_event") or "").strip()
        p["source_event"] = source_event or None
        if "payload_json" not in p:
            p["payload_json"] = dumps_payload_json({})
        else:
            raw_payload_json = p.get("payload_json")
            if isinstance(raw_payload_json, dict):
                p["payload_json"] = dumps_payload_json(raw_payload_json)
            else:
                text = str(raw_payload_json or "").strip()
                p["payload_json"] = text or "{}"

    return p, m


def upcast_snapshot(payload: dict[str, Any], *, fallback_version: int = 0) -> tuple[dict[str, Any], int]:
    p = deepcopy(payload)

    # Legacy snapshot format: raw state only, without wrapper.
    if "state" not in p:
        if "projectId" in p and "project_id" not in p:
            p["project_id"] = p.pop("projectId")
        return p, fallback_version

    version = int(p.get("version", fallback_version))
    snapshot_schema_version = int(p.get("snapshot_schema_version", 1))
    state = deepcopy(p.get("state", {}))

    if snapshot_schema_version < 2:
        # Keep migration minimal: normalize known old aliases.
        if isinstance(state, dict) and "projectId" in state and "project_id" not in state:
            state["project_id"] = state.pop("projectId")

    return state, version
