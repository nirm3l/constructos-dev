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


_metrics = RuntimeMetrics()
_lock = threading.Lock()


def incr(field: str, amount: int = 1) -> None:
    with _lock:
        value = getattr(_metrics, field)
        setattr(_metrics, field, value + amount)


def snapshot() -> dict[str, int]:
    with _lock:
        return {
            "commands_total": _metrics.commands_total,
            "commands_retried": _metrics.commands_retried,
            "command_conflicts": _metrics.command_conflicts,
            "sse_connections": _metrics.sse_connections,
            "notifications_emitted": _metrics.notifications_emitted,
        }
