from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .schedule import next_scheduled_at_utc, parse_recurring_rule

TRIGGER_KIND_MANUAL = "manual"
TRIGGER_KIND_SCHEDULE = "schedule"
TRIGGER_KIND_STATUS_CHANGE = "status_change"
TRIGGER_KINDS = {TRIGGER_KIND_MANUAL, TRIGGER_KIND_SCHEDULE, TRIGGER_KIND_STATUS_CHANGE}
STATUS_SCOPE_SELF = "self"
STATUS_SCOPE_EXTERNAL = "external"
STATUS_SCOPE_EXTERNAL_ALIASES = {
    STATUS_SCOPE_EXTERNAL,
    "other",
    "other_task",
    "other_tasks",
}
STATUS_MATCH_ANY = "any"
STATUS_MATCH_ALL = "all"
DEFAULT_SCHEDULE_RUN_ON_STATUSES = ["In Progress"]


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


def _normalize_string_list_or_csv(values: Any) -> list[str]:
    if isinstance(values, list):
        return _normalize_string_list(values)
    if isinstance(values, str):
        return _normalize_string_list([part.strip() for part in values.split(",")])
    return []


def _normalize_status_change_action(raw: Any) -> str | dict[str, Any] | None:
    if isinstance(raw, str):
        return _normalize_string(raw)
    if not isinstance(raw, dict):
        return None
    action: dict[str, Any] = {}
    action_type = _normalize_string(raw.get("type") or raw.get("action"))
    if action_type:
        action["type"] = action_type
    target_task_id = _normalize_string(raw.get("target_task_id"))
    target_task_ids = _normalize_string_list(raw.get("target_task_ids"))
    if target_task_id and target_task_id.casefold() not in {item.casefold() for item in target_task_ids}:
        target_task_ids = [target_task_id, *target_task_ids]
    if target_task_ids:
        action["target_task_ids"] = target_task_ids
        action["target_task_id"] = target_task_ids[0]
    payload = raw.get("payload")
    if isinstance(payload, dict):
        action["payload"] = payload
    return action or None


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def normalize_schedule_run_on_statuses(values: Any) -> list[str]:
    normalized = _normalize_string_list(values)
    if normalized:
        return normalized
    return list(DEFAULT_SCHEDULE_RUN_ON_STATUSES)


def _normalize_schedule_trigger(raw: dict[str, Any], *, enabled: bool) -> dict[str, Any] | None:
    scheduled_at_utc = _normalize_string(raw.get("scheduled_at_utc"))
    if not scheduled_at_utc:
        return None
    out: dict[str, Any] = {
        "kind": TRIGGER_KIND_SCHEDULE,
        "enabled": enabled,
        "scheduled_at_utc": scheduled_at_utc,
    }
    timezone_name = _normalize_string(raw.get("schedule_timezone"))
    if timezone_name:
        out["schedule_timezone"] = timezone_name
    recurring_rule = _normalize_string(raw.get("recurring_rule"))
    if recurring_rule:
        out["recurring_rule"] = recurring_rule
    out["run_on_statuses"] = normalize_schedule_run_on_statuses(raw.get("run_on_statuses"))
    return out


def _normalize_status_selector(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    selector: dict[str, Any] = {}
    task_ids: list[str] = []
    seen_task_ids: set[str] = set()

    def _append_task_id(value: Any) -> None:
        normalized = _normalize_string(value)
        if not normalized:
            return
        key = normalized.casefold()
        if key in seen_task_ids:
            return
        seen_task_ids.add(key)
        task_ids.append(normalized)

    for item in _normalize_string_list_or_csv(raw.get("task_ids")):
        _append_task_id(item)
    _append_task_id(raw.get("task_id"))
    for item in _normalize_string_list_or_csv(raw.get("source_task_ids")):
        _append_task_id(item)
    _append_task_id(raw.get("source_task_id"))
    if task_ids:
        selector["task_ids"] = task_ids
    project_id = _normalize_string(raw.get("project_id"))
    if project_id:
        selector["project_id"] = project_id
    specification_id = _normalize_string(raw.get("specification_id"))
    if specification_id:
        selector["specification_id"] = specification_id
    assignee_id = _normalize_string(raw.get("assignee_id"))
    if assignee_id:
        selector["assignee_id"] = assignee_id
    labels_any = _normalize_string_list_or_csv(raw.get("labels_any"))
    if labels_any:
        selector["labels_any"] = labels_any
    return selector


def _normalize_status_change_trigger(raw: dict[str, Any], *, enabled: bool) -> dict[str, Any]:
    scope_raw = str(raw.get("scope") or "").strip().lower()
    match_mode_raw = str(raw.get("match_mode") or STATUS_MATCH_ANY).strip().lower()
    match_mode = STATUS_MATCH_ALL if match_mode_raw == STATUS_MATCH_ALL else STATUS_MATCH_ANY
    top_level_source_task_ids = _normalize_string_list_or_csv(raw.get("source_task_ids"))
    top_level_source_task_id = _normalize_string(raw.get("source_task_id"))
    if top_level_source_task_id and top_level_source_task_id.casefold() not in {
        item.casefold() for item in top_level_source_task_ids
    }:
        top_level_source_task_ids = [top_level_source_task_id, *top_level_source_task_ids]
    out: dict[str, Any] = {
        "kind": TRIGGER_KIND_STATUS_CHANGE,
        "enabled": enabled,
        "match_mode": match_mode,
        "from_statuses": _normalize_string_list(raw.get("from_statuses")),
        "to_statuses": _normalize_string_list(raw.get("to_statuses")),
    }
    selector = _normalize_status_selector(raw.get("selector"))
    if top_level_source_task_ids:
        selector_task_ids = list(selector.get("task_ids") or [])
        seen_selector_ids = {str(item).casefold() for item in selector_task_ids}
        for source_task_id in top_level_source_task_ids:
            if source_task_id.casefold() in seen_selector_ids:
                continue
            seen_selector_ids.add(source_task_id.casefold())
            selector_task_ids.append(source_task_id)
        selector["task_ids"] = selector_task_ids
    scope = (
        STATUS_SCOPE_EXTERNAL
        if scope_raw in STATUS_SCOPE_EXTERNAL_ALIASES
        or (scope_raw not in {STATUS_SCOPE_SELF, STATUS_SCOPE_EXTERNAL} and bool(selector.get("task_ids")))
        else STATUS_SCOPE_SELF
    )
    out["scope"] = scope
    if selector:
        out["selector"] = selector
    cooldown_raw = raw.get("cooldown_seconds")
    if cooldown_raw is not None:
        try:
            out["cooldown_seconds"] = max(0, int(cooldown_raw))
        except Exception:
            pass
    target_task_id = _normalize_string(raw.get("target_task_id"))
    target_task_ids = _normalize_string_list(raw.get("target_task_ids"))
    if target_task_id and target_task_id.casefold() not in {item.casefold() for item in target_task_ids}:
        target_task_ids = [target_task_id, *target_task_ids]
    if target_task_ids:
        out["target_task_ids"] = target_task_ids
        out["target_task_id"] = target_task_ids[0]
    action = _normalize_status_change_action(raw.get("action"))
    if action is not None:
        out["action"] = action
    return out


def normalize_execution_triggers(value: Any) -> list[dict[str, Any]]:
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
    seen_keys: set[str] = set()
    for item in parsed:
        if not isinstance(item, dict):
            continue
        kind_raw = str(item.get("kind") or "").strip().lower()
        if kind_raw not in TRIGGER_KINDS:
            continue
        enabled = _as_bool(item.get("enabled"), True)
        normalized: dict[str, Any] | None
        if kind_raw == TRIGGER_KIND_MANUAL:
            normalized = {"kind": TRIGGER_KIND_MANUAL, "enabled": enabled}
        elif kind_raw == TRIGGER_KIND_SCHEDULE:
            normalized = _normalize_schedule_trigger(item, enabled=enabled)
        else:
            normalized = _normalize_status_change_trigger(item, enabled=enabled)
        if not normalized:
            continue
        key = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(normalized)
    return out


def first_enabled_schedule_trigger(triggers: Any) -> tuple[int, dict[str, Any]] | tuple[None, None]:
    normalized = normalize_execution_triggers(triggers)
    for index, trigger in enumerate(normalized):
        if str(trigger.get("kind") or "") != TRIGGER_KIND_SCHEDULE:
            continue
        if not _as_bool(trigger.get("enabled"), True):
            continue
        return index, trigger
    return None, None


def has_enabled_schedule_trigger(triggers: Any) -> bool:
    index, _trigger = first_enabled_schedule_trigger(triggers)
    return index is not None


def parse_schedule_due_at(trigger: dict[str, Any] | None) -> datetime | None:
    if not isinstance(trigger, dict):
        return None
    raw = _normalize_string(trigger.get("scheduled_at_utc"))
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def schedule_trigger_matches_status(*, trigger: dict[str, Any] | None, status: str | None) -> bool:
    normalized_status = _normalize_string(status)
    if not normalized_status:
        return False
    run_on_statuses = normalize_schedule_run_on_statuses(
        trigger.get("run_on_statuses") if isinstance(trigger, dict) else None
    )
    allowed = {item.casefold() for item in run_on_statuses}
    return normalized_status.casefold() in allowed


def build_legacy_schedule_trigger(
    *,
    scheduled_at_utc: str | None,
    schedule_timezone: str | None = None,
    recurring_rule: str | None = None,
    run_on_statuses: Any = None,
) -> dict[str, Any] | None:
    normalized_scheduled_at_utc = _normalize_string(scheduled_at_utc)
    if not normalized_scheduled_at_utc:
        return None
    trigger: dict[str, Any] = {
        "kind": TRIGGER_KIND_SCHEDULE,
        "enabled": True,
        "scheduled_at_utc": normalized_scheduled_at_utc,
    }
    normalized_timezone = _normalize_string(schedule_timezone)
    if normalized_timezone:
        trigger["schedule_timezone"] = normalized_timezone
    normalized_rule = _normalize_string(recurring_rule)
    if normalized_rule:
        trigger["recurring_rule"] = normalized_rule
    trigger["run_on_statuses"] = normalize_schedule_run_on_statuses(run_on_statuses)
    return trigger


def derive_legacy_schedule_fields(*, instruction: str | None, execution_triggers: Any) -> dict[str, Any]:
    _idx, trigger = first_enabled_schedule_trigger(execution_triggers)
    if not trigger:
        return {
            "task_type": "manual",
            "scheduled_instruction": None,
            "scheduled_at_utc": None,
            "schedule_timezone": None,
            "recurring_rule": None,
        }
    return {
        "task_type": "scheduled_instruction",
        "scheduled_instruction": _normalize_string(instruction),
        "scheduled_at_utc": _normalize_string(trigger.get("scheduled_at_utc")),
        "schedule_timezone": _normalize_string(trigger.get("schedule_timezone")),
        "recurring_rule": _normalize_string(trigger.get("recurring_rule")),
    }


def rearm_first_schedule_trigger(
    *,
    execution_triggers: Any,
    now_utc: datetime,
) -> tuple[list[dict[str, Any]], str | None]:
    normalized = normalize_execution_triggers(execution_triggers)
    idx, trigger = first_enabled_schedule_trigger(normalized)
    if idx is None or trigger is None:
        return normalized, None
    recurring_rule = _normalize_string(trigger.get("recurring_rule"))
    if not recurring_rule:
        return normalized, None
    interval = parse_recurring_rule(recurring_rule)
    due_at = parse_schedule_due_at(trigger)
    if interval is None or due_at is None:
        return normalized, None
    next_due = next_scheduled_at_utc(
        base_scheduled_at_utc=due_at,
        now_utc=now_utc,
        interval=interval,
    )
    updated = dict(trigger)
    updated["scheduled_at_utc"] = next_due.isoformat()
    normalized[idx] = updated
    return normalized, updated["scheduled_at_utc"]


def status_transition_matches(
    *,
    from_status: str | None,
    to_status: str | None,
    from_statuses: Any,
    to_statuses: Any,
) -> bool:
    normalized_to = _normalize_string(to_status)
    if not normalized_to:
        return False
    if _normalize_string(from_status) and _normalize_string(from_status) == normalized_to:
        return False

    normalized_from_list = _normalize_string_list(from_statuses)
    normalized_to_list = _normalize_string_list(to_statuses)
    if normalized_from_list:
        if not from_status:
            return False
        if str(from_status).casefold() not in {value.casefold() for value in normalized_from_list}:
            return False
    if normalized_to_list:
        if normalized_to.casefold() not in {value.casefold() for value in normalized_to_list}:
            return False
    return True


def selector_matches_task(*, task_state: dict[str, Any], selector: Any) -> bool:
    normalized_selector = _normalize_status_selector(selector)
    if not normalized_selector:
        return True
    task_id = _normalize_string(task_state.get("id"))
    task_project_id = _normalize_string(task_state.get("project_id"))
    task_specification_id = _normalize_string(task_state.get("specification_id"))
    task_assignee_id = _normalize_string(task_state.get("assignee_id"))
    task_labels = _normalize_string_list(task_state.get("labels"))

    selector_task_ids = normalized_selector.get("task_ids") or []
    if selector_task_ids and task_id not in selector_task_ids:
        return False
    selector_project_id = normalized_selector.get("project_id")
    if selector_project_id and selector_project_id != task_project_id:
        return False
    selector_specification_id = normalized_selector.get("specification_id")
    if selector_specification_id and selector_specification_id != task_specification_id:
        return False
    selector_assignee_id = normalized_selector.get("assignee_id")
    if selector_assignee_id and selector_assignee_id != task_assignee_id:
        return False
    selector_labels_any = normalized_selector.get("labels_any") or []
    if selector_labels_any:
        task_label_keys = {value.casefold() for value in task_labels}
        if not any(label.casefold() in task_label_keys for label in selector_labels_any):
            return False
    return True
