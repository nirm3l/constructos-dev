from __future__ import annotations

import math
import threading
from dataclasses import dataclass


@dataclass
class RuntimeMetrics:
    commands_total: int = 0
    commands_retried: int = 0
    command_conflicts: int = 0
    sse_connections: int = 0
    notifications_emitted: int = 0
    graph_projection_events_processed: int = 0
    graph_projection_failures: int = 0
    graph_projection_lag_commits: int = 0
    graph_context_requests: int = 0
    graph_context_failures: int = 0
    graph_rag_requests: int = 0
    graph_rag_failures: int = 0
    vector_indexed_chunks: int = 0
    vector_retrieval_latency_ms: int = 0
    vector_retrieval_latency_ms_p95: int = 0
    graph_context_latency_ms: int = 0
    graph_context_latency_ms_p95: int = 0
    graph_context_latency_ms_with_summary: int = 0
    graph_context_latency_ms_with_summary_p95: int = 0
    graph_context_latency_ms_without_summary: int = 0
    graph_context_latency_ms_without_summary_p95: int = 0
    embedding_ingest_latency_ms: int = 0
    embedding_ingest_latency_ms_p95: int = 0
    embedding_requests_total: int = 0
    embedding_context_length_errors: int = 0
    context_pack_grounded_claim_ratio: int = 0


_metrics = RuntimeMetrics()
_lock = threading.Lock()
_samples: dict[str, list[int]] = {
    "vector_retrieval_latency_ms": [],
    "graph_context_latency_ms": [],
    "graph_context_latency_ms_with_summary": [],
    "graph_context_latency_ms_without_summary": [],
    "embedding_ingest_latency_ms": [],
}
_sample_window = 400


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1))
    return int(ordered[index])


def incr(field: str, amount: int = 1) -> None:
    with _lock:
        value = getattr(_metrics, field)
        setattr(_metrics, field, value + amount)


def set_value(field: str, value: int) -> None:
    with _lock:
        setattr(_metrics, field, int(value))


def observe(field: str, value: int) -> None:
    with _lock:
        intval = int(value)
        setattr(_metrics, field, intval)
        samples = _samples.get(field)
        if samples is None:
            return
        samples.append(intval)
        if len(samples) > _sample_window:
            del samples[0 : len(samples) - _sample_window]
        p95_field = f"{field}_p95"
        if hasattr(_metrics, p95_field):
            setattr(_metrics, p95_field, _p95(samples))


def snapshot() -> dict[str, int]:
    with _lock:
        return {
            "commands_total": _metrics.commands_total,
            "commands_retried": _metrics.commands_retried,
            "command_conflicts": _metrics.command_conflicts,
            "sse_connections": _metrics.sse_connections,
            "notifications_emitted": _metrics.notifications_emitted,
            "graph_projection_events_processed": _metrics.graph_projection_events_processed,
            "graph_projection_failures": _metrics.graph_projection_failures,
            "graph_projection_lag_commits": _metrics.graph_projection_lag_commits,
            "graph_context_requests": _metrics.graph_context_requests,
            "graph_context_failures": _metrics.graph_context_failures,
            "graph_rag_requests": _metrics.graph_rag_requests,
            "graph_rag_failures": _metrics.graph_rag_failures,
            "vector_indexed_chunks": _metrics.vector_indexed_chunks,
            "vector_retrieval_latency_ms": _metrics.vector_retrieval_latency_ms,
            "vector_retrieval_latency_ms_p95": _metrics.vector_retrieval_latency_ms_p95,
            "graph_context_latency_ms": _metrics.graph_context_latency_ms,
            "graph_context_latency_ms_p95": _metrics.graph_context_latency_ms_p95,
            "graph_context_latency_ms_with_summary": _metrics.graph_context_latency_ms_with_summary,
            "graph_context_latency_ms_with_summary_p95": _metrics.graph_context_latency_ms_with_summary_p95,
            "graph_context_latency_ms_without_summary": _metrics.graph_context_latency_ms_without_summary,
            "graph_context_latency_ms_without_summary_p95": _metrics.graph_context_latency_ms_without_summary_p95,
            "embedding_ingest_latency_ms": _metrics.embedding_ingest_latency_ms,
            "embedding_ingest_latency_ms_p95": _metrics.embedding_ingest_latency_ms_p95,
            "embedding_requests_total": _metrics.embedding_requests_total,
            "embedding_context_length_errors": _metrics.embedding_context_length_errors,
            "context_pack_grounded_claim_ratio": _metrics.context_pack_grounded_claim_ratio,
        }
