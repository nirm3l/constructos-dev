#!/usr/bin/env python3
"""
GraphRAG QA runner.

Usage:
  docker compose exec -T task-app python scripts/qa_graph_rag.py
  python app/scripts/qa_graph_rag.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_USERNAME = os.getenv("QA_USERNAME", "admin")
DEFAULT_PASSWORD = os.getenv("QA_PASSWORD", "admin")


@dataclass
class Check:
    name: str
    ok: bool
    details: str = ""


class Api:
    def __init__(self, *, base_url: str, username: str, password: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout)
        login = self.client.post(
            self.base_url + "/api/auth/login",
            json={"username": username, "password": password},
        )
        login.raise_for_status()

    def close(self) -> None:
        self.client.close()

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        resp = self.client.get(self.base_url + path, params=params)
        resp.raise_for_status()
        return resp.json()

    def patch(self, path: str, payload: dict[str, Any]) -> Any:
        resp = self.client.patch(self.base_url + path, json=payload)
        resp.raise_for_status()
        return resp.json()


def _check_context_pack_shape(pack: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []
    checks.append(Check("context_pack.has_structure", isinstance(pack.get("structure"), dict)))
    checks.append(Check("context_pack.has_evidence", isinstance(pack.get("evidence"), list)))
    checks.append(Check("context_pack.has_mode", str(pack.get("mode") or "") in {"graph-only", "graph+vector"}))

    evidence = pack.get("evidence") or []
    evidence_ids = {str(row.get("evidence_id") or "").strip() for row in evidence if str(row.get("evidence_id") or "").strip()}
    checks.append(Check("evidence.ids_present", all(str(row.get("evidence_id") or "").strip() for row in evidence)))

    summary = pack.get("summary")
    if isinstance(summary, dict):
        key_points = summary.get("key_points") or []
        all_grounded = True
        for row in key_points:
            if not isinstance(row, dict):
                all_grounded = False
                break
            ids = [str(item).strip() for item in (row.get("evidence_ids") or []) if str(item).strip()]
            if not ids:
                all_grounded = False
                break
            if any(item not in evidence_ids for item in ids):
                all_grounded = False
                break
        checks.append(Check("summary.key_points_grounded", all_grounded))
    else:
        checks.append(Check("summary.optional", True, "summary missing (allowed fallback)"))
    return checks


def run(base_url: str, username: str, password: str, timeout: float) -> int:
    api = Api(base_url=base_url, username=username, password=password, timeout=timeout)
    checks: list[Check] = []
    try:
        bootstrap = api.get("/api/bootstrap")
        projects = bootstrap.get("projects") or []
        if not projects:
            print("No projects found in bootstrap payload.")
            return 2
        project = projects[0]
        project_id = str(project.get("id") or "")
        if not project_id:
            print("Bootstrap project has no id.")
            return 2

        pack = api.get(f"/api/projects/{project_id}/knowledge-graph/context-pack", params={"limit": 12})
        checks.extend(_check_context_pack_shape(pack))

        # Project-level toggling check.
        original_enabled = bool(project.get("embedding_enabled"))
        toggled = api.patch(f"/api/projects/{project_id}", {"embedding_enabled": (not original_enabled)})
        checks.append(
            Check(
                "project.toggle_embedding_enabled",
                bool(toggled.get("embedding_enabled")) is (not original_enabled),
            )
        )
        restored = api.patch(f"/api/projects/{project_id}", {"embedding_enabled": original_enabled})
        checks.append(
            Check(
                "project.restore_embedding_enabled",
                bool(restored.get("embedding_enabled")) is original_enabled,
            )
        )

        rag_metrics = api.get("/api/metrics/graph-rag")
        checks.append(Check("metrics.graph_rag.available", isinstance(rag_metrics, dict)))
        checks.append(Check("metrics.context_latency.p95_present", "context_latency_ms" in rag_metrics))
        checks.append(Check("metrics.grounded_ratio.present", "grounded_claim_ratio_pct" in rag_metrics))

        failed = [c for c in checks if not c.ok]
        for check in checks:
            status = "PASS" if check.ok else "FAIL"
            suffix = f" :: {check.details}" if check.details else ""
            print(f"{status} {check.name}{suffix}")

        if failed:
            print(f"\nGraphRAG QA failed: {len(failed)} check(s).")
            return 1
        print("\nGraphRAG QA passed.")
        return 0
    finally:
        api.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run GraphRAG QA checks against a running API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--user-id", default="", help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    return run(base_url=args.base_url, username=args.username, password=args.password, timeout=args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
