from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from features.bootstrap.cache import bootstrap_cache_status
from shared.serializers import to_iso_utc


def _now_iso_utc() -> str:
    return to_iso_utc(datetime.now(timezone.utc))


def _normalize_phase_row(raw: Any, *, phase_type: str, index: int) -> dict[str, Any]:
    item = dict(raw or {}) if isinstance(raw, dict) else {}
    name = str(item.get("name") or "").strip()
    condition = str(item.get("condition") or "").strip() or None
    return {
        "id": f"{phase_type}:{index}:{name or 'unknown'}",
        "name": name or "unknown",
        "phase_type": phase_type,
        "order": index,
        "condition": condition,
        "status": "configured",
    }


def build_bootstrap_plan_read_model() -> dict[str, Any]:
    from features.agents.capability_registry import build_bootstrap_phase_capabilities

    phases = build_bootstrap_phase_capabilities()
    startup = list(phases.get("startup") or [])
    shutdown = list(phases.get("shutdown") or [])
    startup_rows = [
        _normalize_phase_row(item, phase_type="startup", index=index)
        for index, item in enumerate(startup, start=1)
    ]
    shutdown_rows = [
        _normalize_phase_row(item, phase_type="shutdown", index=index)
        for index, item in enumerate(shutdown, start=1)
    ]

    discovery_cache = bootstrap_cache_status(key="bootstrap_discovery_registry")
    inventory_cache = bootstrap_cache_status(key="bootstrap_architecture_inventory_summary")

    return {
        "generated_at": _now_iso_utc(),
        "startup_phase_count": len(startup_rows),
        "shutdown_phase_count": len(shutdown_rows),
        "phases": {
            "startup": startup_rows,
            "shutdown": shutdown_rows,
        },
        "runtime_health": {
            "bootstrap_discovery_cache": {
                "has_payload": bool(discovery_cache.get("has_payload")),
                "expires_in_seconds": float(discovery_cache.get("expires_in_seconds") or 0.0),
                "hit_count": int(discovery_cache.get("hit_count") or 0),
                "miss_count": int(discovery_cache.get("miss_count") or 0),
            },
            "architecture_inventory_cache": {
                "has_payload": bool(inventory_cache.get("has_payload")),
                "expires_in_seconds": float(inventory_cache.get("expires_in_seconds") or 0.0),
                "hit_count": int(inventory_cache.get("hit_count") or 0),
                "miss_count": int(inventory_cache.get("miss_count") or 0),
            },
        },
    }
