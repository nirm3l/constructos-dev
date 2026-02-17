from __future__ import annotations

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


_metrics = RuntimeMetrics()
_lock = threading.Lock()


def incr(field: str, amount: int = 1) -> None:
    with _lock:
        value = getattr(_metrics, field)
        setattr(_metrics, field, value + amount)


def set_value(field: str, value: int) -> None:
    with _lock:
        setattr(_metrics, field, int(value))


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
        }
