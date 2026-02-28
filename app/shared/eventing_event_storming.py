from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any

from sqlalchemy import select

from features.agents.codex_mcp_adapter import run_structured_codex_prompt_with_usage
from features.notes.domain import (
    EVENT_ARCHIVED as NOTE_EVENT_ARCHIVED,
    EVENT_CREATED as NOTE_EVENT_CREATED,
    EVENT_DELETED as NOTE_EVENT_DELETED,
    EVENT_RESTORED as NOTE_EVENT_RESTORED,
    EVENT_UPDATED as NOTE_EVENT_UPDATED,
)
from features.specifications.domain import (
    EVENT_ARCHIVED as SPECIFICATION_EVENT_ARCHIVED,
    EVENT_CREATED as SPECIFICATION_EVENT_CREATED,
    EVENT_DELETED as SPECIFICATION_EVENT_DELETED,
    EVENT_RESTORED as SPECIFICATION_EVENT_RESTORED,
    EVENT_UPDATED as SPECIFICATION_EVENT_UPDATED,
)
from features.tasks.domain import (
    EVENT_ARCHIVED as TASK_EVENT_ARCHIVED,
    EVENT_CREATED as TASK_EVENT_CREATED,
    EVENT_DELETED as TASK_EVENT_DELETED,
    EVENT_RESTORED as TASK_EVENT_RESTORED,
    EVENT_UPDATED as TASK_EVENT_UPDATED,
)

from .contracts import EventEnvelope
from .eventing_store import get_kurrent_client
from .knowledge_graph import graph_enabled, run_graph_query
from .models import (
    EventStormingAnalysisJob,
    EventStormingAnalysisRun,
    Note,
    Project,
    ProjectionCheckpoint,
    SessionLocal,
    Specification,
    Task,
)
from .settings import (
    EVENT_STORMING_ANALYSIS_BATCH_SIZE,
    EVENT_STORMING_ANALYSIS_STALE_AFTER_SECONDS,
    EVENT_STORMING_AI_MODEL,
    EVENT_STORMING_ANALYSIS_POLL_SECONDS,
    EVENT_STORMING_ANALYSIS_WORKER_ENABLED,
    EVENT_STORMING_ENABLED,
    GRAPH_PROJECTION_BATCH_SIZE,
    PERSISTENT_SUBSCRIPTION_EVENT_BUFFER_SIZE,
    PERSISTENT_SUBSCRIPTION_EVENT_STORMING_GROUP,
    PERSISTENT_SUBSCRIPTION_MAX_ACK_BATCH_SIZE,
    PERSISTENT_SUBSCRIPTION_MAX_ACK_DELAY_SECONDS,
    PERSISTENT_SUBSCRIPTION_RETRY_BACKOFF_SECONDS,
    PERSISTENT_SUBSCRIPTION_STOPPING_GRACE_SECONDS,
    AGENT_CODEX_MODEL,
    AGENT_CODEX_REASONING_EFFORT,
    logger,
)

_CHECKPOINT_NAME = "event-storming"
_projection_stop_event = threading.Event()
_projection_thread: threading.Thread | None = None
_projection_subscription: Any | None = None
_projection_subscription_lock = threading.Lock()

_analysis_stop_event = threading.Event()
_analysis_thread: threading.Thread | None = None

_TRACKED_EVENT_TYPES = {
    TASK_EVENT_CREATED,
    TASK_EVENT_UPDATED,
    TASK_EVENT_ARCHIVED,
    TASK_EVENT_RESTORED,
    TASK_EVENT_DELETED,
    NOTE_EVENT_CREATED,
    NOTE_EVENT_UPDATED,
    NOTE_EVENT_ARCHIVED,
    NOTE_EVENT_RESTORED,
    NOTE_EVENT_DELETED,
    SPECIFICATION_EVENT_CREATED,
    SPECIFICATION_EVENT_UPDATED,
    SPECIFICATION_EVENT_ARCHIVED,
    SPECIFICATION_EVENT_RESTORED,
    SPECIFICATION_EVENT_DELETED,
}

_DDD_RELEVANT_UPDATE_FIELDS: dict[str, set[str]] = {
    "task": {"title", "description", "instruction", "labels", "project_id", "is_deleted"},
    "note": {"title", "body", "tags", "project_id", "is_deleted"},
    "specification": {"title", "body", "tags", "project_id", "is_deleted"},
}

_ENTITY_LABELS = {
    "task": "Task",
    "note": "Note",
    "specification": "Specification",
}

_ES_COMPONENT_LABELS = {
    "bounded_context": "BoundedContext",
    "aggregate": "Aggregate",
    "command": "Command",
    "domain_event": "DomainEvent",
    "policy": "Policy",
    "read_model": "ReadModel",
}


def _extract_aggregate_from_stream(stream_name: str) -> tuple[str, str] | None:
    if stream_name.startswith("snapshot::"):
        return None
    base, sep, raw_id = stream_name.partition("::")
    if sep != "::" or not base or not raw_id:
        return None
    return base, raw_id


def _recorded_to_envelope(event: Any) -> tuple[int, EventEnvelope] | None:
    if getattr(event, "is_system_event", False):
        return None
    if getattr(event, "is_checkpoint", False):
        return None
    if getattr(event, "is_caught_up", False):
        return None
    if getattr(event, "is_fell_behind", False):
        return None
    commit_position = int(getattr(event, "commit_position", -1))
    parsed = _extract_aggregate_from_stream(getattr(event, "stream_name", ""))
    if parsed is None:
        return None
    aggregate_type, aggregate_id = parsed
    env = EventEnvelope(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        version=int(event.stream_position) + 1,
        event_type=event.type,
        payload=json.loads((event.data or b"{}").decode("utf-8")),
        metadata=json.loads((event.metadata or b"{}").decode("utf-8")),
    )
    return commit_position, env


def _normalize_entity_type(aggregate_type: str) -> str | None:
    normalized = str(aggregate_type or "").strip().lower()
    if normalized == "task":
        return "task"
    if normalized == "note":
        return "note"
    if normalized == "specification":
        return "specification"
    return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _reason_from_event_type(event_type: str) -> str:
    lowered = str(event_type or "").strip().lower()
    if "created" in lowered:
        return "initial"
    if "deleted" in lowered:
        return "deleted"
    return "updated"


def _dedupe_key(project_id: str, entity_type: str, entity_id: str) -> str:
    return f"{project_id}:{entity_type}:{entity_id}"


def _enqueue_analysis_job(
    *,
    db,
    project_id: str,
    workspace_id: str | None,
    entity_type: str,
    entity_id: str,
    reason: str,
    commit_position: int | None,
    payload: dict[str, Any],
) -> None:
    dedupe_key = _dedupe_key(project_id, entity_type, entity_id)
    existing = db.execute(select(EventStormingAnalysisJob).where(EventStormingAnalysisJob.dedup_key == dedupe_key)).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    payload_json = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)

    if existing is None:
        db.add(
            EventStormingAnalysisJob(
                workspace_id=workspace_id,
                project_id=project_id,
                entity_type=entity_type,
                entity_id=entity_id,
                reason=reason,
                status="queued",
                attempt_count=0,
                next_attempt_at=now,
                last_error=None,
                dedup_key=dedupe_key,
                last_commit_position=commit_position,
                payload_json=payload_json,
            )
        )
        return

    existing.workspace_id = workspace_id
    existing.reason = reason
    existing.status = "queued"
    existing.next_attempt_at = now
    existing.payload_json = payload_json
    existing.last_error = None
    if commit_position is not None:
        current = int(existing.last_commit_position or -1)
        if commit_position > current:
            existing.last_commit_position = commit_position


def _project_event_to_job_queue(db, ev: EventEnvelope, commit_position: int | None = None) -> None:
    if ev.event_type not in _TRACKED_EVENT_TYPES:
        return
    entity_type = _normalize_entity_type(ev.aggregate_type)
    if not entity_type:
        return
    entity_id = _as_str(ev.aggregate_id)
    if not entity_id:
        return
    payload = ev.payload or {}
    metadata = ev.metadata or {}
    project_id = _as_str(payload.get("project_id") or metadata.get("project_id"))
    workspace_id = _as_str(payload.get("workspace_id") or metadata.get("workspace_id"))
    if not project_id:
        return
    if not _project_event_storming_enabled(db, project_id):
        return
    if not _event_payload_affects_ddd(entity_type=entity_type, event_type=ev.event_type, payload=payload):
        return
    _enqueue_analysis_job(
        db=db,
        project_id=project_id,
        workspace_id=workspace_id,
        entity_type=entity_type,
        entity_id=entity_id,
        reason=_reason_from_event_type(ev.event_type),
        commit_position=commit_position,
        payload={"event_type": ev.event_type, "event_version": ev.version},
    )


def _project_event_storming_enabled(db, project_id: str) -> bool:
    row = db.get(Project, project_id)
    if row is None or bool(row.is_deleted):
        return False
    return bool(getattr(row, "event_storming_enabled", True))


def _event_payload_affects_ddd(*, entity_type: str, event_type: str, payload: dict[str, Any]) -> bool:
    lowered = str(event_type or "").strip().lower()
    if "created" in lowered or "deleted" in lowered:
        return True
    if "archived" in lowered or "restored" in lowered:
        return False
    if "updated" not in lowered:
        return False
    relevant_keys = _DDD_RELEVANT_UPDATE_FIELDS.get(entity_type) or set()
    if not relevant_keys:
        return True
    changed_keys = {str(key).strip() for key in (payload or {}).keys() if str(key).strip()}
    if not changed_keys:
        return True
    return bool(changed_keys.intersection(relevant_keys))


def _get_checkpoint(db, name: str = _CHECKPOINT_NAME) -> ProjectionCheckpoint:
    checkpoint = db.get(ProjectionCheckpoint, name)
    if checkpoint is None:
        checkpoint = ProjectionCheckpoint(name=name, commit_position=0)
        db.add(checkpoint)
        db.flush()
    return checkpoint


def project_kurrent_event_storming_once(limit: int | None = None) -> int:
    if not EVENT_STORMING_ENABLED:
        return 0
    client = get_kurrent_client()
    if client is None:
        return 0
    batch_limit = max(1, int(limit or GRAPH_PROJECTION_BATCH_SIZE))
    try:
        with SessionLocal() as db:
            checkpoint = _get_checkpoint(db)
            start_position = checkpoint.commit_position if checkpoint.commit_position > 0 else None
            rows = client.read_all(commit_position=start_position, limit=batch_limit)
            processed = 0
            for event in rows:
                packed = _recorded_to_envelope(event)
                if packed is None:
                    continue
                commit_position, env = packed
                if commit_position <= checkpoint.commit_position:
                    continue
                _project_event_to_job_queue(db, env, commit_position)
                checkpoint.commit_position = commit_position
                db.commit()
                processed += 1
            return processed
    except Exception as exc:
        logger.warning("Event storming catch-up failed: %s", exc)
        return 0


def _set_projection_subscription(subscription: Any | None) -> None:
    global _projection_subscription
    with _projection_subscription_lock:
        _projection_subscription = subscription


def _stop_projection_subscription() -> None:
    with _projection_subscription_lock:
        subscription = _projection_subscription
    if subscription is None:
        return
    try:
        subscription.stop()
    except Exception:
        pass


def _projection_worker_loop() -> None:
    client = get_kurrent_client()
    if client is None:
        return
    while not _projection_stop_event.is_set():
        subscription = None
        try:
            subscription = client.read_subscription_to_all(
                group_name=PERSISTENT_SUBSCRIPTION_EVENT_STORMING_GROUP,
                event_buffer_size=max(1, int(PERSISTENT_SUBSCRIPTION_EVENT_BUFFER_SIZE)),
                max_ack_batch_size=max(1, int(PERSISTENT_SUBSCRIPTION_MAX_ACK_BATCH_SIZE)),
                max_ack_delay=max(0.0, float(PERSISTENT_SUBSCRIPTION_MAX_ACK_DELAY_SECONDS)),
                stopping_grace=max(0.0, float(PERSISTENT_SUBSCRIPTION_STOPPING_GRACE_SECONDS)),
            )
            _set_projection_subscription(subscription)
            for event in subscription:
                if _projection_stop_event.is_set():
                    break
                packed = _recorded_to_envelope(event)
                if packed is None:
                    subscription.ack(event)
                    continue
                commit_position, env = packed
                try:
                    with SessionLocal() as db:
                        _project_event_to_job_queue(db, env, commit_position)
                        db.commit()
                    subscription.ack(event)
                except Exception as exc:
                    logger.warning("Event storming projection event failed, retrying event: %s", exc)
                    subscription.nack(event, "retry")
        except Exception as exc:
            logger.warning("Event storming projection worker retrying after error: %s", exc)
            _projection_stop_event.wait(max(0.2, float(PERSISTENT_SUBSCRIPTION_RETRY_BACKOFF_SECONDS)))
        finally:
            _set_projection_subscription(None)
            if subscription is not None:
                try:
                    subscription.stop()
                except Exception:
                    pass


def _slug(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:120]


def _component_id(project_id: str, component_type: str, name: str) -> str:
    return f"{project_id}:es:{component_type}:{_slug(name)}"


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raw = str(value or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


_ES_COMPONENT_TYPES = set(_ES_COMPONENT_LABELS.keys())
_ES_RELATION_TYPES = {
    "CONTAINS_AGGREGATE",
    "HANDLES_COMMAND",
    "EMITS_EVENT",
    "UPDATES_READ_MODEL",
    "ENFORCES_POLICY",
    "TRIGGERS_POLICY",
}


def _load_entity_graph_context(*, project_id: str, entity_type: str, entity_id: str, limit: int = 16) -> list[dict[str, str]]:
    label = _ENTITY_LABELS.get(entity_type)
    if not label:
        return []
    rows = run_graph_query(
        f"""
        MATCH (a:{label} {{id:$entity_id}})
        OPTIONAL MATCH (a)-[r]-(n)
        WHERE coalesce(n.project_id, '') = $project_id
          AND coalesce(n.id, '') <> $entity_id
        RETURN type(r) AS relation,
               head(labels(n)) AS neighbor_type,
               n.id AS neighbor_id,
               coalesce(n.title, n.name, n.id) AS neighbor_title
        ORDER BY relation ASC, neighbor_type ASC, neighbor_title ASC
        LIMIT $limit
        """,
        {"entity_id": entity_id, "project_id": project_id, "limit": max(1, int(limit))},
    )
    out: list[dict[str, str]] = []
    for row in rows:
        out.append(
            {
                "relation": str(row.get("relation") or "").strip(),
                "neighbor_type": str(row.get("neighbor_type") or "").strip(),
                "neighbor_id": str(row.get("neighbor_id") or "").strip(),
                "neighbor_title": str(row.get("neighbor_title") or "").strip(),
            }
        )
    return out


def _load_project_component_snapshot(*, project_id: str, limit_components: int = 24, limit_relations: int = 0) -> dict[str, Any]:
    component_rows = run_graph_query(
        """
        MATCH (c)
        WHERE coalesce(c.project_id, '') = $project_id
          AND any(lbl IN labels(c) WHERE lbl IN $component_labels)
        RETURN head([lbl IN labels(c) WHERE lbl IN $component_labels]) AS component_type,
               c.id AS component_id,
               coalesce(c.title, c.name, c.id) AS component_title
        ORDER BY component_type ASC, component_title ASC
        LIMIT $limit_components
        """,
        {
            "project_id": project_id,
            "component_labels": list(_ES_COMPONENT_LABELS.values()),
            "limit_components": max(1, int(limit_components)),
        },
    )
    relation_rows: list[dict[str, Any]] = []
    if int(limit_relations or 0) > 0:
        relation_rows = run_graph_query(
            """
            MATCH (a)-[r]->(b)
            WHERE coalesce(a.project_id, '') = $project_id
              AND coalesce(b.project_id, '') = $project_id
              AND any(lbl IN labels(a) WHERE lbl IN $component_labels)
              AND any(lbl IN labels(b) WHERE lbl IN $component_labels)
            RETURN head([lbl IN labels(a) WHERE lbl IN $component_labels]) AS source_type,
                   coalesce(a.title, a.name, a.id) AS source_title,
                   type(r) AS relation,
                   head([lbl IN labels(b) WHERE lbl IN $component_labels]) AS target_type,
                   coalesce(b.title, b.name, b.id) AS target_title
            ORDER BY relation ASC, source_type ASC, source_title ASC
            LIMIT $limit_relations
            """,
            {
                "project_id": project_id,
                "component_labels": list(_ES_COMPONENT_LABELS.values()),
                "limit_relations": max(1, int(limit_relations)),
            },
        )
    return {
        "components": [
            {
                "component_type": str(item.get("component_type") or ""),
                "component_id": str(item.get("component_id") or ""),
                "component_title": str(item.get("component_title") or ""),
            }
            for item in component_rows
        ],
        "relations": [
            {
                "source_type": str(item.get("source_type") or ""),
                "source_title": str(item.get("source_title") or ""),
                "relation": str(item.get("relation") or ""),
                "target_type": str(item.get("target_type") or ""),
                "target_title": str(item.get("target_title") or ""),
            }
            for item in relation_rows
        ],
    }


def _event_storming_ai_prompt(
    *,
    entity_type: str,
    title: str,
    tags: list[str],
    text: str,
    entity_graph_context: list[dict[str, str]],
    project_component_snapshot: dict[str, Any],
) -> str:
    tag_list = ", ".join(tags) if tags else "(none)"
    source_text = str(text or "").strip()
    if len(source_text) > 5000:
        source_text = source_text[:5000]
    context_lines = [
        f"- {row['relation']} -> {row['neighbor_type']} [{row['neighbor_id']}] {row['neighbor_title']}"
        for row in entity_graph_context
        if row.get("neighbor_id")
    ]
    existing_component_lines = [
        f"- {row['component_type']}: {row['component_title']}"
        for row in (project_component_snapshot.get("components") or [])
        if str(row.get("component_type") or "").strip() and str(row.get("component_title") or "").strip()
    ]
    return (
        "You are an expert Event Storming and DDD analyst.\n"
        "Extract ONLY high-confidence, explicit components from the provided source text.\n"
        "Do not invent generic placeholders. If uncertain, omit.\n"
        "Reuse existing project component names when semantics match.\n"
        "Return strict JSON with this shape:\n"
        "{\n"
        '  "components":[{"component_type":"bounded_context|aggregate|command|domain_event|policy|read_model","name":"...","confidence":0.0,"evidence":"..."}],\n'
        '  "relations":[{"source_component_type":"...","source_name":"...","relation":"CONTAINS_AGGREGATE|HANDLES_COMMAND|EMITS_EVENT|UPDATES_READ_MODEL|ENFORCES_POLICY|TRIGGERS_POLICY","target_component_type":"...","target_name":"...","confidence":0.0,"evidence":"..."}]\n'
        "}\n"
        "Rules:\n"
        "- confidence must be [0,1]\n"
        "- evidence must quote or paraphrase a concrete snippet from source text\n"
        "- no markdown, no prose, JSON only\n"
        f"Entity type: {entity_type}\n"
        f"Title: {title}\n"
        f"Tags: {tag_list}\n"
        "Entity graph context:\n"
        + ("\n".join(context_lines) if context_lines else "- (none)")
        + "\n"
        "Existing project components:\n"
        + ("\n".join(existing_component_lines) if existing_component_lines else "- (none)")
        + "\n"
        "Source text:\n"
        f"{source_text}\n"
    )


def _extract_with_codex_agent(
    *,
    workspace_id: str | None,
    project_id: str,
    entity_type: str,
    entity_id: str,
    title: str,
    tags: list[str],
    text: str,
    entity_graph_context: list[dict[str, str]],
    project_component_snapshot: dict[str, Any],
) -> dict[str, Any]:
    model = str(EVENT_STORMING_AI_MODEL or AGENT_CODEX_MODEL or "").strip() or None
    prompt = _event_storming_ai_prompt(
        entity_type=entity_type,
        title=title,
        tags=tags,
        text=text,
        entity_graph_context=entity_graph_context,
        project_component_snapshot=project_component_snapshot,
    )
    schema = {
        "type": "object",
        "properties": {
            "components": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "component_type": {"type": "string"},
                        "name": {"type": "string"},
                        "confidence": {"type": "number"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["component_type", "name", "confidence", "evidence"],
                    "additionalProperties": False,
                },
            },
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_component_type": {"type": "string"},
                        "source_name": {"type": "string"},
                        "relation": {"type": "string"},
                        "target_component_type": {"type": "string"},
                        "target_name": {"type": "string"},
                        "confidence": {"type": "number"},
                        "evidence": {"type": "string"},
                    },
                    "required": [
                        "source_component_type",
                        "source_name",
                        "relation",
                        "target_component_type",
                        "target_name",
                        "confidence",
                        "evidence",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["components", "relations"],
        "additionalProperties": False,
    }
    chat_session_id = f"event-storming-{project_id}-{entity_type}-{entity_id}"
    parsed_payload, usage_payload = run_structured_codex_prompt_with_usage(
        prompt=prompt,
        output_schema=schema,
        workspace_id=workspace_id,
        session_key=chat_session_id,
        model=model,
        reasoning_effort=str(AGENT_CODEX_REASONING_EFFORT or "").strip() or None,
        mcp_servers=None,
    )
    return {
        "payload": {str(key): value for key, value in parsed_payload.items()},
        "usage": usage_payload or {},
        "prompt_chars": len(prompt),
    }


def _normalize_ai_extraction(project_id: str, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    component_map: dict[tuple[str, str], dict[str, Any]] = {}
    for row in payload.get("components") or []:
        if not isinstance(row, dict):
            continue
        component_type = str(row.get("component_type") or "").strip().lower()
        if component_type not in _ES_COMPONENT_TYPES:
            continue
        name = str(row.get("name") or "").strip()[:180]
        if not name:
            continue
        evidence = str(row.get("evidence") or "").strip()[:220]
        confidence = max(0.0, min(1.0, float(row.get("confidence") or 0.0)))
        key = (component_type, name.lower())
        current = component_map.get(key)
        if current is None or confidence > float(current.get("confidence") or 0.0):
            component_map[key] = {
                "id": _component_id(project_id, component_type, name),
                "component_type": component_type,
                "label": _ES_COMPONENT_LABELS[component_type],
                "name": name,
                "confidence": confidence,
                "evidence": evidence,
            }
    components = sorted(component_map.values(), key=lambda item: (-float(item["confidence"]), item["component_type"], item["name"]))
    name_index = {(item["component_type"], item["name"].lower()): item["id"] for item in components}

    relations: list[dict[str, Any]] = []
    seen_rel: set[tuple[str, str, str]] = set()
    for row in payload.get("relations") or []:
        if not isinstance(row, dict):
            continue
        relation = str(row.get("relation") or "").strip().upper()
        if relation not in _ES_RELATION_TYPES:
            continue
        src_type = str(row.get("source_component_type") or "").strip().lower()
        src_name = str(row.get("source_name") or "").strip().lower()
        tgt_type = str(row.get("target_component_type") or "").strip().lower()
        tgt_name = str(row.get("target_name") or "").strip().lower()
        source_id = name_index.get((src_type, src_name))
        target_id = name_index.get((tgt_type, tgt_name))
        if not source_id or not target_id or source_id == target_id:
            continue
        key = (source_id, relation, target_id)
        if key in seen_rel:
            continue
        seen_rel.add(key)
        relations.append(
            {
                "source_id": source_id,
                "target_id": target_id,
                "relation": relation,
                "confidence": max(0.0, min(1.0, float(row.get("confidence") or 0.0))),
                "evidence": str(row.get("evidence") or "").strip()[:220],
            }
        )
    return components, relations


def _load_entity_snapshot(db, job: EventStormingAnalysisJob) -> dict[str, Any] | None:
    entity_type = str(job.entity_type or "").strip().lower()
    if entity_type == "task":
        task = db.get(Task, job.entity_id)
        if task is None:
            return None
        text = "\n\n".join(
            part for part in [str(task.title or ""), str(task.description or ""), str(task.instruction or "")] if part.strip()
        ).strip()
        return {
            "workspace_id": str(task.workspace_id or "").strip() or None,
            "project_id": str(task.project_id or "").strip() or str(job.project_id or "").strip() or None,
            "title": str(task.title or "").strip(),
            "text": text,
            "tags": _json_list(task.labels),
            "is_deleted": bool(task.is_deleted),
        }
    if entity_type == "note":
        note = db.get(Note, job.entity_id)
        if note is None:
            return None
        text = "\n\n".join(part for part in [str(note.title or ""), str(note.body or "")] if part.strip()).strip()
        return {
            "workspace_id": str(note.workspace_id or "").strip() or None,
            "project_id": str(note.project_id or "").strip() or str(job.project_id or "").strip() or None,
            "title": str(note.title or "").strip(),
            "text": text,
            "tags": _json_list(note.tags),
            "is_deleted": bool(note.is_deleted),
        }
    if entity_type == "specification":
        spec = db.get(Specification, job.entity_id)
        if spec is None:
            return None
        text = "\n\n".join(part for part in [str(spec.title or ""), str(spec.body or "")] if part.strip()).strip()
        return {
            "workspace_id": str(spec.workspace_id or "").strip() or None,
            "project_id": str(spec.project_id or "").strip() or str(job.project_id or "").strip() or None,
            "title": str(spec.title or "").strip(),
            "text": text,
            "tags": _json_list(spec.tags),
            "is_deleted": bool(spec.is_deleted),
        }
    return None


def _retry_backoff(attempt: int) -> float:
    exponent = max(0, int(attempt) - 1)
    return max(2.0, min(300.0, 2.0 * (2**exponent)))


def _normalize_tags(tags: list[str] | None) -> list[str]:
    return sorted({str(tag or "").strip().lower() for tag in (tags or []) if str(tag or "").strip()})


def _build_snapshot_input_hash(*, project_id: str, entity_type: str, entity_id: str, snapshot: dict[str, Any]) -> str:
    payload = {
        "project_id": project_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "title": str(snapshot.get("title") or "").strip(),
        "text": str(snapshot.get("text") or "").strip(),
        "tags": _normalize_tags([str(item) for item in (snapshot.get("tags") or [])]),
    }
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _latest_done_input_hash(db, *, project_id: str, entity_type: str, entity_id: str) -> str | None:
    row = db.execute(
        select(EventStormingAnalysisRun.input_hash)
        .where(
            EventStormingAnalysisRun.project_id == project_id,
            EventStormingAnalysisRun.entity_type == entity_type,
            EventStormingAnalysisRun.entity_id == entity_id,
            EventStormingAnalysisRun.status == "done",
        )
        .order_by(EventStormingAnalysisRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    text = str(row or "").strip()
    return text or None


def _clear_artifact_links(*, project_id: str, entity_type: str, entity_id: str) -> None:
    label = _ENTITY_LABELS.get(entity_type)
    if not label:
        return
    run_graph_query(
        f"""
        MATCH (a:{label} {{id:$entity_id}})-[r:RELATES_TO_ES]->(c)
        WHERE coalesce(c.project_id, '') = $project_id
        DELETE r
        """,
        {"entity_id": entity_id, "project_id": project_id},
        write=True,
    )


def _sync_graph_for_job(job: EventStormingAnalysisJob, snapshot: dict[str, Any] | None) -> tuple[int, int, dict[str, Any]]:
    project_id = str(job.project_id or "").strip()
    entity_type = str(job.entity_type or "").strip().lower()
    entity_id = str(job.entity_id or "").strip()
    if not project_id or not entity_id or entity_type not in _ENTITY_LABELS:
        return 0, 0, {"components": [], "relations": []}

    if snapshot is None or bool(snapshot.get("is_deleted")):
        _clear_artifact_links(project_id=project_id, entity_type=entity_type, entity_id=entity_id)
        return 0, 0, {"components": [], "relations": []}

    workspace_id = _as_str(snapshot.get("workspace_id"))
    source_label = _ENTITY_LABELS[entity_type]
    source_title = _as_str(snapshot.get("title")) or entity_id
    entity_graph_context = _load_entity_graph_context(
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=8,
    )
    project_component_snapshot = _load_project_component_snapshot(project_id=project_id, limit_components=24, limit_relations=0)
    extracted = _extract_with_codex_agent(
        workspace_id=workspace_id,
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        title=str(snapshot.get("title") or ""),
        tags=[str(item) for item in (snapshot.get("tags") or [])],
        text=str(snapshot.get("text") or ""),
        entity_graph_context=entity_graph_context,
        project_component_snapshot=project_component_snapshot,
    )
    extracted_payload = extracted.get("payload") if isinstance(extracted, dict) else {}
    usage_payload = extracted.get("usage") if isinstance(extracted, dict) else {}
    prompt_chars = int(extracted.get("prompt_chars") or 0) if isinstance(extracted, dict) else 0
    components, component_relations = _normalize_ai_extraction(project_id, extracted_payload)
    component_ids = [str(item["id"]) for item in components]

    run_graph_query(
        f"""
        MERGE (a:{source_label} {{id:$entity_id}})
        SET a.project_id = $project_id,
            a.workspace_id = coalesce(a.workspace_id, $workspace_id),
            a.title = coalesce(a.title, $source_title)
        """,
        {
            "entity_id": entity_id,
            "project_id": project_id,
            "workspace_id": workspace_id,
            "source_title": source_title,
        },
        write=True,
    )

    for item in components:
        run_graph_query(
            f"""
            MERGE (c:{item["label"]} {{id:$component_id}})
            SET c.project_id = $project_id,
                c.workspace_id = coalesce(c.workspace_id, $workspace_id),
                c.name = $component_name,
                c.title = $component_name,
                c.component_type = $component_type,
                c.updated_at = $updated_at
            """,
            {
                "component_id": str(item["id"]),
                "project_id": project_id,
                "workspace_id": workspace_id,
                "component_name": str(item["name"]),
                "component_type": str(item["component_type"]),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            write=True,
        )

    if component_ids:
        run_graph_query(
            f"""
            MATCH (a:{source_label} {{id:$entity_id}})-[r:RELATES_TO_ES]->(c)
            WHERE coalesce(c.project_id, '') = $project_id
              AND NOT c.id IN $component_ids
            DELETE r
            """,
            {
                "entity_id": entity_id,
                "project_id": project_id,
                "component_ids": component_ids,
            },
            write=True,
        )
    else:
        _clear_artifact_links(project_id=project_id, entity_type=entity_type, entity_id=entity_id)

    for item in components:
        run_graph_query(
            f"""
            MATCH (a:{source_label} {{id:$entity_id}})
            MATCH (c:{item["label"]} {{id:$component_id}})
            MERGE (a)-[r:RELATES_TO_ES]->(c)
            SET r.confidence = $confidence,
                r.inference_method = CASE
                  WHEN coalesce(r.inference_method, '') = 'manual' THEN 'manual'
                  ELSE 'ai_agent'
                END,
                r.review_status = CASE
                  WHEN coalesce(r.inference_method, '') = 'manual' THEN coalesce(r.review_status, 'candidate')
                  WHEN $confidence >= 0.8 THEN 'approved'
                  ELSE 'candidate'
                END,
                r.updated_at = $updated_at,
                r.source_entity_type = $source_entity_type,
                r.source_entity_id = $entity_id,
                r.evidence = $evidence
            """,
            {
                "entity_id": entity_id,
                "component_id": str(item["id"]),
                "confidence": float(item["confidence"]),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source_entity_type": entity_type,
                "evidence": str(item.get("evidence") or ""),
            },
            write=True,
        )

    for rel in component_relations:
        relation = str(rel.get("relation") or "").strip().upper()
        if relation not in _ES_RELATION_TYPES:
            continue
        run_graph_query(
            f"""
            MATCH (a {{id:$source_id}})
            MATCH (b {{id:$target_id}})
            MERGE (a)-[:{relation}]->(b)
            """,
            {
                "source_id": str(rel["source_id"]),
                "target_id": str(rel["target_id"]),
            },
            write=True,
        )

    return len(components), len(component_relations), {
        "components": components,
        "relations": component_relations,
        "usage": usage_payload or {},
        "prompt_chars": prompt_chars,
    }


def _process_analysis_job(job_id: int) -> None:
    started = perf_counter()
    with SessionLocal() as db:
        job = db.get(EventStormingAnalysisJob, job_id)
        if job is None:
            return
        if job.status != "running":
            return
        try:
            if not _project_event_storming_enabled(db, str(job.project_id or "").strip()):
                elapsed_ms = int(max(0.0, (perf_counter() - started) * 1000.0))
                db.add(
                    EventStormingAnalysisRun(
                        job_id=job.id,
                        project_id=job.project_id,
                        entity_type=job.entity_type,
                        entity_id=job.entity_id,
                        status="done",
                        inference_method="disabled",
                        extractor_version="es-codex-v1",
                        components_count=0,
                        relations_count=0,
                        prompt_chars=0,
                        input_hash=None,
                        usage_json="{}",
                        duration_ms=elapsed_ms,
                        output_json='{"skipped":"project_event_storming_disabled"}',
                        error=None,
                    )
                )
                job.status = "done"
                job.last_error = None
                db.commit()
                return
            snapshot = _load_entity_snapshot(db, job)
            input_hash: str | None = None
            if snapshot is not None and not bool(snapshot.get("is_deleted")):
                input_hash = _build_snapshot_input_hash(
                    project_id=str(job.project_id or "").strip(),
                    entity_type=str(job.entity_type or "").strip().lower(),
                    entity_id=str(job.entity_id or "").strip(),
                    snapshot=snapshot,
                )
                previous_hash = _latest_done_input_hash(
                    db,
                    project_id=str(job.project_id or "").strip(),
                    entity_type=str(job.entity_type or "").strip(),
                    entity_id=str(job.entity_id or "").strip(),
                )
                if previous_hash and previous_hash == input_hash:
                    elapsed_ms = int(max(0.0, (perf_counter() - started) * 1000.0))
                    db.add(
                        EventStormingAnalysisRun(
                            job_id=job.id,
                            project_id=job.project_id,
                            entity_type=job.entity_type,
                            entity_id=job.entity_id,
                            status="done",
                            inference_method="content_hash_skip",
                            extractor_version="es-codex-v1",
                            components_count=0,
                            relations_count=0,
                            prompt_chars=0,
                            input_hash=input_hash,
                            usage_json="{}",
                            duration_ms=elapsed_ms,
                            output_json='{"skipped":"input_hash_unchanged"}',
                            error=None,
                        )
                    )
                    job.status = "done"
                    job.last_error = None
                    db.commit()
                    return
            components_count, relations_count, output = _sync_graph_for_job(job, snapshot)
            elapsed_ms = int(max(0.0, (perf_counter() - started) * 1000.0))
            usage_payload = output.get("usage") if isinstance(output, dict) else {}
            prompt_chars = int(output.get("prompt_chars") or 0) if isinstance(output, dict) else 0
            db.add(
                EventStormingAnalysisRun(
                    job_id=job.id,
                    project_id=job.project_id,
                    entity_type=job.entity_type,
                    entity_id=job.entity_id,
                    status="done",
                    inference_method="ai_agent",
                    extractor_version="es-codex-v1",
                    components_count=components_count,
                    relations_count=relations_count,
                    prompt_chars=prompt_chars,
                    input_hash=input_hash,
                    usage_json=json.dumps(usage_payload or {}, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                    duration_ms=elapsed_ms,
                    output_json=json.dumps(output, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str),
                    error=None,
                )
            )
            job.status = "done"
            job.last_error = None
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(EventStormingAnalysisJob, job_id)
            if job is None:
                return
            job.attempt_count = int(job.attempt_count or 0) + 1
            job.status = "failed"
            job.last_error = str(exc)[:4000]
            job.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=_retry_backoff(job.attempt_count))
            elapsed_ms = int(max(0.0, (perf_counter() - started) * 1000.0))
            db.add(
                EventStormingAnalysisRun(
                    job_id=job.id,
                    project_id=job.project_id,
                    entity_type=job.entity_type,
                    entity_id=job.entity_id,
                    status="failed",
                    inference_method="ai_agent",
                    extractor_version="es-codex-v1",
                    components_count=0,
                    relations_count=0,
                    prompt_chars=0,
                    input_hash=None,
                    usage_json="{}",
                    duration_ms=elapsed_ms,
                    output_json="{}",
                    error=str(exc)[:4000],
                )
            )
            db.commit()


def _claim_analysis_jobs(limit: int) -> list[int]:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        rows = db.execute(
            select(EventStormingAnalysisJob)
            .where(
                EventStormingAnalysisJob.status.in_(["queued", "failed"]),
                EventStormingAnalysisJob.next_attempt_at <= now,
            )
            .order_by(EventStormingAnalysisJob.updated_at.asc(), EventStormingAnalysisJob.id.asc())
            .limit(max(1, int(limit))),
        ).scalars().all()
        job_ids: list[int] = []
        for row in rows:
            row.status = "running"
            job_ids.append(int(row.id))
        if job_ids:
            db.commit()
        return job_ids


def _recover_stale_running_analysis_jobs_once(limit: int) -> int:
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=float(EVENT_STORMING_ANALYSIS_STALE_AFTER_SECONDS))
    max_rows = max(1, int(limit))
    with SessionLocal() as db:
        rows = db.execute(
            select(EventStormingAnalysisJob)
            .where(
                EventStormingAnalysisJob.status == "running",
                EventStormingAnalysisJob.updated_at <= stale_before,
            )
            .order_by(EventStormingAnalysisJob.updated_at.asc(), EventStormingAnalysisJob.id.asc())
            .limit(max_rows)
        ).scalars().all()
        if not rows:
            return 0
        for row in rows:
            row.status = "queued"
            row.next_attempt_at = now
            row.last_error = (
                f"Recovered stale running job after exceeding "
                f"{int(EVENT_STORMING_ANALYSIS_STALE_AFTER_SECONDS)}s threshold."
            )
        db.commit()
        return len(rows)


def _analysis_worker_loop() -> None:
    while not _analysis_stop_event.is_set():
        try:
            recovered = _recover_stale_running_analysis_jobs_once(EVENT_STORMING_ANALYSIS_BATCH_SIZE * 2)
            if recovered > 0:
                logger.warning("Recovered %s stale event storming analysis jobs.", recovered)
            claimed = _claim_analysis_jobs(EVENT_STORMING_ANALYSIS_BATCH_SIZE)
            if not claimed:
                _analysis_stop_event.wait(EVENT_STORMING_ANALYSIS_POLL_SECONDS)
                continue
            for job_id in claimed:
                if _analysis_stop_event.is_set():
                    break
                _process_analysis_job(job_id)
        except Exception as exc:
            logger.warning("Event storming analysis worker iteration failed: %s", exc)
            _analysis_stop_event.wait(EVENT_STORMING_ANALYSIS_POLL_SECONDS)


def enqueue_event_storming_project_backfill(*, project_id: str, workspace_id: str | None = None) -> dict[str, int]:
    project_key = str(project_id or "").strip()
    if not project_key:
        return {"queued": 0}
    with SessionLocal() as db:
        project = db.get(Project, project_key)
        if project is None or bool(project.is_deleted):
            return {"queued": 0}
        if not bool(getattr(project, "event_storming_enabled", True)):
            return {"queued": 0}
        resolved_workspace_id = str(workspace_id or project.workspace_id or "").strip() or None
        queued = 0
        task_ids = db.execute(
            select(Task.id).where(Task.project_id == project_key, Task.is_deleted == False)
        ).scalars().all()
        note_ids = db.execute(
            select(Note.id).where(Note.project_id == project_key, Note.is_deleted == False)
        ).scalars().all()
        specification_ids = db.execute(
            select(Specification.id).where(Specification.project_id == project_key, Specification.is_deleted == False)
        ).scalars().all()
        for entity_type, ids in (
            ("task", task_ids),
            ("note", note_ids),
            ("specification", specification_ids),
        ):
            for entity_id in ids:
                _enqueue_analysis_job(
                    db=db,
                    project_id=project_key,
                    workspace_id=resolved_workspace_id,
                    entity_type=entity_type,
                    entity_id=str(entity_id),
                    reason="backfill",
                    commit_position=None,
                    payload={"event_type": "BackfillRequested", "event_version": 1},
                )
                queued += 1
        db.commit()
        return {"queued": queued}


def start_event_storming_projection_worker() -> None:
    global _projection_thread, _analysis_thread
    if not EVENT_STORMING_ENABLED:
        return
    if not graph_enabled():
        return

    if EVENT_STORMING_ANALYSIS_WORKER_ENABLED and (_analysis_thread is None or not _analysis_thread.is_alive()):
        _analysis_stop_event.clear()
        _analysis_thread = threading.Thread(
            target=_analysis_worker_loop,
            name="event-storming-analysis-worker",
            daemon=True,
        )
        _analysis_thread.start()

    if get_kurrent_client() is None:
        return
    if _projection_thread and _projection_thread.is_alive():
        return
    _projection_stop_event.clear()
    _projection_thread = threading.Thread(
        target=_projection_worker_loop,
        name="kurrent-event-storming-projection-worker",
        daemon=True,
    )
    _projection_thread.start()


def stop_event_storming_projection_worker() -> None:
    global _projection_thread, _analysis_thread
    _projection_stop_event.set()
    _analysis_stop_event.set()
    _stop_projection_subscription()
    if _projection_thread and _projection_thread.is_alive():
        _projection_thread.join(timeout=3)
    _projection_thread = None
    if _analysis_thread and _analysis_thread.is_alive():
        _analysis_thread.join(timeout=3)
    _analysis_thread = None
