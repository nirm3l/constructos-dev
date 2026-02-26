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


def _normalize_optional_id(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_status(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


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


def emit_task_automation_triggers_for_event(
    db: Session,
    env: EventEnvelope,
    *,
    append_event_fn: Callable[..., Any],
) -> None:
    if env.aggregate_type != "Task" or env.event_type not in _STATUS_TRANSITION_EVENTS:
        return

    actor_id = _normalize_optional_id((env.metadata or {}).get("actor_id"))
    if actor_id == AGENT_SYSTEM_USER_ID:
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

    candidate_rows = db.execute(
        select(Task).where(
            Task.is_deleted == False,
            Task.execution_triggers.ilike("%status_change%"),
        )
    ).scalars().all()
    if not candidate_rows:
        return

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

    for candidate in candidate_rows:
        candidate_task_id = _normalize_optional_id(candidate.id)
        if not candidate_task_id or candidate_task_id in requested_task_ids:
            continue
        if candidate.workspace_id != source_task.workspace_id:
            continue

        candidate_instruction = _normalize_status(candidate.instruction or candidate.scheduled_instruction)
        if not candidate_instruction:
            continue

        triggers = normalize_execution_triggers(candidate.execution_triggers)
        matched = False
        for trigger in triggers:
            if str(trigger.get("kind") or "") != TRIGGER_KIND_STATUS_CHANGE:
                continue
            if not bool(trigger.get("enabled", True)):
                continue

            scope = str(trigger.get("scope") or STATUS_SCOPE_SELF).strip().lower()
            if scope == STATUS_SCOPE_SELF and candidate_task_id != source_task_id:
                continue
            if scope == STATUS_SCOPE_EXTERNAL and candidate_task_id == source_task_id:
                continue

            if not status_transition_matches(
                from_status=from_status,
                to_status=to_status,
                from_statuses=trigger.get("from_statuses"),
                to_statuses=trigger.get("to_statuses"),
            ):
                continue

            selector = trigger.get("selector")
            if scope == STATUS_SCOPE_EXTERNAL and not selector_matches_task(task_state=source_task_state, selector=selector):
                continue

            match_mode = str(trigger.get("match_mode") or "").strip().lower()
            if scope == STATUS_SCOPE_EXTERNAL and match_mode == STATUS_MATCH_ALL:
                tasks_for_workspace = _workspace_tasks(candidate.workspace_id)
                if not _all_selector_tasks_match_status(
                    tasks_for_workspace=tasks_for_workspace,
                    source_task_state=source_task_state,
                    selector=selector,
                    to_statuses=trigger.get("to_statuses"),
                ):
                    continue

            matched = True
            break

        if not matched:
            continue

        candidate_state, _ = rebuild_state(db, "Task", candidate_task_id)
        if str(candidate_state.get("automation_state") or "idle") in {"queued", "running"}:
            continue

        workspace_id = _normalize_optional_id(candidate_state.get("workspace_id")) or candidate.workspace_id
        if not workspace_id:
            continue
        project_id = _normalize_optional_id(candidate_state.get("project_id")) or candidate.project_id
        effective_instruction = _normalize_status(
            candidate_state.get("instruction")
            or candidate_state.get("scheduled_instruction")
            or candidate_instruction
        )
        if not effective_instruction:
            continue

        append_event_fn(
            db,
            aggregate_type="Task",
            aggregate_id=candidate_task_id,
            event_type=TASK_EVENT_AUTOMATION_REQUESTED,
            payload={
                "requested_at": now_iso,
                "instruction": effective_instruction,
                "source": "status_change",
                "trigger_task_id": source_task_id,
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": candidate_task_id,
                "trigger_task_id": source_task_id,
            },
        )
        requested_task_ids.add(candidate_task_id)
