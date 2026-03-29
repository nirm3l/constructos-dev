from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from features.tasks.domain import (
    EVENT_AUTOMATION_COMPLETED,
    EVENT_AUTOMATION_FAILED,
    EVENT_AUTOMATION_REQUESTED,
    EVENT_COMMENT_ADDED,
)
from plugins.team_mode.runtime_context import TeamModeProjectRuntimeContext
from plugins.team_mode.semantics import semantic_status_key
from shared.eventing_rebuild import load_events_after
from shared.models import ChatMessage, ChatSession, Project, Task
from shared.task_automation import TRIGGER_KIND_STATUS_CHANGE, normalize_execution_triggers
from shared.task_relationships import normalize_task_relationships


def _build_runtime_event_response_markdown(
    *,
    latest_comment_body: str | None,
    terminal_status: str | None,
    terminal_summary: str | None,
    terminal_error: str | None,
) -> str | None:
    if latest_comment_body:
        return latest_comment_body
    normalized_summary = str(terminal_summary or "").strip() or None
    normalized_error = str(terminal_error or "").strip() or None
    if terminal_status == "failed" and normalized_error:
        if normalized_summary and normalized_summary != normalized_error:
            return (
                "**Error**\n\n"
                f"```text\n{normalized_error}\n```\n\n"
                "**Summary**\n\n"
                f"{normalized_summary}"
            )
        return f"```text\n{normalized_error}\n```"
    return normalized_summary or normalized_error or None


def _compact_classifier_payload(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    out: dict[str, Any] = {}
    for key in (
        "execution_intent",
        "execution_kickoff_intent",
        "project_creation_intent",
        "workflow_scope",
        "execution_mode",
        "task_completion_requested",
        "reason",
    ):
        current = value.get(key)
        if isinstance(current, str):
            normalized = current.strip()
            if normalized:
                out[key] = normalized
        elif isinstance(current, bool):
            out[key] = current
    return out or None


def _load_origin_chat_debug(
    *,
    db: Session,
    workspace_id: str,
    project_id: str,
    chat_session_id: str | None,
    requested_at: str | None,
) -> dict[str, Any]:
    normalized_session_id = str(chat_session_id or "").strip()
    if not normalized_session_id:
        return {}
    session = db.execute(
        select(ChatSession).where(
            ChatSession.workspace_id == workspace_id,
            ChatSession.project_id == project_id,
            ChatSession.session_key == normalized_session_id,
            ChatSession.is_archived == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if session is None:
        return {"origin_chat_session_id": normalized_session_id}

    requested_at_text = str(requested_at or "").strip()
    message_base_query = select(ChatMessage).where(
        ChatMessage.session_id == session.id,
        ChatMessage.role == "user",
        ChatMessage.is_deleted == False,  # noqa: E712
    )
    message_query = message_base_query
    if requested_at_text:
        requested_dt = _parse_iso_datetime(requested_at_text)
        if requested_dt is not None:
            message_query = message_query.where(ChatMessage.turn_created_at <= requested_dt)
    message = db.execute(
        message_query.order_by(
            ChatMessage.turn_created_at.desc(),
            ChatMessage.order_index.desc(),
        )
    ).scalars().first()
    if message is None and message_query is not message_base_query:
        message = db.execute(
            message_base_query.order_by(
                ChatMessage.turn_created_at.desc(),
                ChatMessage.order_index.desc(),
            )
        ).scalars().first()
    if message is None:
        return {"origin_chat_session_id": normalized_session_id}
    try:
        usage_payload = json.loads(message.usage_json or "{}")
    except Exception:
        usage_payload = {}
    intent_flags = usage_payload.get("intent_flags") if isinstance(usage_payload, dict) else None
    return {
        "origin_chat_session_id": normalized_session_id,
        "origin_prompt_markdown": str(message.content or "").strip() or None,
        "origin_classifier": _compact_classifier_payload(intent_flags if isinstance(intent_flags, dict) else None),
        "origin_prompt_at": message.turn_created_at.isoformat() if message.turn_created_at else None,
    }


def _parse_iso_datetime(value: str | None) -> datetime | None:
    text_value = str(value or "").strip()
    if not text_value:
        return None
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def get_project_task_dependency_event_detail(
    *,
    db: Session,
    project_id: str,
    target_task_id: str,
    source_task_id: str,
    source: str,
    requested_at: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any] | None:
    normalized_project_id = str(project_id or "").strip()
    normalized_target_task_id = str(target_task_id or "").strip()
    normalized_source_task_id = str(source_task_id or "").strip()
    normalized_source = str(source or "").strip()
    normalized_requested_at = str(requested_at or "").strip() or None
    normalized_correlation_id = str(correlation_id or "").strip() or None
    if not normalized_project_id or not normalized_target_task_id or not normalized_source_task_id or not normalized_source:
        return None

    target_task = db.get(Task, normalized_target_task_id)
    source_task = db.get(Task, normalized_source_task_id)
    if (
        target_task is None
        or source_task is None
        or bool(target_task.is_deleted)
        or bool(source_task.is_deleted)
        or str(target_task.project_id or "").strip() != normalized_project_id
        or str(source_task.project_id or "").strip() != normalized_project_id
    ):
        return None

    events = load_events_after(db, "Task", normalized_target_task_id, 0)
    request_candidates: list[tuple[int, int, Any]] = []
    for index, event in enumerate(events):
        if str(event.event_type or "").strip() != EVENT_AUTOMATION_REQUESTED:
            continue
        payload = dict(event.payload or {})
        if str(payload.get("source") or "").strip() != normalized_source:
            continue
        if str(payload.get("source_task_id") or "").strip() != normalized_source_task_id:
            continue
        payload_correlation = str(payload.get("correlation_id") or "").strip() or None
        payload_requested_at = _max_iso_timestamp(
            [
                payload.get("requested_at"),
                payload.get("triggered_at"),
                payload.get("lead_handoff_at"),
            ]
        )
        score = 0
        if normalized_correlation_id and payload_correlation == normalized_correlation_id:
            score += 4
        if normalized_requested_at and payload_requested_at == normalized_requested_at:
            score += 3
        if normalized_correlation_id is None and normalized_requested_at is None:
            score += 1
        request_candidates.append((score, index, event))

    if not request_candidates:
        return None

    request_candidates.sort(
        key=lambda item: (
            item[0],
            str(_max_iso_timestamp(
                [
                    dict(item[2].payload or {}).get("requested_at"),
                    dict(item[2].payload or {}).get("triggered_at"),
                    dict(item[2].payload or {}).get("lead_handoff_at"),
                ]
            ) or ""),
            int(getattr(item[2], "version", 0) or 0),
        ),
        reverse=True,
    )
    _score, request_index, request_event = request_candidates[0]
    request_payload = dict(request_event.payload or {})

    next_request_index = len(events)
    for later_index in range(request_index + 1, len(events)):
        if str(events[later_index].event_type or "").strip() == EVENT_AUTOMATION_REQUESTED:
            next_request_index = later_index
            break

    terminal_status: str | None = None
    terminal_at: str | None = None
    terminal_summary: str | None = None
    terminal_error: str | None = None
    latest_comment_body: str | None = None
    latest_comment_at: str | None = None
    for event in events[request_index + 1:next_request_index]:
        event_type = str(event.event_type or "").strip()
        payload = dict(event.payload or {})
        if event_type == EVENT_COMMENT_ADDED:
            latest_comment_body = str(payload.get("body") or "").strip() or None
            latest_comment_at = _max_iso_timestamp([payload.get("created_at"), payload.get("commented_at")])
            continue
        if event_type == EVENT_AUTOMATION_COMPLETED and terminal_status is None:
            terminal_status = "completed"
            terminal_at = _max_iso_timestamp([payload.get("completed_at")])
            terminal_summary = str(payload.get("summary") or "").strip() or None
            continue
        if event_type == EVENT_AUTOMATION_FAILED and terminal_status is None:
            terminal_status = "failed"
            terminal_at = _max_iso_timestamp([payload.get("failed_at")])
            terminal_summary = str(payload.get("summary") or "").strip() or None
            terminal_error = str(payload.get("error") or "").strip() or None

    response_markdown = _build_runtime_event_response_markdown(
        latest_comment_body=latest_comment_body,
        terminal_status=terminal_status,
        terminal_summary=terminal_summary,
        terminal_error=terminal_error,
    )
    request_markdown = str(request_payload.get("instruction") or "").strip() or None
    runtime_classifier = _compact_classifier_payload(
        {
            "execution_intent": request_payload.get("execution_intent"),
            "execution_kickoff_intent": request_payload.get("execution_kickoff_intent"),
            "project_creation_intent": request_payload.get("project_creation_intent"),
            "workflow_scope": request_payload.get("workflow_scope"),
            "execution_mode": request_payload.get("execution_mode"),
            "task_completion_requested": request_payload.get("task_completion_requested"),
            "reason": request_payload.get("classifier_reason"),
        }
    )
    origin_debug = _load_origin_chat_debug(
        db=db,
        workspace_id=str(target_task.workspace_id or ""),
        project_id=normalized_project_id,
        chat_session_id=str(request_payload.get("chat_session_id") or "").strip() or None,
        requested_at=_max_iso_timestamp(
            [
                request_payload.get("requested_at"),
                request_payload.get("triggered_at"),
                request_payload.get("lead_handoff_at"),
            ]
        ),
    )
    return {
        "project_id": normalized_project_id,
        "target_task_id": normalized_target_task_id,
        "target_task_title": str(target_task.title or normalized_target_task_id),
        "source_task_id": normalized_source_task_id,
        "source_task_title": str(source_task.title or normalized_source_task_id),
        "source": normalized_source,
        "requested_at": _max_iso_timestamp(
            [
                request_payload.get("requested_at"),
                request_payload.get("triggered_at"),
                request_payload.get("lead_handoff_at"),
            ]
        ),
        "correlation_id": str(request_payload.get("correlation_id") or "").strip() or None,
        "trigger_link": str(request_payload.get("trigger_link") or "").strip() or None,
        "reason": str(request_payload.get("reason") or "").strip() or None,
        "request_markdown": request_markdown,
        "runtime_classifier": runtime_classifier,
        "response_markdown": response_markdown,
        "response_status": terminal_status,
        "response_at": terminal_at,
        "response_summary": terminal_summary,
        "response_error": terminal_error,
        "response_comment_body": latest_comment_body,
        "response_comment_at": latest_comment_at,
        **origin_debug,
    }


def get_project_task_dependency_graph(
    *,
    db: Session,
    project_id: str,
    limit_nodes: int = 240,
    limit_edges: int = 1600,
) -> dict[str, Any]:
    safe_nodes = max(8, min(int(limit_nodes or 240), 600))
    safe_edges = max(8, min(int(limit_edges or 1600), 4000))

    project = db.get(Project, project_id)
    if project is None or bool(project.is_deleted):
        return {
            "project_id": project_id,
            "project_name": "",
            "node_count": 0,
            "edge_count": 0,
            "counts": _empty_counts(),
            "relationship_counts": {},
            "runtime_source_counts": {},
            "nodes": [],
            "edges": [],
        }

    task_rows = (
        db.execute(
            select(Task)
            .where(
                Task.project_id == project_id,
                Task.is_deleted == False,  # noqa: E712
                Task.archived == False,  # noqa: E712
            )
            .order_by(Task.created_at.asc(), Task.id.asc())
            .limit(safe_nodes)
        )
        .scalars()
        .all()
    )
    if not task_rows:
        return {
            "project_id": project_id,
            "project_name": str(project.name or ""),
            "node_count": 0,
            "edge_count": 0,
            "counts": _empty_counts(),
            "relationship_counts": {},
            "runtime_source_counts": {},
            "nodes": [],
            "edges": [],
        }

    runtime_context = TeamModeProjectRuntimeContext(
        db=db,
        workspace_id=str(project.workspace_id or ""),
        project_id=project_id,
    )

    task_ids = [str(task.id or "").strip() for task in task_rows if str(task.id or "").strip()]
    task_id_set = set(task_ids)
    states_by_task_id: dict[str, dict[str, Any]] = {}
    nodes_by_task_id: dict[str, dict[str, Any]] = {}

    for task in task_rows:
        task_id = str(task.id or "").strip()
        if not task_id:
            continue
        entry = runtime_context.task_entry(task_id)
        state = dict(entry.state) if entry is not None else runtime_context.task_state(task_id)
        states_by_task_id[task_id] = state
        role = (
            str(entry.workflow_role or "").strip()
            if entry is not None
            else runtime_context.derive_workflow_role(
                task_like={
                    "id": task_id,
                    "assignee_id": str(state.get("assignee_id") or task.assignee_id or "").strip(),
                    "assigned_agent_code": str(state.get("assigned_agent_code") or task.assigned_agent_code or "").strip(),
                    "labels": state.get("labels", task.labels),
                    "status": str(state.get("status") or task.status or "").strip(),
                }
            )
        )
        last_activity_at = _max_iso_timestamp(
            [
                state.get("last_requested_triggered_at"),
                state.get("last_agent_run_at"),
                state.get("last_schedule_run_at"),
                state.get("last_lead_handoff_at"),
                state.get("completed_at"),
                task.updated_at.isoformat() if getattr(task, "updated_at", None) else None,
                task.created_at.isoformat() if getattr(task, "created_at", None) else None,
            ]
        )
        nodes_by_task_id[task_id] = {
            "entity_type": "Task",
            "entity_id": task_id,
            "title": str(task.title or task_id),
            "status": str(state.get("status") or task.status or "").strip(),
            "priority": str(state.get("priority") or task.priority or "").strip(),
            "automation_state": str(state.get("automation_state") or "idle").strip(),
            "role": str(role or "").strip() or "Task",
            "assigned_agent_code": str(state.get("assigned_agent_code") or task.assigned_agent_code or "").strip() or None,
            "assignee_id": str(state.get("assignee_id") or task.assignee_id or "").strip() or None,
            "specification_id": str(state.get("specification_id") or task.specification_id or "").strip() or None,
            "team_mode_phase": str(state.get("team_mode_phase") or "").strip() or None,
            "team_mode_blocking_gate": str(state.get("team_mode_blocking_gate") or "").strip() or None,
            "last_requested_source": str(state.get("last_requested_source") or "").strip() or None,
            "last_requested_source_task_id": str(state.get("last_requested_source_task_id") or "").strip() or None,
            "last_requested_triggered_at": str(state.get("last_requested_triggered_at") or "").strip() or None,
            "last_activity_at": last_activity_at,
            "inbound_count": 0,
            "outbound_count": 0,
            "runtime_inbound_count": 0,
            "runtime_outbound_count": 0,
            "structural_inbound_count": 0,
            "structural_outbound_count": 0,
            "status_trigger_inbound_count": 0,
            "status_trigger_outbound_count": 0,
        }

    edge_map: dict[tuple[str, str], dict[str, Any]] = {}

    def ensure_edge(source_task_id: str, target_task_id: str) -> dict[str, Any]:
        key = (source_task_id, target_task_id)
        existing = edge_map.get(key)
        if existing is not None:
            return existing
        edge = {
            "source_entity_id": source_task_id,
            "target_entity_id": target_task_id,
            "relationship": "TASK_DEPENDENCY",
            "structural": False,
            "trigger_dependency": False,
            "runtime_dependency": False,
            "active_runtime": False,
            "runtime_requests_total": 0,
            "lead_handoffs_total": 0,
            "latest_runtime_at": None,
            "latest_runtime_source": None,
            "relationship_kinds": [],
            "trigger_conditions": [],
            "runtime_sources": {},
            "channels": [],
            "runtime_events": [],
        }
        edge_map[key] = edge
        return edge

    for task in task_rows:
        task_id = str(task.id or "").strip()
        if not task_id:
            continue
        state = states_by_task_id.get(task_id) or {}
        task_relationships = normalize_task_relationships(state.get("task_relationships") or task.task_relationships)
        for relationship in task_relationships:
            _append_task_relationship_edges(
                edge_map=edge_map,
                ensure_edge=ensure_edge,
                task_id=task_id,
                relationship=relationship,
                task_id_set=task_id_set,
            )

        execution_triggers = normalize_execution_triggers(state.get("execution_triggers") or task.execution_triggers)
        for trigger in execution_triggers:
            _append_status_trigger_edges(
                edge_map=edge_map,
                ensure_edge=ensure_edge,
                task_id=task_id,
                trigger=trigger,
                task_id_set=task_id_set,
            )

    for task_id in task_ids:
        for event in load_events_after(db, "Task", task_id, 0):
            if str(event.event_type or "").strip() != EVENT_AUTOMATION_REQUESTED:
                continue
            payload = dict(event.payload or {})
            source_task_id = str(payload.get("source_task_id") or "").strip()
            if not source_task_id or source_task_id == task_id or source_task_id not in task_id_set:
                continue
            edge = ensure_edge(source_task_id, task_id)
            edge["runtime_dependency"] = True
            request_source = str(payload.get("source") or "runtime").strip() or "runtime"
            requested_at = _max_iso_timestamp(
                [
                    payload.get("requested_at"),
                    payload.get("triggered_at"),
                    payload.get("lead_handoff_at"),
                ]
            )
            edge["runtime_requests_total"] = int(edge.get("runtime_requests_total") or 0) + 1
            if request_source == "lead_handoff":
                edge["lead_handoffs_total"] = int(edge.get("lead_handoffs_total") or 0) + 1
            runtime_sources = dict(edge.get("runtime_sources") or {})
            runtime_sources[request_source] = int(runtime_sources.get(request_source) or 0) + 1
            edge["runtime_sources"] = runtime_sources
            if _iso_greater(requested_at, edge.get("latest_runtime_at")):
                edge["latest_runtime_at"] = requested_at
                edge["latest_runtime_source"] = request_source
            channel_key = f"runtime:{request_source}"
            _merge_channel(
                edge=edge,
                key=channel_key,
                payload={
                    "kind": "runtime_request",
                    "label": "lead handoff" if request_source == "lead_handoff" else request_source.replace("_", " "),
                    "source": request_source,
                    "count": 1,
                    "latest_at": requested_at,
                    "correlation_ids": _compact_unique([payload.get("correlation_id")]),
                    "active": False,
                },
            )
            _merge_runtime_event(
                edge=edge,
                payload={
                    "at": requested_at,
                    "source": request_source,
                    "reason": str(payload.get("reason") or "").strip() or None,
                    "trigger_link": str(payload.get("trigger_link") or "").strip() or None,
                    "correlation_id": str(payload.get("correlation_id") or "").strip() or None,
                    "active": False,
                },
            )

    for task_id, state in states_by_task_id.items():
        source_task_id = str(state.get("last_requested_source_task_id") or "").strip()
        if not source_task_id or source_task_id not in task_id_set or source_task_id == task_id:
            continue
        edge = ensure_edge(source_task_id, task_id)
        request_source = str(state.get("last_requested_source") or "").strip() or str(edge.get("latest_runtime_source") or "").strip() or "runtime"
        requested_at = _max_iso_timestamp(
            [
                state.get("last_requested_triggered_at"),
                state.get("last_lead_handoff_at"),
                state.get("last_agent_run_at"),
                state.get("completed_at"),
                state.get("last_schedule_run_at"),
            ]
        )
        edge["runtime_dependency"] = True
        edge["runtime_requests_total"] = max(1, int(edge.get("runtime_requests_total") or 0))
        if request_source == "lead_handoff":
            edge["lead_handoffs_total"] = max(1, int(edge.get("lead_handoffs_total") or 0))
        runtime_sources = dict(edge.get("runtime_sources") or {})
        runtime_sources[request_source] = max(1, int(runtime_sources.get(request_source) or 0))
        edge["runtime_sources"] = runtime_sources
        if _iso_greater(requested_at, edge.get("latest_runtime_at")):
            edge["latest_runtime_at"] = requested_at
            edge["latest_runtime_source"] = request_source
        _merge_channel(
            edge=edge,
            key=f"runtime:{request_source}",
            payload={
                "kind": "runtime_request",
                "label": "lead handoff" if request_source == "lead_handoff" else request_source.replace("_", " "),
                "source": request_source,
                "count": 1,
                "latest_at": requested_at,
                "correlation_ids": _compact_unique([state.get("last_requested_correlation_id")]),
                "active": True,
            },
        )
        _merge_runtime_event(
            edge=edge,
            payload={
                "at": requested_at,
                "source": request_source,
                "reason": str(state.get("last_requested_reason") or "").strip() or None,
                "trigger_link": str(state.get("last_requested_trigger_link") or "").strip() or None,
                "correlation_id": str(state.get("last_requested_correlation_id") or "").strip() or None,
                "active": True,
            },
        )
        edge["active_runtime"] = True
        for channel in edge.get("channels") or []:
            if not isinstance(channel, dict):
                continue
            if str(channel.get("kind") or "").strip() != "runtime_request":
                continue
            if str(channel.get("source") or "").strip() != request_source:
                continue
            channel["active"] = True

    edges = list(edge_map.values())
    edges.sort(
        key=lambda edge: (
            0 if bool(edge.get("active_runtime")) else 1,
            -int(edge.get("lead_handoffs_total") or 0),
            -int(edge.get("runtime_requests_total") or 0),
            0 if bool(edge.get("runtime_dependency")) else 1,
            0 if bool(edge.get("trigger_dependency")) else 1,
            0 if bool(edge.get("structural")) else 1,
            str(edge.get("latest_runtime_at") or ""),
            str(edge.get("source_entity_id") or ""),
            str(edge.get("target_entity_id") or ""),
        )
    )
    if len(edges) > safe_edges:
        edges = edges[:safe_edges]

    visible_task_ids: set[str] = set()
    relationship_counts: dict[str, int] = defaultdict(int)
    runtime_source_counts: dict[str, int] = defaultdict(int)
    counts = _empty_counts()
    counts["tasks"] = len(nodes_by_task_id)

    for edge in edges:
        source_task_id = str(edge.get("source_entity_id") or "").strip()
        target_task_id = str(edge.get("target_entity_id") or "").strip()
        if not source_task_id or not target_task_id:
            continue
        visible_task_ids.add(source_task_id)
        visible_task_ids.add(target_task_id)
        nodes_by_task_id[source_task_id]["outbound_count"] = int(nodes_by_task_id[source_task_id]["outbound_count"]) + 1
        nodes_by_task_id[target_task_id]["inbound_count"] = int(nodes_by_task_id[target_task_id]["inbound_count"]) + 1
        if bool(edge.get("structural")):
            counts["structural_edges"] = int(counts["structural_edges"]) + 1
            nodes_by_task_id[source_task_id]["structural_outbound_count"] = int(nodes_by_task_id[source_task_id]["structural_outbound_count"]) + 1
            nodes_by_task_id[target_task_id]["structural_inbound_count"] = int(nodes_by_task_id[target_task_id]["structural_inbound_count"]) + 1
        if bool(edge.get("trigger_dependency")):
            counts["status_trigger_edges"] = int(counts["status_trigger_edges"]) + 1
            nodes_by_task_id[source_task_id]["status_trigger_outbound_count"] = int(nodes_by_task_id[source_task_id]["status_trigger_outbound_count"]) + 1
            nodes_by_task_id[target_task_id]["status_trigger_inbound_count"] = int(nodes_by_task_id[target_task_id]["status_trigger_inbound_count"]) + 1
        if bool(edge.get("runtime_dependency")):
            counts["runtime_edges"] = int(counts["runtime_edges"]) + 1
            nodes_by_task_id[source_task_id]["runtime_outbound_count"] = int(nodes_by_task_id[source_task_id]["runtime_outbound_count"]) + 1
            nodes_by_task_id[target_task_id]["runtime_inbound_count"] = int(nodes_by_task_id[target_task_id]["runtime_inbound_count"]) + 1
            if bool(edge.get("active_runtime")):
                counts["active_runtime_edges"] = int(counts["active_runtime_edges"]) + 1
        for kind in edge.get("relationship_kinds") or []:
            relationship_counts[str(kind)] += 1
        for runtime_source, value in dict(edge.get("runtime_sources") or {}).items():
            runtime_source_counts[str(runtime_source)] += int(value or 0)

    for task_id, node in nodes_by_task_id.items():
        status = str(node.get("status") or "").strip()
        semantic_status = semantic_status_key(status=status)
        automation_state = str(node.get("automation_state") or "").strip().lower()
        if automation_state == "running":
            counts["running_tasks"] = int(counts["running_tasks"]) + 1
        elif automation_state == "queued":
            counts["queued_tasks"] = int(counts["queued_tasks"]) + 1
        if semantic_status == "blocked":
            counts["blocked_tasks"] = int(counts["blocked_tasks"]) + 1
        if semantic_status == "completed":
            counts["done_tasks"] = int(counts["done_tasks"]) + 1

    nodes = list(nodes_by_task_id.values())
    nodes.sort(
        key=lambda node: (
            _role_sort_key(str(node.get("role") or "")),
            _status_sort_key(str(node.get("status") or "")),
            str(node.get("title") or "").lower(),
        )
    )

    return {
        "project_id": project_id,
        "project_name": str(project.name or ""),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "counts": counts,
        "relationship_counts": dict(sorted(relationship_counts.items())),
        "runtime_source_counts": dict(sorted(runtime_source_counts.items())),
        "nodes": nodes,
        "edges": edges,
    }


def get_project_task_dependency_event_detail(
    *,
    db: Session,
    project_id: str,
    source_task_id: str,
    target_task_id: str,
    runtime_source: str,
    occurred_at: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if project is None or bool(project.is_deleted):
        return {"project_id": project_id, "found": False, "detail": "Project not found"}

    source_task = db.get(Task, source_task_id)
    target_task = db.get(Task, target_task_id)
    if (
        source_task is None
        or target_task is None
        or bool(source_task.is_deleted)
        or bool(target_task.is_deleted)
        or str(source_task.project_id or "").strip() != project_id
        or str(target_task.project_id or "").strip() != project_id
    ):
        return {"project_id": project_id, "found": False, "detail": "Task edge not found"}

    normalized_source = str(runtime_source or "").strip()
    normalized_correlation_id = str(correlation_id or "").strip() or None
    normalized_occurred_at = str(occurred_at or "").strip() or None
    events = load_events_after(db, "Task", str(target_task.id), 0)

    best_request_index: int | None = None
    best_request = None
    best_score: tuple[int, int, str] | None = None

    for index, event in enumerate(events):
        if str(event.event_type or "").strip() != EVENT_AUTOMATION_REQUESTED:
            continue
        payload = dict(event.payload or {})
        if str(payload.get("source_task_id") or "").strip() != str(source_task.id):
            continue
        if str(payload.get("source") or "").strip() != normalized_source:
            continue
        event_correlation_id = str(payload.get("correlation_id") or "").strip() or None
        event_at = _max_iso_timestamp(
            [
                payload.get("requested_at"),
                payload.get("triggered_at"),
                payload.get("lead_handoff_at"),
            ]
        )
        score = (
            0 if normalized_correlation_id and event_correlation_id == normalized_correlation_id else 1,
            0 if normalized_occurred_at and event_at == normalized_occurred_at else 1,
            str(event_at or ""),
        )
        if best_score is None or score[:2] < best_score[:2] or (score[:2] == best_score[:2] and score[2] > best_score[2]):
            best_score = score
            best_request_index = index
            best_request = event

    if best_request_index is None or best_request is None:
        return {
            "project_id": project_id,
            "found": False,
            "detail": "Runtime event detail not found",
        }

    next_request_index = len(events)
    for next_index in range(best_request_index + 1, len(events)):
        if str(events[next_index].event_type or "").strip() == EVENT_AUTOMATION_REQUESTED:
            next_request_index = next_index
            break

    request_payload = dict(best_request.payload or {})
    request_at = _max_iso_timestamp(
        [
            request_payload.get("requested_at"),
            request_payload.get("triggered_at"),
            request_payload.get("lead_handoff_at"),
        ]
    )
    terminal_status: str | None = None
    terminal_at: str | None = None
    terminal_summary: str | None = None
    terminal_error: str | None = None
    latest_comment_body: str | None = None
    latest_comment_at: str | None = None

    for event in events[best_request_index + 1 : next_request_index]:
        event_type = str(event.event_type or "").strip()
        payload = dict(event.payload or {})
        if event_type == EVENT_COMMENT_ADDED:
            latest_comment_body = str(payload.get("body") or "").strip() or None
            latest_comment_at = _max_iso_timestamp([payload.get("created_at"), payload.get("added_at")])
            continue
        if event_type == EVENT_AUTOMATION_COMPLETED and terminal_status is None:
            terminal_status = "completed"
            terminal_at = _max_iso_timestamp([payload.get("completed_at")])
            terminal_summary = str(payload.get("summary") or "").strip() or None
            continue
        if event_type == EVENT_AUTOMATION_FAILED and terminal_status is None:
            terminal_status = "failed"
            terminal_at = _max_iso_timestamp([payload.get("failed_at")])
            terminal_summary = str(payload.get("summary") or "").strip() or None
            terminal_error = str(payload.get("error") or "").strip() or None

    response_markdown = _build_runtime_event_response_markdown(
        latest_comment_body=latest_comment_body,
        terminal_status=terminal_status,
        terminal_summary=terminal_summary,
        terminal_error=terminal_error,
    )
    request_markdown = str(request_payload.get("instruction") or "").strip() or None
    runtime_classifier = _compact_classifier_payload(
        {
            "execution_intent": request_payload.get("execution_intent"),
            "execution_kickoff_intent": request_payload.get("execution_kickoff_intent"),
            "project_creation_intent": request_payload.get("project_creation_intent"),
            "workflow_scope": request_payload.get("workflow_scope"),
            "execution_mode": request_payload.get("execution_mode"),
            "task_completion_requested": request_payload.get("task_completion_requested"),
            "reason": request_payload.get("classifier_reason"),
        }
    )
    origin_debug = _load_origin_chat_debug(
        db=db,
        workspace_id=str(target_task.workspace_id or ""),
        project_id=project_id,
        chat_session_id=str(request_payload.get("chat_session_id") or "").strip() or None,
        requested_at=request_at,
    )
    return {
        "project_id": project_id,
        "project_name": str(project.name or ""),
        "found": True,
        "target_task_id": str(target_task.id),
        "target_task_title": str(target_task.title or target_task.id),
        "source_task_id": str(source_task.id),
        "source_task_title": str(source_task.title or source_task.id),
        "source": normalized_source,
        "requested_at": request_at,
        "correlation_id": str(request_payload.get("correlation_id") or "").strip() or None,
        "trigger_link": str(request_payload.get("trigger_link") or "").strip() or None,
        "reason": str(request_payload.get("reason") or "").strip() or None,
        "request_markdown": request_markdown,
        "runtime_classifier": runtime_classifier,
        "response_markdown": response_markdown,
        "response_status": terminal_status,
        "response_at": terminal_at,
        "response_summary": terminal_summary,
        "response_error": terminal_error,
        "response_comment_body": latest_comment_body,
        "response_comment_at": latest_comment_at,
        **origin_debug,
    }


def _append_task_relationship_edges(
    *,
    edge_map: dict[tuple[str, str], dict[str, Any]],
    ensure_edge,
    task_id: str,
    relationship: dict[str, Any],
    task_id_set: set[str],
) -> None:
    kind = str(relationship.get("kind") or "").strip().lower()
    statuses = _normalize_string_list(relationship.get("statuses"))
    linked_task_ids = [
        str(item or "").strip()
        for item in (relationship.get("task_ids") or [])
        if str(item or "").strip() and str(item or "").strip() in task_id_set
    ]
    if not linked_task_ids:
        return
    if kind == "delivers_to":
        for target_task_id in linked_task_ids:
            _merge_structural_edge(
                edge=ensure_edge(task_id, target_task_id),
                kind="delivers_to",
                statuses=statuses,
            )
    elif kind == "hands_off_to":
        for source_task_id in linked_task_ids:
            _merge_structural_edge(
                edge=ensure_edge(source_task_id, task_id),
                kind="hands_off_to",
                statuses=statuses,
            )
    elif kind == "escalates_to":
        for target_task_id in linked_task_ids:
            _merge_structural_edge(
                edge=ensure_edge(task_id, target_task_id),
                kind="escalates_to",
                statuses=statuses,
            )
    elif kind == "depends_on":
        for source_task_id in linked_task_ids:
            _merge_structural_edge(
                edge=ensure_edge(source_task_id, task_id),
                kind="depends_on",
                statuses=statuses,
            )


def _append_status_trigger_edges(
    *,
    edge_map: dict[tuple[str, str], dict[str, Any]],
    ensure_edge,
    task_id: str,
    trigger: dict[str, Any],
    task_id_set: set[str],
) -> None:
    if str(trigger.get("kind") or "").strip() != TRIGGER_KIND_STATUS_CHANGE:
        return
    if not bool(trigger.get("enabled", True)):
        return
    to_statuses = _normalize_string_list(trigger.get("to_statuses"))
    match_mode = str(trigger.get("match_mode") or "").strip() or None
    scope = str(trigger.get("scope") or "").strip().lower()
    selector = trigger.get("selector") if isinstance(trigger.get("selector"), dict) else {}
    selector_task_ids = [
        str(item or "").strip()
        for item in (selector.get("task_ids") or [])
        if str(item or "").strip() and str(item or "").strip() in task_id_set
    ]
    target_task_ids = [
        str(item or "").strip()
        for item in (trigger.get("target_task_ids") or [])
        if str(item or "").strip() and str(item or "").strip() in task_id_set
    ]

    if target_task_ids:
        for target_task_id in target_task_ids:
            if target_task_id == task_id:
                continue
            _merge_status_trigger_edge(
                edge=ensure_edge(task_id, target_task_id),
                to_statuses=to_statuses,
                match_mode=match_mode,
                scope=scope or None,
            )
        return

    if scope == "external" and selector_task_ids:
        for source_task_id in selector_task_ids:
            if source_task_id == task_id:
                continue
            _merge_status_trigger_edge(
                edge=ensure_edge(source_task_id, task_id),
                to_statuses=to_statuses,
                match_mode=match_mode,
                scope=scope or None,
            )


def _merge_structural_edge(*, edge: dict[str, Any], kind: str, statuses: list[str]) -> None:
    edge["structural"] = True
    kinds = list(edge.get("relationship_kinds") or [])
    if kind not in kinds:
        kinds.append(kind)
        edge["relationship_kinds"] = kinds
    _merge_channel(
        edge=edge,
        key=f"structural:{kind}:{','.join(statuses)}",
        payload={
            "kind": "relationship",
            "label": kind.replace("_", " "),
            "source": "task_relationships",
            "statuses": statuses,
        },
    )


def _merge_status_trigger_edge(
    *,
    edge: dict[str, Any],
    to_statuses: list[str],
    match_mode: str | None,
    scope: str | None,
) -> None:
    edge["trigger_dependency"] = True
    _merge_channel(
        edge=edge,
        key=f"status_trigger:{scope or ''}:{match_mode or ''}:{','.join(to_statuses)}",
        payload={
            "kind": "status_trigger",
            "label": "status trigger",
            "source": "execution_triggers",
            "scope": scope,
            "match_mode": match_mode,
            "to_statuses": to_statuses,
        },
    )


def _merge_channel(*, edge: dict[str, Any], key: str, payload: dict[str, Any]) -> None:
    channels = list(edge.get("channels") or [])
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        if str(channel.get("_key") or "").strip() != key:
            continue
        if "count" in payload:
            channel["count"] = int(channel.get("count") or 0) + int(payload.get("count") or 0)
        if _iso_greater(payload.get("latest_at"), channel.get("latest_at")):
            channel["latest_at"] = payload.get("latest_at")
        if payload.get("active"):
            channel["active"] = True
        channel["statuses"] = _compact_unique([*(channel.get("statuses") or []), *(payload.get("statuses") or [])])
        channel["to_statuses"] = _compact_unique([*(channel.get("to_statuses") or []), *(payload.get("to_statuses") or [])])
        channel["correlation_ids"] = _compact_unique([*(channel.get("correlation_ids") or []), *(payload.get("correlation_ids") or [])])
        edge["channels"] = channels
        return
    channels.append({"_key": key, **payload})
    edge["channels"] = channels


def _merge_runtime_event(*, edge: dict[str, Any], payload: dict[str, Any]) -> None:
    events = list(edge.get("runtime_events") or [])
    incoming_at = str(payload.get("at") or "").strip() or None
    incoming_source = str(payload.get("source") or "").strip() or "runtime"
    incoming_reason = str(payload.get("reason") or "").strip() or None
    incoming_trigger_link = str(payload.get("trigger_link") or "").strip() or None
    incoming_correlation_id = str(payload.get("correlation_id") or "").strip() or None
    for event in events:
        if not isinstance(event, dict):
            continue
        if str(event.get("at") or "").strip() != str(incoming_at or ""):
            continue
        if str(event.get("source") or "").strip() != incoming_source:
            continue
        if str(event.get("reason") or "").strip() != str(incoming_reason or ""):
            continue
        if str(event.get("trigger_link") or "").strip() != str(incoming_trigger_link or ""):
            continue
        if str(event.get("correlation_id") or "").strip() != str(incoming_correlation_id or ""):
            continue
        if payload.get("active"):
            event["active"] = True
        return
    events.append(
        {
            "at": incoming_at,
            "source": incoming_source,
            "reason": incoming_reason,
            "trigger_link": incoming_trigger_link,
            "correlation_id": incoming_correlation_id,
            "active": bool(payload.get("active")),
        }
    )
    events.sort(key=lambda item: str((item or {}).get("at") or ""), reverse=True)
    edge["runtime_events"] = events
def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = str(item or "").strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out


def _compact_unique(values: list[object]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        normalized = str(item or "").strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out


def _max_iso_timestamp(values: list[object]) -> str | None:
    normalized = [str(value or "").strip() for value in values if str(value or "").strip()]
    if not normalized:
        return None
    return max(normalized)


def _iso_greater(left: object, right: object) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text:
        return False
    if not right_text:
        return True
    return left_text > right_text


def _role_sort_key(value: str) -> int:
    normalized = str(value or "").strip().lower()
    if normalized == "developer":
        return 0
    if normalized == "lead":
        return 1
    if normalized == "qa":
        return 2
    return 3


def _status_sort_key(value: str) -> int:
    normalized = str(value or "").strip().lower()
    if normalized == "running":
        return 0
    if normalized == "dev":
        return 1
    if normalized == "lead":
        return 2
    if normalized == "qa":
        return 3
    if normalized == "blocked":
        return 4
    if normalized == "done":
        return 5
    return 6


def _empty_counts() -> dict[str, int]:
    return {
        "tasks": 0,
        "structural_edges": 0,
        "status_trigger_edges": 0,
        "runtime_edges": 0,
        "active_runtime_edges": 0,
        "running_tasks": 0,
        "queued_tasks": 0,
        "blocked_tasks": 0,
        "done_tasks": 0,
    }
