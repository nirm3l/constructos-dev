from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from features.tasks.domain import (
    EVENT_AUTOMATION_REQUESTED as TASK_EVENT_AUTOMATION_REQUESTED,
    EVENT_COMPLETED as TASK_EVENT_COMPLETED,
    EVENT_REOPENED as TASK_EVENT_REOPENED,
    EVENT_REORDERED as TASK_EVENT_REORDERED,
    EVENT_UPDATED as TASK_EVENT_UPDATED,
)

from .contracts import EventEnvelope
from .eventing_rebuild import rebuild_state
from .models import Task
from .serializers import to_iso_utc
from .settings import AGENT_SYSTEM_USER_ID
from .task_automation import (
    STATUS_MATCH_ALL,
    STATUS_SCOPE_EXTERNAL,
    STATUS_SCOPE_SELF,
    TRIGGER_KIND_STATUS_CHANGE,
    normalize_execution_triggers,
    selector_matches_task,
    status_transition_matches,
)

_STATUS_TRANSITION_EVENTS = {
    TASK_EVENT_UPDATED,
    TASK_EVENT_REORDERED,
    TASK_EVENT_COMPLETED,
    TASK_EVENT_REOPENED,
}
_STATUS_CHANGE_AUTOMATION_ACTIONS = {
    "automation",
    "execute_instruction",
    "queue",
    "queue_automation",
    "queue_instruction",
    "request_automation",
    "request_instruction",
    "run",
    "run_automation",
    "run_instruction",
    "run_task_instruction",
    "start_automation",
    "start_instruction",
    "trigger_automation",
    "trigger_instruction",
}


def _normalize_optional_id(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_status(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_nonnegative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 0
    return max(0, parsed)


def _parse_task_labels(raw_labels: str | None) -> list[str]:
    if not raw_labels:
        return []
    try:
        value = json.loads(raw_labels)
    except Exception:
        return []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        label = str(item or "").strip()
        if label:
            out.append(label)
    return out


def _task_state_from_row(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "project_id": task.project_id,
        "specification_id": task.specification_id,
        "assignee_id": task.assignee_id,
        "labels": _parse_task_labels(task.labels),
        "status": task.status,
    }


def _status_transition_for_event(env: EventEnvelope) -> tuple[str | None, str | None]:
    payload = dict(env.payload or {})
    from_status = _normalize_status(payload.get("from_status"))
    to_status = _normalize_status(payload.get("to_status"))

    if env.event_type == TASK_EVENT_COMPLETED:
        to_status = to_status or "Done"
    elif env.event_type == TASK_EVENT_REOPENED:
        to_status = to_status or _normalize_status(payload.get("status")) or "To do"
    elif env.event_type in {TASK_EVENT_UPDATED, TASK_EVENT_REORDERED}:
        to_status = to_status or _normalize_status(payload.get("status"))

    return from_status, to_status


def _all_selector_tasks_match_status(
    *,
    tasks_for_workspace: list[dict[str, Any]],
    source_task_state: dict[str, Any],
    selector: Any,
    to_statuses: Any,
) -> bool:
    selected = [
        task_state
        for task_state in tasks_for_workspace
        if selector_matches_task(task_state=task_state, selector=selector)
    ]
    if not selected:
        return False
    source_id = _normalize_optional_id(source_task_state.get("id"))
    if source_id and source_id not in {_normalize_optional_id(item.get("id")) for item in selected}:
        return False

    allowed_statuses = {
        str(status).strip().casefold()
        for status in (to_statuses or [])
        if str(status).strip()
    }
    if not allowed_statuses:
        return False
    return all(str(item.get("status") or "").strip().casefold() in allowed_statuses for item in selected)


def _normalize_status_change_action(raw: Any) -> str | None:
    if isinstance(raw, dict):
        return _normalize_status(raw.get("type") or raw.get("action"))
    return _normalize_status(raw)


def _extract_status_change_target_task_ids(trigger: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def _append(value: Any) -> None:
        normalized = _normalize_optional_id(value)
        if not normalized:
            return
        key = normalized.casefold()
        if key in seen:
            return
        seen.add(key)
        out.append(normalized)

    _append(trigger.get("target_task_id"))
    raw_ids = trigger.get("target_task_ids")
    if isinstance(raw_ids, list):
        for item in raw_ids:
            _append(item)
    action = trigger.get("action")
    if isinstance(action, dict):
        _append(action.get("target_task_id"))
        raw_action_ids = action.get("target_task_ids")
        if isinstance(raw_action_ids, list):
            for item in raw_action_ids:
                _append(item)
    return out


def _is_cross_task_automation_action(action: str | None) -> bool:
    if action is None:
        return True
    return action.casefold() in _STATUS_CHANGE_AUTOMATION_ACTIONS


def _trigger_matches_status_change_event(
    *,
    trigger: dict[str, Any],
    source_task_state: dict[str, Any],
    from_status: str | None,
    to_status: str | None,
    workspace_tasks_fn: Callable[[str], list[dict[str, Any]]],
) -> bool:
    if str(trigger.get("kind") or "") != TRIGGER_KIND_STATUS_CHANGE:
        return False
    if not bool(trigger.get("enabled", True)):
        return False
    if not status_transition_matches(
        from_status=from_status,
        to_status=to_status,
        from_statuses=trigger.get("from_statuses"),
        to_statuses=trigger.get("to_statuses"),
    ):
        return False
    scope = str(trigger.get("scope") or STATUS_SCOPE_SELF).strip().lower()
    if scope != STATUS_SCOPE_EXTERNAL:
        return True
    selector = trigger.get("selector")
    if not selector_matches_task(task_state=source_task_state, selector=selector):
        return False
    match_mode = str(trigger.get("match_mode") or "").strip().lower()
    if match_mode != STATUS_MATCH_ALL:
        return True
    workspace_id = _normalize_optional_id(source_task_state.get("workspace_id"))
    if not workspace_id:
        return False
    tasks_for_workspace = workspace_tasks_fn(workspace_id)
    return _all_selector_tasks_match_status(
        tasks_for_workspace=tasks_for_workspace,
        source_task_state=source_task_state,
        selector=selector,
        to_statuses=trigger.get("to_statuses"),
    )


def emit_task_automation_triggers_for_event(
    db: Session,
    env: EventEnvelope,
    *,
    append_event_fn: Callable[..., Any],
) -> None:
    if env.aggregate_type != "Task" or env.event_type not in _STATUS_TRANSITION_EVENTS:
        return

    source_task_id = _normalize_optional_id(env.aggregate_id)
    if not source_task_id:
        return

    from_status, to_status = _status_transition_for_event(env)
    if not to_status:
        return
    if from_status and from_status == to_status:
        return

    source_task = db.get(Task, source_task_id)
    if source_task is None or source_task.is_deleted:
        return
    source_task_state = _task_state_from_row(source_task)

    now_iso = to_iso_utc(datetime.now(timezone.utc))
    workspace_task_cache: dict[str, list[dict[str, Any]]] = {}
    requested_task_ids: set[str] = set()

    def _workspace_tasks(workspace_id: str) -> list[dict[str, Any]]:
        if workspace_id not in workspace_task_cache:
            rows = db.execute(
                select(Task).where(
                    Task.workspace_id == workspace_id,
                    Task.is_deleted == False,
                )
            ).scalars().all()
            workspace_task_cache[workspace_id] = [_task_state_from_row(row) for row in rows]
        return workspace_task_cache[workspace_id]

    def _queue_automation_for_task(
        *,
        task_row: Task,
        trigger_task_id: str,
        trigger_from_status: str | None,
        trigger_to_status: str | None,
        triggered_at: str,
    ) -> bool:
        task_id = _normalize_optional_id(task_row.id)
        if not task_id or task_id in requested_task_ids:
            return False
        if task_row.is_deleted:
            return False
        if task_row.workspace_id != source_task.workspace_id:
            return False

        task_instruction = _normalize_status(task_row.instruction or task_row.scheduled_instruction)
        if not task_instruction:
            return False

        task_state, _ = rebuild_state(db, "Task", task_id)
        workspace_id = _normalize_optional_id(task_state.get("workspace_id")) or task_row.workspace_id
        if not workspace_id:
            return False
        project_id = _normalize_optional_id(task_state.get("project_id")) or task_row.project_id
        effective_instruction = _normalize_status(
            task_state.get("instruction")
            or task_state.get("scheduled_instruction")
            or task_instruction
        )
        if not effective_instruction:
            return False

        if str(task_state.get("automation_state") or "idle") in {"queued", "running"}:
            pending_requests = _normalize_nonnegative_int(task_state.get("automation_pending_requests"))
            append_event_fn(
                db,
                aggregate_type="Task",
                aggregate_id=task_id,
                event_type=TASK_EVENT_UPDATED,
                payload={
                    "automation_pending_requests": pending_requests + 1,
                    "last_requested_instruction": effective_instruction,
                    "last_requested_source": "status_change",
                    "last_requested_trigger_task_id": trigger_task_id,
                    "last_requested_from_status": trigger_from_status,
                    "last_requested_to_status": trigger_to_status,
                    "last_requested_triggered_at": triggered_at,
                },
                metadata={
                    "actor_id": AGENT_SYSTEM_USER_ID,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": task_id,
                    "trigger_task_id": trigger_task_id,
                    "trigger_from_status": trigger_from_status,
                    "trigger_to_status": trigger_to_status,
                    "triggered_at": triggered_at,
                },
            )
            return False

        append_event_fn(
            db,
            aggregate_type="Task",
            aggregate_id=task_id,
            event_type=TASK_EVENT_AUTOMATION_REQUESTED,
            payload={
                "requested_at": now_iso,
                "instruction": effective_instruction,
                "source": "status_change",
                "trigger_task_id": trigger_task_id,
                "from_status": trigger_from_status,
                "to_status": trigger_to_status,
                "triggered_at": triggered_at,
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": task_id,
                "trigger_task_id": trigger_task_id,
                "trigger_from_status": trigger_from_status,
                "trigger_to_status": trigger_to_status,
                "triggered_at": triggered_at,
            },
        )
        requested_task_ids.add(task_id)
        return True

    source_triggers = normalize_execution_triggers(source_task.execution_triggers)
    for trigger in source_triggers:
        if not _trigger_matches_status_change_event(
            trigger=trigger,
            source_task_state=source_task_state,
            from_status=from_status,
            to_status=to_status,
            workspace_tasks_fn=_workspace_tasks,
        ):
            continue
        action = _normalize_status_change_action(trigger.get("action"))
        target_task_ids = _extract_status_change_target_task_ids(trigger)
        if not target_task_ids or not _is_cross_task_automation_action(action):
            continue
        for target_task_id in target_task_ids:
            if target_task_id == source_task_id:
                continue
            target_task = db.get(Task, target_task_id)
            if target_task is None:
                continue
            _queue_automation_for_task(
                task_row=target_task,
                trigger_task_id=source_task_id,
                trigger_from_status=from_status,
                trigger_to_status=to_status,
                triggered_at=now_iso,
            )

    candidate_rows = db.execute(
        select(Task).where(
            Task.is_deleted == False,
            Task.execution_triggers.ilike("%status_change%"),
        )
    ).scalars().all()
    if not candidate_rows:
        return

    for candidate in candidate_rows:
        candidate_task_id = _normalize_optional_id(candidate.id)
        if not candidate_task_id or candidate_task_id in requested_task_ids:
            continue
        if candidate.workspace_id != source_task.workspace_id:
            continue

        triggers = normalize_execution_triggers(candidate.execution_triggers)
        matched = False
        for trigger in triggers:
            trigger_target_task_ids = _extract_status_change_target_task_ids(trigger)
            if trigger_target_task_ids:
                if candidate_task_id not in set(trigger_target_task_ids):
                    # Explicit target mappings should not fire for non-target tasks.
                    continue
                action = _normalize_status_change_action(trigger.get("action"))
                if not _is_cross_task_automation_action(action):
                    continue
            scope = str(trigger.get("scope") or STATUS_SCOPE_SELF).strip().lower()
            if scope == STATUS_SCOPE_SELF and candidate_task_id != source_task_id:
                continue
            if scope == STATUS_SCOPE_EXTERNAL and candidate_task_id == source_task_id:
                continue
            if not _trigger_matches_status_change_event(
                trigger=trigger,
                source_task_state=source_task_state,
                from_status=from_status,
                to_status=to_status,
                workspace_tasks_fn=_workspace_tasks,
            ):
                continue

            matched = True
            break

        if not matched:
            continue
        _queue_automation_for_task(
            task_row=candidate,
            trigger_task_id=source_task_id,
            trigger_from_status=from_status,
            trigger_to_status=to_status,
            triggered_at=now_iso,
        )
