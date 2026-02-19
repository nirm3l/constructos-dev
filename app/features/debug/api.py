from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.core import get_current_user, get_db, load_events_after, metrics_snapshot
from shared.settings import (
    GRAPH_RAG_CANARY_PROJECT_IDS,
    GRAPH_RAG_CANARY_WORKSPACE_IDS,
    GRAPH_RAG_SLO_EMBED_CONTEXT_ERROR_RATE_PCT,
    GRAPH_RAG_SLO_CONTEXT_NO_SUMMARY_MS,
    GRAPH_RAG_SLO_CONTEXT_WITH_SUMMARY_MS,
    GRAPH_RAG_SLO_EMBED_INGEST_P95_MS,
)

router = APIRouter()


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
