import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from features.architecture_inventory import build_architecture_export, build_architecture_inventory
from plugins.descriptors import list_plugin_descriptors
from shared.core import ensure_project_access, ensure_role, get_current_user, get_db, load_events_after, metrics_snapshot
from shared.models import ChatMessage, ChatSession, StoredEvent
from shared.settings import (
    GRAPH_RAG_CANARY_PROJECT_IDS,
    GRAPH_RAG_CANARY_WORKSPACE_IDS,
    GRAPH_RAG_SLO_EMBED_CONTEXT_ERROR_RATE_PCT,
    GRAPH_RAG_SLO_CONTEXT_NO_SUMMARY_MS,
    GRAPH_RAG_SLO_CONTEXT_WITH_SUMMARY_MS,
    GRAPH_RAG_SLO_EMBED_INGEST_P95_MS,
)

router = APIRouter()


@router.get("/api/debug/architecture-inventory")
def architecture_inventory(_user=Depends(get_current_user)):
    return build_architecture_inventory()


@router.get("/api/debug/architecture-export")
def architecture_export(_user=Depends(get_current_user)):
    return build_architecture_export()


@router.get("/api/debug/plugin-descriptors")
def plugin_descriptors(_user=Depends(get_current_user)):
    items = list_plugin_descriptors()
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "count": len(items),
        "items": items,
    }


@router.get("/api/events/{aggregate_type}/{aggregate_id}")
def stream_events(aggregate_type: str, aggregate_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    events = load_events_after(db, aggregate_type, aggregate_id, 0)
    return [
        {
            "version": e.version,
            "event_type": e.event_type,
            "payload": e.payload,
            "metadata": e.metadata,
        }
        for e in events
    ]


@router.get("/api/metrics")
def runtime_metrics(_user=Depends(get_current_user)):
    return metrics_snapshot()


@router.get("/api/metrics/graph-rag")
def graph_rag_metrics(_user=Depends(get_current_user)):
    metrics = metrics_snapshot()
    requests = int(metrics.get("graph_rag_requests", 0) or 0)
    failures = int(metrics.get("graph_rag_failures", 0) or 0)
    failure_rate_pct = round((failures / requests) * 100.0, 2) if requests > 0 else 0.0
    context_p95 = int(metrics.get("graph_context_latency_ms_p95", 0) or 0)
    context_with_summary_p95 = int(metrics.get("graph_context_latency_ms_with_summary_p95", 0) or 0)
    context_without_summary_p95 = int(metrics.get("graph_context_latency_ms_without_summary_p95", 0) or 0)
    ingest_p95 = int(metrics.get("embedding_ingest_latency_ms_p95", 0) or 0)

    breaches: list[str] = []
    if context_with_summary_p95 > max(0, int(GRAPH_RAG_SLO_CONTEXT_WITH_SUMMARY_MS)):
        breaches.append("context_pack_with_summary_latency_p95_exceeded")
    if context_without_summary_p95 > max(0, int(GRAPH_RAG_SLO_CONTEXT_NO_SUMMARY_MS)):
        breaches.append("context_pack_without_summary_latency_p95_exceeded")
    if context_p95 > max(0, int(GRAPH_RAG_SLO_CONTEXT_WITH_SUMMARY_MS)):
        breaches.append("context_pack_latency_p95_exceeded")
    if ingest_p95 > max(0, int(GRAPH_RAG_SLO_EMBED_INGEST_P95_MS)):
        breaches.append("embedding_ingest_latency_p95_exceeded")

    embedding_total = int(metrics.get("embedding_requests_total", 0) or 0)
    embedding_context_errors = int(metrics.get("embedding_context_length_errors", 0) or 0)
    context_error_rate = round((embedding_context_errors / max(1, embedding_total)) * 100.0, 4) if embedding_total > 0 else 0.0
    if context_error_rate > float(GRAPH_RAG_SLO_EMBED_CONTEXT_ERROR_RATE_PCT):
        breaches.append("embedding_context_length_error_rate_exceeded")

    return {
        "requests": requests,
        "failures": failures,
        "failure_rate_pct": failure_rate_pct,
        "grounded_claim_ratio_pct": int(metrics.get("context_pack_grounded_claim_ratio", 0) or 0),
        "context_latency_ms": {
            "last": int(metrics.get("graph_context_latency_ms", 0) or 0),
            "p95": context_p95,
            "with_summary": {
                "last": int(metrics.get("graph_context_latency_ms_with_summary", 0) or 0),
                "p95": context_with_summary_p95,
            },
            "without_summary": {
                "last": int(metrics.get("graph_context_latency_ms_without_summary", 0) or 0),
                "p95": context_without_summary_p95,
            },
            "slo_without_summary_ms": max(0, int(GRAPH_RAG_SLO_CONTEXT_NO_SUMMARY_MS)),
            "slo_with_summary_ms": max(0, int(GRAPH_RAG_SLO_CONTEXT_WITH_SUMMARY_MS)),
        },
        "vector_retrieval_latency_ms": {
            "last": int(metrics.get("vector_retrieval_latency_ms", 0) or 0),
            "p95": int(metrics.get("vector_retrieval_latency_ms_p95", 0) or 0),
        },
        "embedding_ingest_latency_ms": {
            "last": int(metrics.get("embedding_ingest_latency_ms", 0) or 0),
            "p95": ingest_p95,
            "slo_p95_ms": max(0, int(GRAPH_RAG_SLO_EMBED_INGEST_P95_MS)),
        },
        "embedding_context_length_error_rate_pct": context_error_rate,
        "embedding_context_length_error_rate_slo_pct": float(GRAPH_RAG_SLO_EMBED_CONTEXT_ERROR_RATE_PCT),
        "canary": {
            "project_ids": sorted(GRAPH_RAG_CANARY_PROJECT_IDS),
            "workspace_ids": sorted(GRAPH_RAG_CANARY_WORKSPACE_IDS),
        },
        "slo_breaches": breaches,
    }


@router.get("/api/metrics/chat-prompt-segments")
def chat_prompt_segment_metrics(
    *,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    workspace_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
):
    query = (
        select(ChatMessage.usage_json)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatMessage.role == "assistant",
            ChatMessage.is_deleted == False,  # noqa: E712
            ChatSession.created_by == user.id,
            ChatSession.is_archived == False,  # noqa: E712
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(max(1, int(limit)))
    )
    if workspace_id:
        query = query.where(ChatSession.workspace_id == str(workspace_id).strip())
    if project_id:
        query = query.where(ChatSession.project_id == str(project_id).strip())
    rows = db.execute(query).all()

    mode_counts: dict[str, int] = {"full": 0, "resume": 0}
    segment_totals: dict[str, int] = {}
    segment_presence_counts: dict[str, int] = {}
    runs_analyzed = 0

    for (usage_json_raw,) in rows:
        raw = str(usage_json_raw or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        prompt_mode = str(payload.get("prompt_mode") or "").strip().lower()
        if prompt_mode in {"full", "resume"}:
            mode_counts[prompt_mode] = int(mode_counts.get(prompt_mode, 0)) + 1
        segment_chars = payload.get("prompt_segment_chars")
        if not isinstance(segment_chars, dict):
            continue
        runs_analyzed += 1
        for key_raw, value_raw in segment_chars.items():
            key = str(key_raw or "").strip()
            if not key:
                continue
            try:
                value = max(0, int(value_raw))
            except Exception:
                continue
            segment_totals[key] = int(segment_totals.get(key, 0)) + value
            segment_presence_counts[key] = int(segment_presence_counts.get(key, 0)) + 1

    segment_averages = {
        key: int(round(total / max(1, segment_presence_counts.get(key, 1))))
        for key, total in segment_totals.items()
    }

    return {
        "runs_analyzed": runs_analyzed,
        "runs_scanned": len(rows),
        "prompt_mode_counts": mode_counts,
        "segment_totals_chars": dict(sorted(segment_totals.items(), key=lambda item: item[1], reverse=True)),
        "segment_avg_chars_when_present": dict(
            sorted(segment_averages.items(), key=lambda item: item[1], reverse=True)
        ),
    }


@router.get("/api/metrics/task-automation-prompt-segments")
def task_automation_prompt_segment_metrics(
    *,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    workspace_id: str = Query(...),
    project_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
):
    ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    if project_id:
        ensure_project_access(db, workspace_id, project_id, user.id, {"Owner", "Admin", "Member", "Guest"})

    query = (
        select(StoredEvent.payload, StoredEvent.meta)
        .where(
            StoredEvent.aggregate_type == "Task",
            StoredEvent.event_type == "TaskAutomationCompleted",
        )
        .order_by(StoredEvent.occurred_at.desc())
        .limit(max(1, int(limit)))
    )
    rows = db.execute(query).all()

    mode_counts: dict[str, int] = {"full": 0, "resume": 0}
    segment_totals: dict[str, int] = {}
    segment_presence_counts: dict[str, int] = {}
    runs_analyzed = 0
    runs_scanned = 0

    for payload_raw, meta_raw in rows:
        try:
            meta = json.loads(str(meta_raw or "{}"))
        except Exception:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        if str(meta.get("workspace_id") or "").strip() != str(workspace_id).strip():
            continue
        if project_id and str(meta.get("project_id") or "").strip() != str(project_id).strip():
            continue
        runs_scanned += 1

        try:
            payload = json.loads(str(payload_raw or "{}"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        prompt_mode = str(payload.get("prompt_mode") or "").strip().lower()
        if prompt_mode in {"full", "resume"}:
            mode_counts[prompt_mode] = int(mode_counts.get(prompt_mode, 0)) + 1
        segment_chars = payload.get("prompt_segment_chars")
        if not isinstance(segment_chars, dict):
            continue
        runs_analyzed += 1
        for key_raw, value_raw in segment_chars.items():
            key = str(key_raw or "").strip()
            if not key:
                continue
            try:
                value = max(0, int(value_raw))
            except Exception:
                continue
            segment_totals[key] = int(segment_totals.get(key, 0)) + value
            segment_presence_counts[key] = int(segment_presence_counts.get(key, 0)) + 1

    segment_averages = {
        key: int(round(total / max(1, segment_presence_counts.get(key, 1))))
        for key, total in segment_totals.items()
    }

    return {
        "runs_analyzed": runs_analyzed,
        "runs_scanned": runs_scanned,
        "prompt_mode_counts": mode_counts,
        "segment_totals_chars": dict(sorted(segment_totals.items(), key=lambda item: item[1], reverse=True)),
        "segment_avg_chars_when_present": dict(
            sorted(segment_averages.items(), key=lambda item: item[1], reverse=True)
        ),
    }
