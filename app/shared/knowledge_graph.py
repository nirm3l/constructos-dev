from __future__ import annotations

import json
import re
import threading
from time import perf_counter
from datetime import datetime, timezone
from collections.abc import Iterable
from typing import Any

import httpx

from .json_utils import parse_json_object
from .observability import incr, observe, set_value
from .settings import (
    CONTEXT_PACK_EVIDENCE_TOP_K,
    GRAPH_CONTEXT_MAX_HOPS,
    GRAPH_CONTEXT_MAX_TOKENS,
    GRAPH_RAG_CANARY_PROJECT_IDS,
    GRAPH_RAG_CANARY_WORKSPACE_IDS,
    GRAPH_RAG_ENABLED,
    GRAPH_RAG_SUMMARY_MODEL,
    KNOWLEDGE_GRAPH_ENABLED,
    NEO4J_DATABASE,
    OLLAMA_BASE_URL,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USERNAME,
    logger,
)
from .task_automation import normalize_execution_triggers
from .vector_store import resolve_project_embedding_runtime, search_project_chunks

try:  # pragma: no cover - exercised in integration only
    from neo4j import GraphDatabase
except Exception:  # pragma: no cover
    GraphDatabase = None

_DRIVER_LOCK = threading.Lock()
_NEO4J_DRIVER: Any | None = None
_NEO4J_MISSING_LOGGED = False
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False

_ENTITY_LABELS = {
    "workspace": "Workspace",
    "project": "Project",
    "template": "Template",
    "templateversion": "TemplateVersion",
    "template_version": "TemplateVersion",
    "task": "Task",
    "note": "Note",
    "chatsession": "ChatSession",
    "chat_session": "ChatSession",
    "chatmessage": "ChatMessage",
    "chat_message": "ChatMessage",
    "chatattachment": "ChatAttachment",
    "chat_attachment": "ChatAttachment",
    "comment": "Comment",
    "taskcomment": "Comment",
    "task_comment": "Comment",
    "specification": "Specification",
    "projectrule": "ProjectRule",
    "project_rule": "ProjectRule",
    "user": "User",
    "tag": "Tag",
    "boundedcontext": "BoundedContext",
    "bounded_context": "BoundedContext",
    "aggregate": "Aggregate",
    "command": "Command",
    "domainevent": "DomainEvent",
    "domain_event": "DomainEvent",
    "policy": "Policy",
    "readmodel": "ReadModel",
    "read_model": "ReadModel",
    "integrationboundary": "IntegrationBoundary",
    "integration_boundary": "IntegrationBoundary",
    "gameplayloop": "GameplayLoop",
    "gameplay_loop": "GameplayLoop",
    "inputscheme": "InputScheme",
    "input_scheme": "InputScheme",
    "assetpipeline": "AssetPipeline",
    "asset_pipeline": "AssetPipeline",
    "deviceprofile": "DeviceProfile",
    "device_profile": "DeviceProfile",
    "performancebudget": "PerformanceBudget",
    "performance_budget": "PerformanceBudget",
    "deploymenttarget": "DeploymentTarget",
    "deployment_target": "DeploymentTarget",
    "releasepipeline": "ReleasePipeline",
    "release_pipeline": "ReleasePipeline",
    "telemetrymetric": "TelemetryMetric",
    "telemetry_metric": "TelemetryMetric",
}


def graph_enabled() -> bool:
    return bool(KNOWLEDGE_GRAPH_ENABLED and NEO4J_URI)


def _project_canary_scope(project_id: str) -> tuple[str, str]:
    from .models import Project, SessionLocal

    pid = str(project_id or "").strip()
    if not pid:
        return "", ""
    try:
        with SessionLocal() as db:
            project = db.get(Project, pid)
            if project is None or project.is_deleted:
                return pid, ""
            return pid, str(project.workspace_id or "").strip()
    except Exception:
        return pid, ""


def graph_rag_enabled_for_scope(*, project_id: str, workspace_id: str | None = None) -> bool:
    if not GRAPH_RAG_ENABLED:
        return False
    if not GRAPH_RAG_CANARY_PROJECT_IDS and not GRAPH_RAG_CANARY_WORKSPACE_IDS:
        return True
    pid = str(project_id or "").strip()
    wid = str(workspace_id or "").strip()
    return bool((pid and pid in GRAPH_RAG_CANARY_PROJECT_IDS) or (wid and wid in GRAPH_RAG_CANARY_WORKSPACE_IDS))


def graph_rag_enabled_for_project(project_id: str) -> bool:
    pid, workspace_id = _project_canary_scope(project_id)
    return graph_rag_enabled_for_scope(project_id=pid, workspace_id=workspace_id)


def _resolve_context_pack_evidence_top_k(project_id: str, requested_limit: int) -> int:
    configured = int(CONTEXT_PACK_EVIDENCE_TOP_K or 10)
    pid = str(project_id or "").strip()
    if pid:
        try:
            from .models import Project, SessionLocal

            with SessionLocal() as db:
                project = db.get(Project, pid)
                if project is not None and not project.is_deleted and project.context_pack_evidence_top_k is not None:
                    configured = int(project.context_pack_evidence_top_k)
        except Exception as exc:
            logger.warning("Unable to resolve project evidence top-k project_id=%s: %s", pid, exc)
    configured = max(1, min(configured, 40))
    return max(1, min(configured, int(requested_limit or configured), 40))


def normalize_entity_label(entity_type: str) -> str:
    key = str(entity_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in _ENTITY_LABELS:
        return _ENTITY_LABELS[key]
    compact = key.replace("_", "")
    if compact in _ENTITY_LABELS:
        return _ENTITY_LABELS[compact]
    raise ValueError(f"Unsupported entity_type: {entity_type}")


def _get_driver() -> Any | None:
    global _NEO4J_DRIVER, _NEO4J_MISSING_LOGGED
    if not graph_enabled():
        return None
    if GraphDatabase is None:
        if not _NEO4J_MISSING_LOGGED:
            logger.warning("Knowledge graph enabled but neo4j dependency is missing.")
            _NEO4J_MISSING_LOGGED = True
        return None
    with _DRIVER_LOCK:
        if _NEO4J_DRIVER is not None:
            return _NEO4J_DRIVER
        auth = (NEO4J_USERNAME, NEO4J_PASSWORD) if NEO4J_USERNAME else None
        _NEO4J_DRIVER = GraphDatabase.driver(NEO4J_URI, auth=auth) if auth else GraphDatabase.driver(NEO4J_URI)
        return _NEO4J_DRIVER


def close_knowledge_graph_driver() -> None:
    global _NEO4J_DRIVER, _SCHEMA_READY
    with _DRIVER_LOCK:
        drv = _NEO4J_DRIVER
        _NEO4J_DRIVER = None
    if drv is not None:
        try:
            drv.close()
        except Exception:
            pass
    with _SCHEMA_LOCK:
        _SCHEMA_READY = False


def require_graph_available() -> None:
    if not graph_enabled():
        raise RuntimeError("Knowledge graph is disabled")
    if _get_driver() is None:
        raise RuntimeError("Knowledge graph is unavailable")


def _session_execute_write(session: Any, fn, *args):
    if hasattr(session, "execute_write"):
        return session.execute_write(fn, *args)
    return session.write_transaction(fn, *args)


def _session_execute_read(session: Any, fn, *args):
    if hasattr(session, "execute_read"):
        return session.execute_read(fn, *args)
    return session.read_transaction(fn, *args)


def ensure_graph_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    require_graph_available()
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        statements = [
            "CREATE CONSTRAINT workspace_id_unique IF NOT EXISTS FOR (n:Workspace) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT project_id_unique IF NOT EXISTS FOR (n:Project) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT template_id_unique IF NOT EXISTS FOR (n:Template) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT template_version_id_unique IF NOT EXISTS FOR (n:TemplateVersion) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT task_id_unique IF NOT EXISTS FOR (n:Task) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT note_id_unique IF NOT EXISTS FOR (n:Note) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT chat_session_id_unique IF NOT EXISTS FOR (n:ChatSession) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT chat_message_id_unique IF NOT EXISTS FOR (n:ChatMessage) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT chat_attachment_id_unique IF NOT EXISTS FOR (n:ChatAttachment) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT specification_id_unique IF NOT EXISTS FOR (n:Specification) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT project_rule_id_unique IF NOT EXISTS FOR (n:ProjectRule) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT bounded_context_id_unique IF NOT EXISTS FOR (n:BoundedContext) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT aggregate_id_unique IF NOT EXISTS FOR (n:Aggregate) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT command_id_unique IF NOT EXISTS FOR (n:Command) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT domain_event_id_unique IF NOT EXISTS FOR (n:DomainEvent) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT policy_id_unique IF NOT EXISTS FOR (n:Policy) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT read_model_id_unique IF NOT EXISTS FOR (n:ReadModel) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (n:User) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT tag_value_unique IF NOT EXISTS FOR (n:Tag) REQUIRE n.value IS UNIQUE",
            "CREATE INDEX project_workspace_idx IF NOT EXISTS FOR (n:Project) ON (n.workspace_id)",
            "CREATE INDEX template_key_idx IF NOT EXISTS FOR (n:Template) ON (n.key)",
            "CREATE INDEX task_project_idx IF NOT EXISTS FOR (n:Task) ON (n.project_id)",
            "CREATE INDEX note_project_idx IF NOT EXISTS FOR (n:Note) ON (n.project_id)",
            "CREATE INDEX chat_session_project_idx IF NOT EXISTS FOR (n:ChatSession) ON (n.project_id)",
            "CREATE INDEX chat_message_project_idx IF NOT EXISTS FOR (n:ChatMessage) ON (n.project_id)",
            "CREATE INDEX chat_attachment_project_idx IF NOT EXISTS FOR (n:ChatAttachment) ON (n.project_id)",
            "CREATE INDEX specification_project_idx IF NOT EXISTS FOR (n:Specification) ON (n.project_id)",
            "CREATE INDEX project_rule_project_idx IF NOT EXISTS FOR (n:ProjectRule) ON (n.project_id)",
            "CREATE INDEX bounded_context_project_idx IF NOT EXISTS FOR (n:BoundedContext) ON (n.project_id)",
            "CREATE INDEX aggregate_project_idx IF NOT EXISTS FOR (n:Aggregate) ON (n.project_id)",
            "CREATE INDEX command_project_idx IF NOT EXISTS FOR (n:Command) ON (n.project_id)",
            "CREATE INDEX domain_event_project_idx IF NOT EXISTS FOR (n:DomainEvent) ON (n.project_id)",
            "CREATE INDEX policy_project_idx IF NOT EXISTS FOR (n:Policy) ON (n.project_id)",
            "CREATE INDEX read_model_project_idx IF NOT EXISTS FOR (n:ReadModel) ON (n.project_id)",
        ]
        driver = _get_driver()
        if driver is None:
            raise RuntimeError("Knowledge graph is unavailable")
        session_kwargs = {"database": NEO4J_DATABASE} if NEO4J_DATABASE else {}
        with driver.session(**session_kwargs) as session:
            for stmt in statements:
                _session_execute_write(session, lambda tx, s=stmt: list(tx.run(s)))
        _SCHEMA_READY = True


def run_graph_query(cypher: str, params: dict[str, Any] | None = None, *, write: bool = False) -> list[dict[str, Any]]:
    require_graph_available()
    if write:
        ensure_graph_schema()
    driver = _get_driver()
    if driver is None:
        raise RuntimeError("Knowledge graph is unavailable")
    payload = dict(params or {})

    def _runner(tx):
        records = tx.run(cypher, **payload)
        return [dict(record.data()) for record in records]

    session_kwargs = {"database": NEO4J_DATABASE} if NEO4J_DATABASE else {}
    with driver.session(**session_kwargs) as session:
        if write:
            return _session_execute_write(session, _runner)
        return _session_execute_read(session, _runner)


def _sanitize_rel_types(rel_types: Iterable[str] | None) -> list[str]:
    if not rel_types:
        return []
    out: list[str] = []
    for raw in rel_types:
        rel = str(raw or "").strip().upper()
        if not rel:
            continue
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", rel):
            continue
        if rel not in out:
            out.append(rel)
    return out


def graph_get_project_overview(project_id: str, *, top_limit: int = 8) -> dict[str, Any]:
    require_graph_available()
    limit = max(1, min(int(top_limit or 8), 30))
    project_rows = run_graph_query(
        """
        MATCH (p:Project {id:$project_id})
        RETURN p.id AS project_id, coalesce(p.name, p.title, '') AS project_name
        LIMIT 1
        """,
        {"project_id": project_id},
    )
    if not project_rows:
        return {
            "project_id": project_id,
            "project_name": "",
            "counts": {"tasks": 0, "notes": 0, "specifications": 0, "project_rules": 0, "comments": 0},
            "top_tags": [],
            "top_relationships": [],
        }

    counts_rows = run_graph_query(
        """
        MATCH (p:Project {id:$project_id})
        OPTIONAL MATCH (t:Task)
        WHERE coalesce(t.is_deleted, false) = false
          AND (
            coalesce(t.project_id, '') = $project_id
            OR EXISTS { MATCH (t)-[:IN_PROJECT]->(p) }
          )
        WITH p, count(DISTINCT t) AS task_count
        OPTIONAL MATCH (n:Note)
        WHERE coalesce(n.is_deleted, false) = false
          AND (
            coalesce(n.project_id, '') = $project_id
            OR EXISTS { MATCH (n)-[:IN_PROJECT]->(p) }
          )
        WITH p, task_count, count(DISTINCT n) AS note_count
        OPTIONAL MATCH (s:Specification)
        WHERE coalesce(s.is_deleted, false) = false
          AND (
            coalesce(s.project_id, '') = $project_id
            OR EXISTS { MATCH (s)-[:IN_PROJECT]->(p) }
          )
        WITH p, task_count, note_count, count(DISTINCT s) AS specification_count
        OPTIONAL MATCH (r:ProjectRule)
        WHERE coalesce(r.is_deleted, false) = false
          AND (
            coalesce(r.project_id, '') = $project_id
            OR EXISTS { MATCH (r)-[:IN_PROJECT]->(p) }
          )
        WITH p, task_count, note_count, specification_count, count(DISTINCT r) AS rule_count
        OPTIONAL MATCH (tc:Task)-[cr:COMMENTED_BY]->(:User)
        WHERE coalesce(tc.is_deleted, false) = false
          AND (
            coalesce(tc.project_id, '') = $project_id
            OR EXISTS { MATCH (tc)-[:IN_PROJECT]->(p) }
          )
        RETURN task_count, note_count, specification_count, rule_count, coalesce(sum(coalesce(cr.count, 1)), 0) AS comment_count
        """,
        {"project_id": project_id},
    )
    counts = counts_rows[0] if counts_rows else {}

    top_tags = run_graph_query(
        """
        MATCH (p:Project {id:$project_id})
        MATCH (n)-[:TAGGED_WITH]->(tag:Tag)
        WHERE coalesce(n.is_deleted, false) = false
          AND (
            coalesce(n.project_id, '') = $project_id
            OR EXISTS { MATCH (n)-[:IN_PROJECT]->(p) }
          )
        RETURN tag.value AS tag, count(*) AS usage
        ORDER BY usage DESC, tag ASC
        LIMIT $limit
        """,
        {"project_id": project_id, "limit": limit},
    )

    top_relationships = run_graph_query(
        """
        MATCH (p:Project {id:$project_id})
        MATCH (n)-[r]-()
        WHERE coalesce(n.is_deleted, false) = false
          AND (
            coalesce(n.project_id, '') = $project_id
            OR EXISTS { MATCH (n)-[:IN_PROJECT]->(p) }
          )
        RETURN type(r) AS relationship, count(r) AS count
        ORDER BY count DESC, relationship ASC
        LIMIT $limit
        """,
        {"project_id": project_id, "limit": limit},
    )

    first = project_rows[0]
    return {
        "project_id": first.get("project_id") or project_id,
        "project_name": first.get("project_name") or "",
        "counts": {
            "tasks": int(counts.get("task_count") or 0),
            "notes": int(counts.get("note_count") or 0),
            "specifications": int(counts.get("specification_count") or 0),
            "project_rules": int(counts.get("rule_count") or 0),
            "comments": int(counts.get("comment_count") or 0),
        },
        "top_tags": [{"tag": str(row.get("tag") or ""), "usage": int(row.get("usage") or 0)} for row in top_tags],
        "top_relationships": [
            {"relationship": str(row.get("relationship") or ""), "count": int(row.get("count") or 0)}
            for row in top_relationships
        ],
    }


def graph_get_project_subgraph(
    project_id: str,
    *,
    limit_nodes: int = 48,
    limit_edges: int = 160,
) -> dict[str, Any]:
    require_graph_available()
    safe_nodes = max(8, min(int(limit_nodes or 48), 120))
    safe_edges = max(8, min(int(limit_edges or 160), 320))

    project_rows = run_graph_query(
        """
        MATCH (p:Project {id:$project_id})
        RETURN p.id AS project_id, coalesce(p.name, '') AS project_name
        LIMIT 1
        """,
        {"project_id": project_id},
    )
    if not project_rows:
        return {
            "project_id": project_id,
            "project_name": "",
            "node_count": 0,
            "edge_count": 0,
            "nodes": [],
            "edges": [],
        }

    project_name = str(project_rows[0].get("project_name") or "").strip()
    if not project_name:
        # Fallback to SQL source-of-truth when the graph node exists but lacks a display name.
        from .models import Project, SessionLocal

        with SessionLocal() as db:
            project_row = db.get(Project, project_id)
            if project_row is not None and not bool(project_row.is_deleted):
                project_name = str(project_row.name or "").strip()
    resource_rows = run_graph_query(
        """
        MATCH (p:Project {id:$project_id})
        MATCH (n)
        WHERE coalesce(n.is_deleted, false) = false
          AND n.id IS NOT NULL
          AND n.id <> $project_id
          AND (
            coalesce(n.project_id, '') = $project_id
            OR EXISTS { MATCH (n)-[:IN_PROJECT]->(p) }
          )
        RETURN DISTINCT
          head(labels(n)) AS entity_type,
          n.id AS entity_id,
          coalesce(n.title, n.name, n.username, n.value, n.id) AS title
        ORDER BY title ASC
        LIMIT $limit
        """,
        {"project_id": project_id, "limit": max(200, safe_nodes * 8)},
    )

    buckets: dict[str, list[dict[str, str]]] = {}
    for row in resource_rows:
        entity_id = str(row.get("entity_id") or "").strip()
        if not entity_id:
            continue
        entity_type = str(row.get("entity_type") or "Entity").strip() or "Entity"
        bucket_key = entity_type.lower()
        buckets.setdefault(bucket_key, []).append(
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "title": str(row.get("title") or entity_id),
            }
        )
    for values in buckets.values():
        values.sort(key=lambda item: str(item.get("title") or "").lower())

    preferred_order = [
        "specification",
        "comment",
        "task",
        "note",
        "chatmessage",
        "chatattachment",
        "chatsession",
        "projectrule",
        "user",
        "tag",
        "workspace",
    ]
    ordered_types = preferred_order + sorted([key for key in buckets.keys() if key not in preferred_order])
    selected_rows: list[dict[str, str]] = []
    comment_slot_reserve = min(8, max(2, safe_nodes // 5))
    max_resource_nodes = max(0, safe_nodes - 1 - comment_slot_reserve)
    while len(selected_rows) < max_resource_nodes and any(buckets.get(key) for key in ordered_types):
        for key in ordered_types:
            if len(selected_rows) >= max_resource_nodes:
                break
            queue = buckets.get(key) or []
            if not queue:
                continue
            selected_rows.append(queue.pop(0))
            buckets[key] = queue

    nodes: list[dict[str, Any]] = [
        {
            "entity_type": "Project",
            "entity_id": project_id,
            "title": project_name or project_id,
            "degree": 0,
        }
    ]
    seen_ids = {project_id}
    for row in selected_rows:
        entity_id = str(row.get("entity_id") or "").strip()
        if not entity_id or entity_id in seen_ids:
            continue
        seen_ids.add(entity_id)
        nodes.append(
            {
                "entity_type": str(row.get("entity_type") or "Entity"),
                "entity_id": entity_id,
                "title": str(row.get("title") or entity_id),
                "degree": 0,
            }
            )

    synthetic_edges: list[dict[str, str]] = []
    task_ids = [str(node.get("entity_id") or "") for node in nodes if str(node.get("entity_type") or "").lower() == "task"]
    remaining_node_slots = max(0, safe_nodes - len(nodes))
    if task_ids:
        from .models import SessionLocal, Task, TaskComment

        if remaining_node_slots:
            thread_previews: dict[str, str] = {}
            with SessionLocal() as db:
                comment_rows_sql = (
                    db.query(TaskComment.task_id, TaskComment.user_id, TaskComment.body)
                    .filter(TaskComment.task_id.in_(task_ids))
                    .order_by(TaskComment.created_at.desc(), TaskComment.id.desc())
                    .limit(2000)
                    .all()
                )
                for task_id_raw, user_id_raw, body_raw in comment_rows_sql:
                    task_id_text = str(task_id_raw or "").strip()
                    user_id_text = str(user_id_raw or "").strip()
                    if not task_id_text or not user_id_text:
                        continue
                    thread_key = f"{task_id_text}:{user_id_text}"
                    if thread_key in thread_previews:
                        continue
                    preview = _truncate_snippet(str(body_raw or ""), max_chars=72)
                    if preview:
                        thread_previews[thread_key] = preview

            comment_rows = run_graph_query(
                """
                MATCH (t:Task)-[r:COMMENTED_BY]->(u:User)
                WHERE t.id IN $task_ids
                  AND coalesce(t.is_deleted, false) = false
                RETURN
                  t.id AS task_id,
                  u.id AS user_id,
                  coalesce(u.username, u.name, u.id) AS author_label,
                  coalesce(r.count, 1) AS comment_count
                ORDER BY comment_count DESC, author_label ASC
                LIMIT $limit
                """,
                {"task_ids": task_ids, "limit": min(remaining_node_slots, safe_edges, 80)},
            )
            for row in comment_rows:
                if len(nodes) >= safe_nodes:
                    break
                task_id = str(row.get("task_id") or "").strip()
                user_id = str(row.get("user_id") or "").strip()
                if not task_id or not user_id:
                    continue
                comment_id = f"comment-thread:{task_id}:{user_id}"
                if comment_id in seen_ids:
                    continue
                count = max(1, int(row.get("comment_count") or 1))
                author = str(row.get("author_label") or user_id).strip() or user_id
                label = thread_previews.get(f"{task_id}:{user_id}") or f"{author} · {count} comment{'s' if count != 1 else ''}"
                seen_ids.add(comment_id)
                nodes.append(
                    {
                        "entity_type": "Comment",
                        "entity_id": comment_id,
                        "title": label,
                        "degree": 0,
                    }
                )
                synthetic_edges.append(
                    {
                        "source_entity_id": comment_id,
                        "target_entity_id": task_id,
                        "relationship": "COMMENT_ACTIVITY",
                    }
                )
            remaining_node_slots = max(0, safe_nodes - len(nodes))

        task_id_set = {tid for tid in task_ids if tid}
        task_dependency_keys: set[tuple[str, str, str]] = set()
        with SessionLocal() as db:
            task_rows_sql = (
                db.query(Task.id, Task.execution_triggers)
                .filter(Task.id.in_(task_ids))
                .filter(Task.project_id == project_id)
                .filter(Task.is_deleted.is_(False))
                .all()
            )

        for dependent_task_raw, execution_triggers_raw in task_rows_sql:
            dependent_task_id = str(dependent_task_raw or "").strip()
            if not dependent_task_id:
                continue
            triggers = normalize_execution_triggers(execution_triggers_raw)
            for trigger in triggers:
                if not isinstance(trigger, dict):
                    continue
                if str(trigger.get("kind") or "").strip().lower() != "status_change":
                    continue
                if not bool(trigger.get("enabled", True)):
                    continue
                if str(trigger.get("scope") or "").strip().lower() != "external":
                    continue
                selector_raw = trigger.get("selector")
                selector = selector_raw if isinstance(selector_raw, dict) else {}
                source_ids_raw = [
                    *(selector.get("task_ids") or []),
                    *(trigger.get("source_task_ids") or []),
                ]
                source_ids = []
                seen_source_ids: set[str] = set()
                for source_raw in source_ids_raw:
                    source_id = str(source_raw or "").strip()
                    if not source_id or source_id in seen_source_ids:
                        continue
                    seen_source_ids.add(source_id)
                    if source_id == dependent_task_id:
                        continue
                    if source_id not in task_id_set:
                        continue
                    source_ids.append(source_id)
                for source_id in source_ids:
                    dep_key = (source_id, dependent_task_id, "DEPENDS_ON_TASK_STATUS")
                    if dep_key in task_dependency_keys:
                        continue
                    task_dependency_keys.add(dep_key)
                    synthetic_edges.append(
                        {
                            "source_entity_id": source_id,
                            "target_entity_id": dependent_task_id,
                            "relationship": "DEPENDS_ON_TASK_STATUS",
                        }
                    )

    if remaining_node_slots and any(buckets.get(key) for key in ordered_types):
        while remaining_node_slots > 0 and any(buckets.get(key) for key in ordered_types):
            for key in ordered_types:
                if remaining_node_slots <= 0:
                    break
                queue = buckets.get(key) or []
                while queue:
                    row = queue.pop(0)
                    entity_id = str(row.get("entity_id") or "").strip()
                    if not entity_id or entity_id in seen_ids:
                        continue
                    seen_ids.add(entity_id)
                    nodes.append(
                        {
                            "entity_type": str(row.get("entity_type") or "Entity"),
                            "entity_id": entity_id,
                            "title": str(row.get("title") or entity_id),
                            "degree": 0,
                        }
                    )
                    remaining_node_slots -= 1
                    break
                buckets[key] = queue

    node_ids = [str(n["entity_id"]) for n in nodes if str(n.get("entity_id", "")).strip()]
    if len(node_ids) <= 1:
        return {
            "project_id": project_id,
            "project_name": project_name,
            "node_count": len(nodes),
            "edge_count": 0,
            "nodes": nodes,
            "edges": [],
        }

    edge_rows = run_graph_query(
        """
        MATCH (a)-[r]-(b)
        WHERE a.id IN $node_ids
          AND b.id IN $node_ids
          AND a.id <> b.id
        RETURN a.id AS source_entity_id, b.id AS target_entity_id, type(r) AS relationship
        LIMIT $limit
        """,
        {
            "node_ids": node_ids,
            "limit": safe_edges * 4,
        },
    )

    dedup: set[tuple[str, str, str]] = set()
    edges: list[dict[str, str]] = []
    degree_map: dict[str, int] = {node_id: 0 for node_id in node_ids}
    directional_relationships = {"DEPENDS_ON_TASK_STATUS"}

    for row in edge_rows:
        source = str(row.get("source_entity_id") or "").strip()
        target = str(row.get("target_entity_id") or "").strip()
        relationship = str(row.get("relationship") or "RELATED").strip() or "RELATED"
        if not source or not target or source == target:
            continue
        if relationship not in directional_relationships and source > target:
            source, target = target, source
        if relationship in directional_relationships:
            key = (source, target, relationship)
        else:
            lhs, rhs = (source, target) if source <= target else (target, source)
            key = (lhs, rhs, relationship)
        if key in dedup:
            continue
        dedup.add(key)
        edges.append(
            {
                "source_entity_id": source,
                "target_entity_id": target,
                "relationship": relationship,
            }
        )
        degree_map[source] = int(degree_map.get(source) or 0) + 1
        degree_map[target] = int(degree_map.get(target) or 0) + 1
        if len(edges) >= safe_edges:
            break

    for edge in synthetic_edges:
        if len(edges) >= safe_edges:
            break
        source = str(edge.get("source_entity_id") or "").strip()
        target = str(edge.get("target_entity_id") or "").strip()
        relationship = str(edge.get("relationship") or "RELATED").strip() or "RELATED"
        if not source or not target or source == target:
            continue
        if relationship in directional_relationships:
            key = (source, target, relationship)
        else:
            lhs, rhs = (source, target) if source <= target else (target, source)
            key = (lhs, rhs, relationship)
        if key in dedup:
            continue
        dedup.add(key)
        edges.append(
            {
                "source_entity_id": source,
                "target_entity_id": target,
                "relationship": relationship,
            }
        )
        degree_map[source] = int(degree_map.get(source) or 0) + 1
        degree_map[target] = int(degree_map.get(target) or 0) + 1

    for node in nodes:
        node_id = str(node.get("entity_id") or "")
        node["degree"] = int(degree_map.get(node_id) or 0)

    return {
        "project_id": project_id,
        "project_name": project_name,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }


_EVENT_STORMING_COMPONENT_LABELS = [
    "BoundedContext",
    "Aggregate",
    "Command",
    "DomainEvent",
    "Policy",
    "ReadModel",
]
_EVENT_STORMING_ARTIFACT_LABELS = ["Task", "Note", "Specification"]


def event_storming_get_project_overview(project_id: str) -> dict[str, Any]:
    require_graph_available()
    from sqlalchemy import func, select

    from .models import ContextSessionState, EventStormingAnalysisJob, Note, Project, SessionLocal, Specification, Task

    project_rows = run_graph_query(
        """
        MATCH (p:Project {id:$project_id})
        RETURN p.id AS project_id, coalesce(p.name, '') AS project_name
        LIMIT 1
        """,
        {"project_id": project_id},
    )
    if not project_rows:
        return {
            "project_id": project_id,
            "project_name": "",
            "component_counts": {},
            "artifact_link_count": 0,
            "event_storming_enabled": True,
            "processing": {
                "artifact_total": 0,
                "processed": 0,
                "queued": 0,
                "running": 0,
                "failed": 0,
                "done": 0,
                "progress_pct": 0.0,
            },
        }

    component_counts: dict[str, int] = {}
    for label in _EVENT_STORMING_COMPONENT_LABELS:
        rows = run_graph_query(
            f"""
            MATCH (n:{label})
            WHERE coalesce(n.project_id, '') = $project_id
            RETURN count(n) AS count
            """,
            {"project_id": project_id},
        )
        component_counts[label] = int((rows[0] if rows else {}).get("count") or 0)

    link_rows = run_graph_query(
        """
        MATCH (a)-[r:RELATES_TO_ES]->(c)
        WHERE any(label IN labels(a) WHERE label IN $artifact_labels)
          AND any(label IN labels(c) WHERE label IN $component_labels)
          AND coalesce(c.project_id, '') = $project_id
        RETURN count(r) AS count
        """,
        {
            "project_id": project_id,
            "artifact_labels": _EVENT_STORMING_ARTIFACT_LABELS,
            "component_labels": _EVENT_STORMING_COMPONENT_LABELS,
        },
    )
    first = project_rows[0]
    processing = {
        "artifact_total": 0,
        "processed": 0,
        "queued": 0,
        "running": 0,
        "failed": 0,
        "done": 0,
        "progress_pct": 0.0,
    }
    event_storming_enabled = True
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if project is not None and not bool(project.is_deleted):
            event_storming_enabled = bool(getattr(project, "event_storming_enabled", True))
        frame_state = db.execute(
            select(ContextSessionState).where(
                ContextSessionState.project_id == project_id,
                ContextSessionState.scope_type == "event_storming_project",
                ContextSessionState.scope_id == project_id,
            )
        ).scalar_one_or_none()
        task_count = int(
            db.execute(
                select(func.count(Task.id)).where(Task.project_id == project_id, Task.is_deleted == False)
            ).scalar_one()
            or 0
        )
        note_count = int(
            db.execute(
                select(func.count(Note.id)).where(Note.project_id == project_id, Note.is_deleted == False)
            ).scalar_one()
            or 0
        )
        specification_count = int(
            db.execute(
                select(func.count(Specification.id)).where(Specification.project_id == project_id, Specification.is_deleted == False)
            ).scalar_one()
            or 0
        )
        status_rows = db.execute(
            select(EventStormingAnalysisJob.status, func.count(EventStormingAnalysisJob.id))
            .where(EventStormingAnalysisJob.project_id == project_id)
            .group_by(EventStormingAnalysisJob.status)
        ).all()
        status_counts = {str(status or "").strip().lower(): int(count or 0) for status, count in status_rows}
        artifact_total = task_count + note_count + specification_count
        done_count = int(status_counts.get("done", 0))
        processing = {
            "artifact_total": artifact_total,
            "processed": min(done_count, artifact_total) if artifact_total > 0 else done_count,
            "queued": int(status_counts.get("queued", 0)),
            "running": int(status_counts.get("running", 0)),
            "failed": int(status_counts.get("failed", 0)),
            "done": done_count,
            "progress_pct": (
                round((min(done_count, artifact_total) / artifact_total) * 100.0, 1)
                if artifact_total > 0
                else 100.0
            ),
        }
    context_frame = {
        "mode": str(getattr(frame_state, "last_frame_mode", "") or "").strip().lower() or None,
        "revision": str(getattr(frame_state, "context_revision", "") or "").strip() or None,
        "updated_at": (
            frame_state.last_frame_at.astimezone(timezone.utc).isoformat()
            if getattr(frame_state, "last_frame_at", None) is not None
            else None
        ),
    }
    return {
        "project_id": str(first.get("project_id") or project_id),
        "project_name": str(first.get("project_name") or ""),
        "component_counts": component_counts,
        "artifact_link_count": int((link_rows[0] if link_rows else {}).get("count") or 0),
        "event_storming_enabled": event_storming_enabled,
        "processing": processing,
        "context_frame": context_frame,
    }


def event_storming_get_project_subgraph(
    project_id: str,
    *,
    limit_nodes: int = 120,
    limit_edges: int = 220,
) -> dict[str, Any]:
    require_graph_available()
    safe_nodes = max(16, min(int(limit_nodes or 120), 300))
    safe_edges = max(16, min(int(limit_edges or 220), 500))

    project_rows = run_graph_query(
        """
        MATCH (p:Project {id:$project_id})
        RETURN p.id AS project_id, coalesce(p.name, '') AS project_name
        LIMIT 1
        """,
        {"project_id": project_id},
    )
    if not project_rows:
        return {
            "project_id": project_id,
            "project_name": "",
            "node_count": 0,
            "edge_count": 0,
            "nodes": [],
            "edges": [],
        }

    component_rows = run_graph_query(
        """
        MATCH (n)
        WHERE any(label IN labels(n) WHERE label IN $component_labels)
          AND coalesce(n.project_id, '') = $project_id
        RETURN n.id AS entity_id,
               head([label IN labels(n) WHERE label IN $component_labels]) AS entity_type,
               coalesce(n.title, n.name, n.id) AS title
        ORDER BY title ASC
        LIMIT $limit
        """,
        {
            "project_id": project_id,
            "component_labels": _EVENT_STORMING_COMPONENT_LABELS,
            "limit": safe_nodes,
        },
    )
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in component_rows:
        entity_id = str(row.get("entity_id") or "").strip()
        if not entity_id or entity_id in seen:
            continue
        seen.add(entity_id)
        nodes.append(
            {
                "entity_type": str(row.get("entity_type") or "Entity"),
                "entity_id": entity_id,
                "title": str(row.get("title") or entity_id),
                "degree": 0,
            }
        )

    component_ids = [str(item["entity_id"]) for item in nodes]
    if not component_ids:
        first = project_rows[0]
        return {
            "project_id": str(first.get("project_id") or project_id),
            "project_name": str(first.get("project_name") or ""),
            "node_count": 0,
            "edge_count": 0,
            "nodes": [],
            "edges": [],
        }

    component_edge_rows = run_graph_query(
        """
        MATCH (a)-[r]->(b)
        WHERE a.id IN $component_ids
          AND b.id IN $component_ids
          AND any(label IN labels(a) WHERE label IN $component_labels)
          AND any(label IN labels(b) WHERE label IN $component_labels)
        RETURN a.id AS source_entity_id, b.id AS target_entity_id, type(r) AS relationship
        ORDER BY relationship ASC
        LIMIT $limit
        """,
        {
            "component_ids": component_ids,
            "component_labels": _EVENT_STORMING_COMPONENT_LABELS,
            "limit": safe_edges,
        },
    )
    artifact_link_rows = run_graph_query(
        """
        MATCH (a)-[r:RELATES_TO_ES]->(c)
        WHERE c.id IN $component_ids
          AND any(label IN labels(a) WHERE label IN $artifact_labels)
        RETURN a.id AS source_entity_id,
               c.id AS target_entity_id,
               type(r) AS relationship,
               coalesce(r.review_status, 'candidate') AS review_status,
               coalesce(r.inference_method, 'heuristic') AS inference_method,
               toFloat(coalesce(r.confidence, 0.0)) AS confidence,
               head([label IN labels(a) WHERE label IN $artifact_labels]) AS artifact_label,
               coalesce(a.title, a.name, a.id) AS artifact_title
        ORDER BY artifact_title ASC
        LIMIT $limit
        """,
        {
            "component_ids": component_ids,
            "artifact_labels": _EVENT_STORMING_ARTIFACT_LABELS,
            "limit": safe_edges,
        },
    )

    for row in artifact_link_rows:
        artifact_id = str(row.get("source_entity_id") or "").strip()
        if not artifact_id or artifact_id in seen:
            continue
        seen.add(artifact_id)
        nodes.append(
            {
                "entity_type": str(row.get("artifact_label") or "Entity"),
                "entity_id": artifact_id,
                "title": str(row.get("artifact_title") or artifact_id),
                "degree": 0,
            }
        )

    edges = [
        {
            "source_entity_id": str(row.get("source_entity_id") or ""),
            "target_entity_id": str(row.get("target_entity_id") or ""),
            "relationship": str(row.get("relationship") or "RELATED"),
            "review_status": str(row.get("review_status") or ""),
            "inference_method": str(row.get("inference_method") or ""),
            "confidence": float(row.get("confidence") or 0.0),
        }
        for row in [*component_edge_rows, *artifact_link_rows]
        if str(row.get("source_entity_id") or "").strip() and str(row.get("target_entity_id") or "").strip()
    ]
    degree_by_id: dict[str, int] = {}
    for edge in edges:
        source_id = str(edge["source_entity_id"])
        target_id = str(edge["target_entity_id"])
        degree_by_id[source_id] = degree_by_id.get(source_id, 0) + 1
        degree_by_id[target_id] = degree_by_id.get(target_id, 0) + 1
    for node in nodes:
        node_id = str(node.get("entity_id") or "")
        node["degree"] = int(degree_by_id.get(node_id, 0))

    first = project_rows[0]
    return {
        "project_id": str(first.get("project_id") or project_id),
        "project_name": str(first.get("project_name") or ""),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }


def event_storming_get_entity_links(
    *,
    project_id: str,
    entity_type: str,
    entity_id: str,
) -> dict[str, Any]:
    require_graph_available()
    label = normalize_entity_label(entity_type)
    if label not in _EVENT_STORMING_ARTIFACT_LABELS:
        raise ValueError("entity_type must be task, note, or specification")
    links = run_graph_query(
        f"""
        MATCH (a:{label} {{id:$entity_id}})-[r:RELATES_TO_ES]->(c)
        WHERE coalesce(c.project_id, '') = $project_id
          AND any(lbl IN labels(c) WHERE lbl IN $component_labels)
        RETURN c.id AS component_id,
               head([lbl IN labels(c) WHERE lbl IN $component_labels]) AS component_type,
               coalesce(c.title, c.name, c.id) AS component_title,
               coalesce(r.confidence, 0.0) AS confidence,
               coalesce(r.review_status, 'candidate') AS review_status,
               coalesce(r.inference_method, 'heuristic') AS inference_method,
               coalesce(r.updated_at, '') AS updated_at
        ORDER BY confidence DESC, component_title ASC
        """,
        {
            "project_id": project_id,
            "entity_id": entity_id,
            "component_labels": _EVENT_STORMING_COMPONENT_LABELS,
        },
    )
    return {
        "project_id": project_id,
        "entity_type": label,
        "entity_id": entity_id,
        "items": [
            {
                "component_id": str(item.get("component_id") or ""),
                "component_type": str(item.get("component_type") or ""),
                "component_title": str(item.get("component_title") or ""),
                "confidence": float(item.get("confidence") or 0.0),
                "review_status": str(item.get("review_status") or "candidate"),
                "inference_method": str(item.get("inference_method") or "heuristic"),
                "updated_at": str(item.get("updated_at") or ""),
            }
            for item in links
        ],
    }


def event_storming_get_component_links(
    *,
    project_id: str,
    component_id: str,
) -> dict[str, Any]:
    require_graph_available()
    rows = run_graph_query(
        """
        MATCH (c {id:$component_id})
        WHERE any(lbl IN labels(c) WHERE lbl IN $component_labels)
          AND coalesce(c.project_id, '') = $project_id
        OPTIONAL MATCH (a)-[r:RELATES_TO_ES]->(c)
        WHERE any(lbl IN labels(a) WHERE lbl IN $artifact_labels)
        RETURN head([lbl IN labels(c) WHERE lbl IN $component_labels]) AS component_type,
               coalesce(c.title, c.name, c.id) AS component_title,
               a.id AS entity_id,
               head([lbl IN labels(a) WHERE lbl IN $artifact_labels]) AS entity_type,
               coalesce(a.title, a.name, a.id) AS entity_title,
               coalesce(r.confidence, 0.0) AS confidence,
               coalesce(r.review_status, 'candidate') AS review_status,
               coalesce(r.inference_method, 'heuristic') AS inference_method,
               coalesce(r.updated_at, '') AS updated_at
        ORDER BY confidence DESC, entity_title ASC
        """,
        {
            "project_id": project_id,
            "component_id": component_id,
            "component_labels": _EVENT_STORMING_COMPONENT_LABELS,
            "artifact_labels": _EVENT_STORMING_ARTIFACT_LABELS,
        },
    )
    if not rows:
        return {
            "project_id": project_id,
            "component_id": component_id,
            "component_type": "",
            "component_title": "",
            "items": [],
        }
    first = rows[0]
    items = []
    for item in rows:
        entity_id = str(item.get("entity_id") or "").strip()
        if not entity_id:
            continue
        items.append(
            {
                "entity_id": entity_id,
                "entity_type": str(item.get("entity_type") or ""),
                "entity_title": str(item.get("entity_title") or entity_id),
                "confidence": float(item.get("confidence") or 0.0),
                "review_status": str(item.get("review_status") or "candidate"),
                "inference_method": str(item.get("inference_method") or "heuristic"),
                "updated_at": str(item.get("updated_at") or ""),
            }
        )
    return {
        "project_id": project_id,
        "component_id": component_id,
        "component_type": str(first.get("component_type") or ""),
        "component_title": str(first.get("component_title") or component_id),
        "items": items,
    }


def event_storming_set_link_review_status(
    *,
    project_id: str,
    entity_type: str,
    entity_id: str,
    component_id: str,
    review_status: str,
    confidence: float | None = None,
) -> dict[str, Any]:
    require_graph_available()
    artifact_label = normalize_entity_label(entity_type)
    if artifact_label not in _EVENT_STORMING_ARTIFACT_LABELS:
        raise ValueError("entity_type must be task, note, or specification")
    normalized_status = str(review_status or "").strip().lower()
    if normalized_status not in {"candidate", "approved", "rejected"}:
        raise ValueError("review_status must be one of: candidate, approved, rejected")
    confidence_value = None if confidence is None else max(0.0, min(1.0, float(confidence)))

    rows = run_graph_query(
        f"""
        MATCH (a:{artifact_label} {{id:$entity_id}})-[r:RELATES_TO_ES]->(c {{id:$component_id}})
        WHERE coalesce(c.project_id, '') = $project_id
        SET r.review_status = $review_status,
            r.inference_method = 'manual',
            r.updated_at = $updated_at,
            r.confidence = coalesce($confidence, r.confidence)
        RETURN
            a.id AS entity_id,
            c.id AS component_id,
            coalesce(r.review_status, 'candidate') AS review_status,
            coalesce(r.inference_method, 'manual') AS inference_method,
            coalesce(r.confidence, 0.0) AS confidence,
            coalesce(r.updated_at, '') AS updated_at
        LIMIT 1
        """,
        {
            "project_id": project_id,
            "entity_id": entity_id,
            "component_id": component_id,
            "review_status": normalized_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "confidence": confidence_value,
        },
        write=True,
    )
    if not rows:
        raise ValueError("RELATES_TO_ES link not found for provided entity/component")
    row = rows[0]
    return {
        "project_id": project_id,
        "entity_type": artifact_label,
        "entity_id": str(row.get("entity_id") or entity_id),
        "component_id": str(row.get("component_id") or component_id),
        "review_status": str(row.get("review_status") or normalized_status),
        "inference_method": str(row.get("inference_method") or "manual"),
        "confidence": float(row.get("confidence") or 0.0),
        "updated_at": str(row.get("updated_at") or ""),
    }


def graph_get_neighbors(
    *,
    project_id: str | None = None,
    entity_type: str,
    entity_id: str,
    rel_types: list[str] | None = None,
    depth: int = 1,
    limit: int = 50,
) -> dict[str, Any]:
    require_graph_available()
    label = normalize_entity_label(entity_type)
    max_depth = max(1, min(int(depth or 1), max(1, GRAPH_CONTEXT_MAX_HOPS)))
    safe_limit = max(1, min(int(limit or 50), 100))
    safe_rel_types = _sanitize_rel_types(rel_types)

    conditions = ["m.id IS NOT NULL"]
    params: dict[str, Any] = {
        "entity_id": entity_id,
        "limit": safe_limit,
        "rel_types": safe_rel_types,
        "project_id": project_id,
    }
    project_scope_clause = ""
    if str(project_id or "").strip():
        project_scope_clause = """
        WHERE (
          n.project_id = $project_id
          OR n.id = $project_id
          OR EXISTS { MATCH (n)-[:IN_PROJECT]->(:Project {id:$project_id}) }
        )
        """
        conditions.append(
            "("
            "m.project_id = $project_id "
            "OR m.id = $project_id "
            "OR EXISTS { MATCH (m)-[:IN_PROJECT]->(:Project {id:$project_id}) }"
            ")"
        )
    if safe_rel_types:
        conditions.append("all(rel IN rels WHERE type(rel) IN $rel_types)")
    where_clause = "WHERE " + " AND ".join(conditions)

    cypher = f"""
    MATCH (n:{label} {{id:$entity_id}})
    {project_scope_clause}
    MATCH path = (n)-[rels*1..{max_depth}]-(m)
    {where_clause}
    RETURN DISTINCT
      head(labels(m)) AS entity_type,
      m.id AS entity_id,
      coalesce(m.title, m.name, m.username, m.value, m.id) AS title,
      [rel IN rels | type(rel)] AS path_types
    LIMIT $limit
    """
    rows = run_graph_query(
        cypher,
        params,
    )
    return {
        "entity_type": label,
        "entity_id": entity_id,
        "depth": max_depth,
        "items": rows,
    }


def graph_find_related_resources(*, project_id: str, query: str, limit: int = 20) -> dict[str, Any]:
    require_graph_available()
    safe_limit = max(1, min(int(limit or 20), 100))
    q = str(query or "").strip().lower()
    if not q:
        return {"project_id": project_id, "query": "", "items": []}
    tokens = _extract_related_query_terms(q)
    if not tokens:
        tokens = [q]

    rows = run_graph_query(
        """
        MATCH (p:Project {id:$project_id})
        MATCH (n)
        WHERE (
            n.project_id = $project_id
            OR n.id = $project_id
            OR EXISTS { MATCH (n)-[:IN_PROJECT]->(p) }
          )
          AND coalesce(n.is_deleted, false) = false
        WITH
          n,
          toLower(trim(coalesce(n.title, ''))) AS title_text,
          toLower(trim(coalesce(n.description, ''))) AS description_text,
          toLower(trim(coalesce(n.body, ''))) AS body_text,
          toLower(trim(coalesce(n.name, ''))) AS name_text
        WITH
          n,
          title_text,
          description_text,
          body_text,
          name_text,
          [tok IN $tokens WHERE (
            title_text CONTAINS tok
            OR description_text CONTAINS tok
            OR body_text CONTAINS tok
            OR name_text CONTAINS tok
          )] AS matched_tokens,
          size([tok IN $tokens WHERE title_text CONTAINS tok]) AS title_hits
        WITH
          n,
          matched_tokens,
          title_hits,
          size(matched_tokens) AS token_hits,
          CASE
            WHEN title_text = $q THEN 400
            WHEN title_text STARTS WITH $q THEN 320
            WHEN title_text CONTAINS $q THEN 260
            WHEN description_text CONTAINS $q OR body_text CONTAINS $q OR name_text CONTAINS $q THEN 200
            ELSE 0
          END AS phrase_score
        WHERE phrase_score > 0 OR token_hits >= CASE WHEN size($tokens) >= 4 THEN 2 ELSE 1 END
        OPTIONAL MATCH (n)-[r]-()
        WITH
          n,
          matched_tokens,
          token_hits,
          title_hits,
          phrase_score,
          count(r) AS degree
        RETURN
          head(labels(n)) AS entity_type,
          n.id AS entity_id,
          coalesce(n.title, n.name, n.id) AS title,
          (
            phrase_score
            + (title_hits * 28)
            + (token_hits * 14)
            + CASE WHEN size($tokens) > 0 AND token_hits = size($tokens) THEN 25 ELSE 0 END
            + degree
          ) AS score,
          token_hits,
          title_hits,
          matched_tokens[0..8] AS matched_terms
        ORDER BY score DESC, token_hits DESC, title_hits DESC, title ASC
        LIMIT $limit
        """,
        {
            "project_id": project_id,
            "q": q,
            "tokens": tokens,
            "limit": safe_limit,
        },
    )
    return {
        "project_id": project_id,
        "query": query,
        "items": rows,
    }


def _extract_related_query_terms(query: str, *, max_terms: int = 16) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for raw in re.findall(r"[a-z0-9][a-z0-9._-]*", str(query or "").lower()):
        term = raw.strip("._-")
        if len(term) < 2:
            continue
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= max_terms:
            break
    return terms


def graph_get_dependency_path(
    *,
    project_id: str | None = None,
    from_entity_type: str,
    from_entity_id: str,
    to_entity_type: str,
    to_entity_id: str,
    max_depth: int = 4,
) -> dict[str, Any]:
    require_graph_available()
    from_label = normalize_entity_label(from_entity_type)
    to_label = normalize_entity_label(to_entity_type)
    depth = max(1, min(int(max_depth or 4), 8))

    project_scope_clause = ""
    if str(project_id or "").strip():
        project_scope_clause = """
        WHERE (
          a.project_id = $project_id
          OR a.id = $project_id
          OR EXISTS { MATCH (a)-[:IN_PROJECT]->(:Project {id:$project_id}) }
        )
        AND (
          b.project_id = $project_id
          OR b.id = $project_id
          OR EXISTS { MATCH (b)-[:IN_PROJECT]->(:Project {id:$project_id}) }
        )
        """

    cypher = f"""
    MATCH (a:{from_label} {{id:$from_id}}), (b:{to_label} {{id:$to_id}})
    {project_scope_clause}
    MATCH p = shortestPath((a)-[*..{depth}]-(b))
    RETURN
      [node IN nodes(p) | {{
        entity_type: head(labels(node)),
        entity_id: node.id,
        title: coalesce(node.title, node.name, node.username, node.value, node.id)
      }}] AS nodes,
      [rel IN relationships(p) | type(rel)] AS relationships,
      length(p) AS hops
    LIMIT 1
    """
    rows = run_graph_query(
        cypher,
        {
            "from_id": from_entity_id,
            "to_id": to_entity_id,
            "project_id": project_id,
        },
    )
    if not rows:
        return {
            "found": False,
            "from": {"entity_type": from_label, "entity_id": from_entity_id},
            "to": {"entity_type": to_label, "entity_id": to_entity_id},
            "hops": None,
            "nodes": [],
            "relationships": [],
        }
    first = rows[0]
    return {
        "found": True,
        "from": {"entity_type": from_label, "entity_id": from_entity_id},
        "to": {"entity_type": to_label, "entity_id": to_entity_id},
        "hops": int(first.get("hops") or 0),
        "nodes": first.get("nodes") or [],
        "relationships": first.get("relationships") or [],
    }


def _load_project_template_binding(project_id: str) -> dict[str, Any] | None:
    from .models import ProjectTemplateBinding, SessionLocal

    with SessionLocal() as db:
        binding = (
            db.query(ProjectTemplateBinding)
            .filter(ProjectTemplateBinding.project_id == project_id)
            .order_by(ProjectTemplateBinding.id.desc())
            .first()
        )
        if binding is None:
            return None
        return {
            "template_key": str(binding.template_key or "").strip(),
            "template_version": str(binding.template_version or "").strip(),
            "applied_by": str(binding.applied_by or "").strip(),
            "applied_at": binding.created_at.isoformat().replace("+00:00", "Z") if binding.created_at else None,
        }


def search_project_knowledge(
    *,
    project_id: str,
    query: str,
    limit: int = 20,
    focus_entity_type: str | None = None,
    focus_entity_id: str | None = None,
) -> dict[str, Any]:
    text_query = str(query or "").strip()
    if not text_query:
        return {
            "project_id": project_id,
            "query": "",
            "mode": "empty",
            "items": [],
            "gaps": ["query is empty"],
        }

    safe_limit = max(1, min(int(limit or 20), 50))
    focus_type = str(focus_entity_type or "").strip() or None
    focus_id = str(focus_entity_id or "").strip() or None
    gaps: list[str] = []

    candidate_scores: dict[tuple[str, str], float] = {}
    path_lookup: dict[tuple[str, str], list[str]] = {}
    focus_neighbors: list[dict[str, Any]] = []
    if focus_type and focus_id and graph_enabled():
        try:
            focus_neighbors = graph_get_neighbors(
                project_id=project_id,
                entity_type=focus_type,
                entity_id=focus_id,
                depth=min(max(1, GRAPH_CONTEXT_MAX_HOPS), 4),
                limit=min(max(10, safe_limit), 30),
            ).get("items") or []
        except Exception as exc:
            gaps.append(f"focus graph neighborhood is unavailable: {exc}")

    if graph_enabled():
        try:
            connected_resources = run_graph_query(
                """
                MATCH (p:Project {id:$project_id})
                MATCH (n)
                WHERE (
                    coalesce(n.project_id, '') = $project_id
                    OR EXISTS { MATCH (n)-[:IN_PROJECT]->(p) }
                  )
                  AND coalesce(n.is_deleted, false) = false
                OPTIONAL MATCH (n)-[r]-()
                RETURN
                  head(labels(n)) AS entity_type,
                  n.id AS entity_id,
                  count(DISTINCT r) AS degree
                ORDER BY degree DESC
                LIMIT $limit
                """,
                {
                    "project_id": project_id,
                    "limit": max(safe_limit * 5, 80),
                },
            )
            max_degree = max([int(item.get("degree") or 0) for item in connected_resources], default=1)
            for row in connected_resources:
                entity_type = str(row.get("entity_type") or "").strip()
                entity_id = str(row.get("entity_id") or "").strip()
                if not entity_type or not entity_id:
                    continue
                degree = int(row.get("degree") or 0)
                candidate_scores[(entity_type, entity_id)] = max(0.0, min(1.0, degree / max(1, max_degree)))

            for row in focus_neighbors:
                entity_type = str(row.get("entity_type") or "").strip()
                entity_id = str(row.get("entity_id") or "").strip()
                if not entity_type or not entity_id:
                    continue
                path_types = [str(item) for item in (row.get("path_types") or []) if str(item).strip()]
                score = 1.0 / max(1.0, float(len(path_types) + 1))
                prev = candidate_scores.get((entity_type, entity_id), 0.0)
                candidate_scores[(entity_type, entity_id)] = max(prev, score)

            if focus_type and focus_id and candidate_scores:
                dependency_paths = _build_dependency_paths(
                    project_id=project_id,
                    focus_entity_type=focus_type,
                    focus_entity_id=focus_id,
                    candidates=sorted(candidate_scores.keys(), key=lambda key: -candidate_scores.get(key, 0.0)),
                    max_items=min(12, max(4, safe_limit)),
                )
                path_lookup = _dependency_path_lookup(dependency_paths)
        except Exception as exc:
            gaps.append(f"graph signal is unavailable: {exc}")
    else:
        gaps.append("knowledge graph is disabled")

    from .models import SessionLocal

    with SessionLocal() as db:
        runtime = resolve_project_embedding_runtime(db, project_id)
        vector_candidates: list[dict[str, Any]] = []
        template_binding = _load_project_template_binding(project_id)
        template_key = str((template_binding or {}).get("template_key") or "").strip()
        expanded_query = " ".join([text_query, *_template_query_terms(template_key)]).strip() or text_query
        if runtime.enabled:
            try:
                vector_candidates = search_project_chunks(
                    db,
                    project_id=project_id,
                    query=expanded_query,
                    limit=max(safe_limit * 4, 16),
                    entity_filters=set(candidate_scores) or None,
                )
            except Exception as exc:
                gaps.append(f"vector retrieval failed: {exc}")
        else:
            gaps.append("vector retrieval is disabled for this project")

    items: list[dict[str, Any]] = []
    if vector_candidates:
        for candidate in vector_candidates:
            entity_type = str(candidate.get("entity_type") or "").strip() or "Entity"
            entity_id = str(candidate.get("entity_id") or "").strip() or "?"
            source_type = str(candidate.get("source_type") or "source").strip() or "source"
            snippet = _truncate_snippet(str(candidate.get("snippet") or ""))
            if not snippet:
                continue
            key = (entity_type, entity_id)
            graph_score = float(candidate_scores.get(key, 0.2 if not candidate_scores else 0.3))
            vector_similarity = float(candidate.get("vector_similarity") or 0.0)
            freshness = _score_freshness(candidate.get("source_updated_at"))
            entity_priority = _score_entity_priority(entity_type)
            graph_path = path_lookup.get(key, [entity_type])
            template_alignment = _template_alignment_score(
                template_key=template_key,
                entity_type=entity_type,
                source_type=source_type,
                graph_path=graph_path,
            )
            final_score = (
                (0.38 * vector_similarity)
                + (0.30 * graph_score)
                + (0.14 * freshness)
                + (0.08 * entity_priority)
                + (0.10 * template_alignment)
            )
            updated_at = _as_datetime_utc(candidate.get("source_updated_at"))
            items.append(
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "source_type": source_type,
                    "snippet": snippet,
                    "vector_similarity": round(vector_similarity, 4),
                    "graph_score": round(graph_score, 4),
                    "template_alignment": round(template_alignment, 4),
                    "final_score": float(final_score),
                    "graph_path": graph_path,
                    "updated_at": updated_at.isoformat().replace("+00:00", "Z") if updated_at else None,
                    "why_selected": "combined vector similarity, graph relevance, and template alignment",
                }
            )
    elif candidate_scores:
        graph_only_evidence = _load_graph_only_evidence_candidates(
            project_id=project_id,
            candidates=[
                {"entity_type": entity_type, "entity_id": entity_id, "graph_score": score}
                for (entity_type, entity_id), score in sorted(candidate_scores.items(), key=lambda item: -item[1])
            ],
            limit=max(safe_limit * 2, 10),
        )
        for candidate in graph_only_evidence:
            entity_type = str(candidate.get("entity_type") or "").strip() or "Entity"
            entity_id = str(candidate.get("entity_id") or "").strip() or "?"
            source_type = str(candidate.get("source_type") or "source").strip() or "source"
            snippet = _truncate_snippet(str(candidate.get("snippet") or ""))
            if not snippet:
                continue
            graph_score = float(candidate.get("graph_score") or 0.0)
            freshness = _score_freshness(candidate.get("source_updated_at"))
            entity_priority = _score_entity_priority(entity_type)
            key = (entity_type, entity_id)
            graph_path = path_lookup.get(key, [entity_type])
            template_alignment = _template_alignment_score(
                template_key=template_key,
                entity_type=entity_type,
                source_type=source_type,
                graph_path=graph_path,
            )
            final_score = (
                (0.62 * graph_score)
                + (0.16 * freshness)
                + (0.08 * entity_priority)
                + (0.14 * template_alignment)
            )
            updated_at = _as_datetime_utc(candidate.get("source_updated_at"))
            items.append(
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "source_type": source_type,
                    "snippet": snippet,
                    "vector_similarity": None,
                    "graph_score": round(graph_score, 4),
                    "template_alignment": round(template_alignment, 4),
                    "final_score": float(final_score),
                    "graph_path": graph_path,
                    "updated_at": updated_at.isoformat().replace("+00:00", "Z") if updated_at else None,
                    "why_selected": "graph fallback strengthened by template-aware ranking",
                }
            )
    else:
        gaps.append("no candidate knowledge entities found")

    items.sort(
        key=lambda item: (
            -float(item.get("final_score") or 0.0),
            -float(item.get("template_alignment") or 0.0),
            -float(item.get("graph_score") or 0.0),
            -float(item.get("vector_similarity") or 0.0),
            str(item.get("entity_type") or ""),
            str(item.get("entity_id") or ""),
        )
    )
    items = items[:safe_limit]
    for index, item in enumerate(items, start=1):
        item["rank"] = index
        item["final_score"] = round(float(item.get("final_score") or 0.0), 4)

    mode = "graph+vector"
    if items and all(item.get("vector_similarity") is None for item in items):
        mode = "graph-only"
    elif items and not candidate_scores:
        mode = "vector-only"
    elif not items:
        mode = "empty"

    response: dict[str, Any] = {
        "project_id": project_id,
        "query": text_query,
        "mode": mode,
        "items": items,
    }
    if focus_type and focus_id:
        response["focus"] = {"entity_type": focus_type, "entity_id": focus_id}
    if template_binding is not None:
        response["template"] = template_binding
    if gaps:
        response["gaps"] = gaps
    return response


def _as_datetime_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except Exception:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _truncate_snippet(text: str, max_chars: int = 260) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def _score_freshness(source_updated_at: Any) -> float:
    dt = _as_datetime_utc(source_updated_at)
    if dt is None:
        return 0.45
    age_hours = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    if age_hours <= 24:
        return 1.0
    if age_hours <= 72:
        return 0.85
    if age_hours <= 7 * 24:
        return 0.7
    if age_hours <= 30 * 24:
        return 0.55
    return 0.35


def _score_entity_priority(entity_type: str) -> float:
    key = str(entity_type or "").strip().lower()
    if key == "task":
        return 1.0
    if key == "specification":
        return 0.9
    if key == "note":
        return 0.8
    if key == "projectrule":
        return 0.75
    if key == "chatmessage":
        return 0.68
    if key == "chatattachment":
        return 0.64
    if key == "chatsession":
        return 0.58
    if key == "comment":
        return 0.6
    return 0.5


_TEMPLATE_ENTITY_ALIGNMENT: dict[str, set[str]] = {
    "ddd_product_build": {
        "boundedcontext",
        "aggregate",
        "command",
        "domainevent",
        "policy",
        "readmodel",
        "integrationboundary",
        "specification",
        "task",
        "projectrule",
    },
    "mobile_browser_game_development": {
        "gameplayloop",
        "inputscheme",
        "assetpipeline",
        "deviceprofile",
        "performancebudget",
        "deploymenttarget",
        "releasepipeline",
        "telemetrymetric",
        "specification",
        "task",
        "projectrule",
    },
}

_TEMPLATE_QUERY_HINTS: dict[str, list[str]] = {
    "ddd_product_build": [
        "bounded context",
        "aggregate",
        "command",
        "domain event",
        "read model",
        "policy",
    ],
    "mobile_browser_game_development": [
        "mobile browser game",
        "touch controls",
        "asset pipeline",
        "performance budget",
        "docker compose",
        "lan port",
    ],
}


def _normalize_template_key(value: str | None) -> str:
    key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key == "ddd":
        return "ddd_product_build"
    if key in {"mobile_game", "browser_game", "mobile_browser_game"}:
        return "mobile_browser_game_development"
    return key


def _normalize_entity_key(value: str | None) -> str:
    return str(value or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "")


def _template_query_terms(template_key: str | None) -> list[str]:
    key = _normalize_template_key(template_key)
    return list(_TEMPLATE_QUERY_HINTS.get(key) or [])


def _template_alignment_score(
    *,
    template_key: str | None,
    entity_type: str | None,
    source_type: str | None = None,
    graph_path: list[str] | None = None,
) -> float:
    normalized_template = _normalize_template_key(template_key)
    priority = _TEMPLATE_ENTITY_ALIGNMENT.get(normalized_template)
    if not priority:
        return 0.5

    entity_key = _normalize_entity_key(entity_type)
    if entity_key in priority:
        return 1.0

    best = 0.35
    source_key = _normalize_entity_key((source_type or "").split(".", 1)[0])
    if source_key and source_key in priority:
        best = max(best, 0.78)

    for step in graph_path or []:
        step_key = _normalize_entity_key(step)
        if step_key in priority:
            best = max(best, 0.86)
            break
    return best


def _compose_dependency_path(path_payload: dict[str, Any]) -> list[str]:
    nodes = path_payload.get("nodes") or []
    relationships = path_payload.get("relationships") or []
    out: list[str] = []
    for idx, node in enumerate(nodes):
        entity_type = str((node or {}).get("entity_type") or "").strip()
        if entity_type:
            out.append(entity_type)
        if idx < len(relationships):
            rel = str(relationships[idx] or "").strip()
            if rel:
                out.append(rel)
    return out


def _build_dependency_paths(
    *,
    project_id: str,
    focus_entity_type: str | None,
    focus_entity_id: str | None,
    candidates: list[tuple[str, str]],
    max_items: int = 6,
) -> list[dict[str, Any]]:
    if not str(focus_entity_type or "").strip() or not str(focus_entity_id or "").strip():
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entity_type, entity_id in candidates:
        key = (str(entity_type), str(entity_id))
        if key in seen:
            continue
        seen.add(key)
        if entity_id == focus_entity_id:
            continue
        try:
            path_payload = graph_get_dependency_path(
                project_id=project_id,
                from_entity_type=str(focus_entity_type),
                from_entity_id=str(focus_entity_id),
                to_entity_type=entity_type,
                to_entity_id=entity_id,
                max_depth=max(2, GRAPH_CONTEXT_MAX_HOPS + 2),
            )
        except Exception:
            continue
        if not path_payload.get("found"):
            continue
        out.append(
            {
                "to_entity_type": entity_type,
                "to_entity_id": entity_id,
                "hops": int(path_payload.get("hops") or 0),
                "relationships": path_payload.get("relationships") or [],
                "path": _compose_dependency_path(path_payload),
            }
        )
        if len(out) >= max(1, int(max_items)):
            break
    return out


def _dependency_path_lookup(dependency_paths: list[dict[str, Any]]) -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    for item in dependency_paths:
        key = (str(item.get("to_entity_type") or ""), str(item.get("to_entity_id") or ""))
        if not key[0] or not key[1]:
            continue
        path = [str(step) for step in (item.get("path") or []) if str(step).strip()]
        if path:
            out[key] = path
    return out


def _load_graph_only_evidence_candidates(
    *,
    project_id: str,
    candidates: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    from .models import ChatAttachment, ChatMessage, Note, ProjectRule, SessionLocal, Specification, Task

    out: list[dict[str, Any]] = []
    if not candidates:
        return out
    with SessionLocal() as db:
        for candidate in candidates:
            entity_type = str(candidate.get("entity_type") or "").strip()
            entity_id = str(candidate.get("entity_id") or "").strip()
            if not entity_type or not entity_id:
                continue
            graph_score = float(candidate.get("graph_score") or 0.0)
            key = entity_type.lower()
            snippets: list[tuple[str, str, Any]] = []
            if key == "task":
                task = db.get(Task, entity_id)
                if not task or task.project_id != project_id or task.is_deleted or task.archived:
                    continue
                snippets = [
                    ("task.title", task.title or "", task.updated_at),
                    ("task.description", task.description or "", task.updated_at),
                ]
            elif key == "note":
                note = db.get(Note, entity_id)
                if not note or note.project_id != project_id or note.is_deleted or note.archived:
                    continue
                snippets = [
                    ("note.title", note.title or "", note.updated_at),
                    ("note.body", note.body or "", note.updated_at),
                ]
            elif key == "specification":
                specification = db.get(Specification, entity_id)
                if not specification or specification.project_id != project_id or specification.is_deleted or specification.archived:
                    continue
                snippets = [
                    ("specification.title", specification.title or "", specification.updated_at),
                    ("specification.body", specification.body or "", specification.updated_at),
                ]
            elif key == "projectrule":
                rule = db.get(ProjectRule, entity_id)
                if not rule or rule.project_id != project_id or rule.is_deleted:
                    continue
                snippets = [
                    ("project_rule.title", rule.title or "", rule.updated_at),
                    ("project_rule.body", rule.body or "", rule.updated_at),
                ]
            elif key == "chatmessage":
                message = db.get(ChatMessage, entity_id)
                if not message or message.project_id != project_id or message.is_deleted:
                    continue
                snippets = [
                    (f"chat_message.{str(message.role or '').strip().lower() or 'message'}", message.content or "", message.updated_at),
                ]
            elif key == "chatattachment":
                attachment = db.get(ChatAttachment, entity_id)
                if not attachment or attachment.project_id != project_id or attachment.is_deleted:
                    continue
                metadata_parts: list[str] = []
                if str(attachment.name or "").strip():
                    metadata_parts.append(f"name: {attachment.name}")
                if str(attachment.path or "").strip():
                    metadata_parts.append(f"path: {attachment.path}")
                if str(attachment.mime_type or "").strip():
                    metadata_parts.append(f"mime_type: {attachment.mime_type}")
                if isinstance(attachment.size_bytes, int) and attachment.size_bytes >= 0:
                    metadata_parts.append(f"size_bytes: {attachment.size_bytes}")
                metadata_text = "\n".join(metadata_parts).strip()
                snippets = []
                if metadata_text:
                    snippets.append(("chat_attachment.metadata", metadata_text, attachment.updated_at))
                if str(attachment.extracted_text or "").strip():
                    snippets.append(("chat_attachment.text", attachment.extracted_text or "", attachment.updated_at))
            else:
                continue

            for source_type, text, source_updated_at in snippets:
                snippet = _truncate_snippet(text)
                if not snippet:
                    continue
                out.append(
                    {
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "source_type": source_type,
                        "snippet": snippet,
                        "source_updated_at": source_updated_at,
                        "graph_score": graph_score,
                        "vector_similarity": None,
                    }
                )
                if len(out) >= max(8, int(limit) * 4):
                    return out
    return out


def _build_grounded_summary(
    *,
    project_name: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    if str(GRAPH_RAG_SUMMARY_MODEL or "").strip():
        return _build_grounded_summary_with_ollama(project_name=project_name, evidence=evidence)
    return _build_grounded_summary_heuristic(project_name=project_name, evidence=evidence)


def _build_grounded_summary_heuristic(
    *,
    project_name: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    if not evidence:
        return {
            "executive": f"{project_name}: no grounded textual evidence is currently available.",
            "key_points": [],
            "gaps": ["No indexed text evidence found for this project scope."],
        }

    top = evidence[: min(len(evidence), 5)]
    key_points: list[dict[str, Any]] = []
    for item in top:
        snippet = _truncate_snippet(str(item.get("snippet") or ""), max_chars=170)
        claim = snippet or f"{item.get('entity_type')} {item.get('entity_id')} is relevant."
        key_points.append({"claim": claim, "evidence_ids": [str(item.get("evidence_id") or "")]})

    executive = f"{project_name}: {len(top)} grounded finding(s) extracted from {len(evidence)} evidence item(s)."
    gaps: list[str] = []
    if len(evidence) < 3:
        gaps.append("Limited evidence volume; add or expand project artifacts for stronger grounding.")
    return {"executive": executive, "key_points": key_points, "gaps": gaps}


def _summary_prompt(project_name: str, evidence: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("You are generating a grounded project summary.")
    lines.append("Use only the evidence list.")
    lines.append("Rules:")
    lines.append("- Do not invent facts.")
    lines.append("- Every key point must cite at least one evidence_id.")
    lines.append("- Return strict JSON object with keys: executive, key_points, gaps.")
    lines.append("- key_points is an array of {claim, evidence_ids}.")
    lines.append("")
    lines.append(f"Project: {project_name}")
    lines.append("Evidence:")
    for item in evidence[:12]:
        lines.append(
            "[{evidence_id}] {entity_type} {entity_id} ({source_type}) score={score:.3f} :: {snippet}".format(
                evidence_id=str(item.get("evidence_id") or ""),
                entity_type=str(item.get("entity_type") or "Entity"),
                entity_id=str(item.get("entity_id") or "?"),
                source_type=str(item.get("source_type") or "source"),
                score=float(item.get("final_score") or 0.0),
                snippet=_truncate_snippet(str(item.get("snippet") or ""), max_chars=220),
            )
        )
    lines.append("")
    lines.append("Return JSON only.")
    return "\n".join(lines)


def _normalize_summary_payload(raw: dict[str, Any], *, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    evidence_ids = {str(item.get("evidence_id") or "").strip() for item in evidence if str(item.get("evidence_id") or "").strip()}
    executive = str(raw.get("executive") or "").strip() or "Grounded summary is unavailable."
    key_points: list[dict[str, Any]] = []
    for row in (raw.get("key_points") or []):
        if not isinstance(row, dict):
            continue
        claim = str(row.get("claim") or "").strip()
        if not claim:
            continue
        ids = [str(item).strip() for item in (row.get("evidence_ids") or []) if str(item).strip()]
        ids = [item for item in ids if item in evidence_ids]
        if not ids:
            continue
        key_points.append({"claim": claim, "evidence_ids": ids[:3]})
    gaps = [str(item).strip() for item in (raw.get("gaps") or []) if str(item).strip()]
    return {
        "executive": executive,
        "key_points": key_points[:8],
        "gaps": gaps[:8],
    }


def _build_grounded_summary_with_ollama(
    *,
    project_name: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    if not evidence:
        return {
            "executive": f"{project_name}: no grounded textual evidence is currently available.",
            "key_points": [],
            "gaps": ["No indexed text evidence found for this project scope."],
        }

    model = str(GRAPH_RAG_SUMMARY_MODEL or "").strip()
    if not model:
        return _build_grounded_summary_heuristic(project_name=project_name, evidence=evidence)

    prompt = _summary_prompt(project_name, evidence)
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    response = httpx.post(url, json=payload, timeout=50.0)
    if response.status_code >= 400:
        detail = (response.text or f"Ollama summary request failed ({response.status_code})").strip()
        raise RuntimeError(detail)
    data = response.json()
    summary_raw = parse_json_object(
        str(data.get("response") or ""),
        empty_error="Summary response is empty",
        invalid_error="Summary response is not valid JSON object",
    )
    summary = _normalize_summary_payload(summary_raw, evidence=evidence)
    if not summary.get("key_points"):
        raise RuntimeError("Summary payload has no grounded key points")
    return summary


def _render_context_markdown(
    *,
    structure: dict[str, Any],
    evidence: list[dict[str, Any]],
    summary: dict[str, Any] | None,
) -> str:
    overview = structure.get("overview") or {}
    focus_neighbors = structure.get("focus_neighbors") or []
    dependency_paths = structure.get("dependency_paths") or []
    lines: list[str] = []

    project_name = str(overview.get("project_name") or "").strip() or overview.get("project_id") or "(unknown)"
    counts = overview.get("counts") or {}
    lines.append(f"# Graph Context: {project_name}")
    lines.append("")
    lines.append("## Structure")
    lines.append(
        "- tasks={tasks}, notes={notes}, specifications={specs}, project_rules={rules}, comments={comments}".format(
            tasks=int(counts.get("tasks") or 0),
            notes=int(counts.get("notes") or 0),
            specs=int(counts.get("specifications") or 0),
            rules=int(counts.get("project_rules") or 0),
            comments=int(counts.get("comments") or 0),
        )
    )
    if focus_neighbors:
        lines.append("- focus_neighbors:")
        for row in focus_neighbors[:8]:
            lines.append(
                "  - {entity_type} {entity_id}: {title}".format(
                    entity_type=str(row.get("entity_type") or "Entity"),
                    entity_id=str(row.get("entity_id") or "?"),
                    title=str(row.get("title") or row.get("entity_id") or ""),
                )
            )
    if dependency_paths:
        lines.append("- dependency_paths:")
        for row in dependency_paths[:6]:
            path = " -> ".join([str(step) for step in (row.get("path") or []) if str(step).strip()])
            lines.append(
                "  - {to_type} {to_id}: {path}".format(
                    to_type=str(row.get("to_entity_type") or "Entity"),
                    to_id=str(row.get("to_entity_id") or "?"),
                    path=path or "RELATED",
                )
            )

    lines.append("")
    lines.append("## Evidence")
    if not evidence:
        lines.append("- _(none)_")
    else:
        for row in evidence[: min(len(evidence), 12)]:
            lines.append(
                "- [{evidence_id}] {entity_type} {entity_id} ({source_type}) score={score:.3f} :: {snippet}".format(
                    evidence_id=str(row.get("evidence_id") or ""),
                    entity_type=str(row.get("entity_type") or "Entity"),
                    entity_id=str(row.get("entity_id") or "?"),
                    source_type=str(row.get("source_type") or "source"),
                    score=float(row.get("final_score") or 0.0),
                    snippet=_truncate_snippet(str(row.get("snippet") or ""), max_chars=180),
                )
            )

    lines.append("")
    lines.append("## Summary")
    if not summary:
        lines.append("- _(summary unavailable)_")
    else:
        lines.append(str(summary.get("executive") or ""))
        key_points = summary.get("key_points") or []
        if key_points:
            for item in key_points:
                evidence_ids = [str(item_id) for item_id in (item.get("evidence_ids") or []) if str(item_id).strip()]
                suffix = f" [{', '.join(evidence_ids)}]" if evidence_ids else ""
                lines.append(f"- {str(item.get('claim') or '').strip()}{suffix}")
        gaps = summary.get("gaps") or []
        if gaps:
            lines.append("")
            lines.append("Gaps:")
            for gap in gaps:
                lines.append(f"- {str(gap)}")

    text = "\n".join(lines).strip()
    max_chars = max(400, int(GRAPH_CONTEXT_MAX_TOKENS) * 4)
    if len(text) > max_chars:
        return text[: max_chars - 18].rstrip() + "\n\n_(truncated)_"
    return text


def graph_context_pack(
    *,
    project_id: str,
    focus_entity_type: str | None = None,
    focus_entity_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    require_graph_available()
    incr("graph_context_requests")
    rag_enabled = graph_rag_enabled_for_project(project_id)
    started_at = perf_counter()
    summary_emitted = False
    if rag_enabled:
        incr("graph_rag_requests")
    try:
        safe_limit = max(1, min(int(limit or 20), 60))
        evidence_top_k = _resolve_context_pack_evidence_top_k(project_id, safe_limit)
        gaps: list[str] = []
        if GRAPH_RAG_ENABLED and not rag_enabled and (GRAPH_RAG_CANARY_PROJECT_IDS or GRAPH_RAG_CANARY_WORKSPACE_IDS):
            gaps.append("GraphRAG canary is disabled for this project scope; using graph-only mode.")
        overview = graph_get_project_overview(project_id, top_limit=min(max(4, safe_limit // 2), 20))

        focus_neighbors: list[dict[str, Any]] = []
        if str(focus_entity_type or "").strip() and str(focus_entity_id or "").strip():
            focus = graph_get_neighbors(
                project_id=project_id,
                entity_type=str(focus_entity_type),
                entity_id=str(focus_entity_id),
                depth=min(max(1, GRAPH_CONTEXT_MAX_HOPS), 4),
                limit=min(safe_limit, 30),
            )
            focus_neighbors = focus.get("items") or []

        connected_resources = run_graph_query(
            """
            MATCH (p:Project {id:$project_id})
            MATCH (n)
            WHERE (
                coalesce(n.project_id, '') = $project_id
                OR EXISTS { MATCH (n)-[:IN_PROJECT]->(p) }
              )
              AND coalesce(n.is_deleted, false) = false
            OPTIONAL MATCH (n)-[r]-()
            RETURN
              head(labels(n)) AS entity_type,
              n.id AS entity_id,
              coalesce(n.title, n.name, n.id) AS title,
              count(DISTINCT r) AS degree
            ORDER BY degree DESC, title ASC
            LIMIT $limit
            """,
            {
                "project_id": project_id,
                "limit": safe_limit,
            },
        )

        comment_resources = run_graph_query(
            """
            MATCH (p:Project {id:$project_id})
            MATCH (t:Task)-[r:COMMENTED_BY]->(u:User)
            WHERE coalesce(t.is_deleted, false) = false
              AND (
                coalesce(t.project_id, '') = $project_id
                OR EXISTS { MATCH (t)-[:IN_PROJECT]->(p) }
              )
            RETURN
              'Comment' AS entity_type,
              ('comment-thread:' + t.id + ':' + u.id) AS entity_id,
              (coalesce(u.username, u.name, u.id) + ' · ' + toString(coalesce(r.count, 1)) + ' comments on ' + coalesce(t.title, t.id)) AS title,
              toInteger(coalesce(r.count, 1) + 1) AS degree
            ORDER BY degree DESC, title ASC
            LIMIT $limit
            """,
            {
                "project_id": project_id,
                "limit": safe_limit,
            },
        )

        merged_resources: list[dict[str, Any]] = []
        seen_resource_ids: set[str] = set()
        for row in [*connected_resources, *comment_resources]:
            entity_id = str(row.get("entity_id") or "").strip()
            if not entity_id or entity_id in seen_resource_ids:
                continue
            seen_resource_ids.add(entity_id)
            merged_resources.append(
                {
                    "entity_type": str(row.get("entity_type") or "Entity"),
                    "entity_id": entity_id,
                    "title": str(row.get("title") or entity_id),
                    "degree": int(row.get("degree") or 0),
                }
            )
        merged_resources.sort(key=lambda item: (-int(item.get("degree") or 0), str(item.get("title") or "").lower()))
        connected_resources = merged_resources[:safe_limit]

        max_degree = max([int(item.get("degree") or 0) for item in connected_resources], default=1)
        candidate_scores: dict[tuple[str, str], float] = {}
        for row in connected_resources:
            entity_type = str(row.get("entity_type") or "").strip()
            entity_id = str(row.get("entity_id") or "").strip()
            if not entity_type or not entity_id:
                continue
            degree = int(row.get("degree") or 0)
            candidate_scores[(entity_type, entity_id)] = max(0.0, min(1.0, degree / max(1, max_degree)))
        for row in focus_neighbors:
            entity_type = str(row.get("entity_type") or "").strip()
            entity_id = str(row.get("entity_id") or "").strip()
            if not entity_type or not entity_id:
                continue
            path_types = [str(item) for item in (row.get("path_types") or []) if str(item).strip()]
            score = 1.0 / max(1.0, float(len(path_types) + 1))
            prev = candidate_scores.get((entity_type, entity_id), 0.0)
            candidate_scores[(entity_type, entity_id)] = max(prev, score)

        candidate_pairs = sorted(candidate_scores.keys(), key=lambda key: -candidate_scores.get(key, 0.0))
        dependency_paths = _build_dependency_paths(
            project_id=project_id,
            focus_entity_type=focus_entity_type,
            focus_entity_id=focus_entity_id,
            candidates=candidate_pairs,
            max_items=min(8, evidence_top_k),
        )
        path_lookup = _dependency_path_lookup(dependency_paths)

        template_binding = _load_project_template_binding(project_id)
        template_key = str((template_binding or {}).get("template_key") or "").strip()
        project_name = str(overview.get("project_name") or project_id).strip() or project_id
        top_tags = [str(item.get("tag") or "").strip() for item in (overview.get("top_tags") or []) if str(item.get("tag") or "").strip()]
        focus_hint = str(focus_entity_id or "").strip()
        retrieval_query = " ".join(
            [project_name, focus_hint, *top_tags, *_template_query_terms(template_key)]
        ).strip() or project_name

        evidence: list[dict[str, Any]] = []
        vector_mode = False
        if rag_enabled:
            from .models import SessionLocal

            try:
                with SessionLocal() as db:
                    runtime = resolve_project_embedding_runtime(db, project_id)
                    if runtime.enabled:
                        vector_mode = True
                        vector_candidates = search_project_chunks(
                            db,
                            project_id=project_id,
                            query=retrieval_query,
                            limit=max(evidence_top_k * 4, 12),
                            entity_filters=set(candidate_pairs) or None,
                        )
                    else:
                        vector_candidates = []
                        gaps.append("Vector retrieval is disabled for this project; using graph-only evidence.")
            except Exception as exc:
                logger.warning("Vector retrieval failed for project=%s: %s", project_id, exc)
                vector_candidates = []
                vector_mode = False
                gaps.append("Vector retrieval failed; used graph-only evidence fallback.")
        else:
            vector_candidates = []

        if vector_candidates:
            for item in vector_candidates:
                entity_type = str(item.get("entity_type") or "").strip() or "Entity"
                entity_id = str(item.get("entity_id") or "").strip() or "?"
                source_type = str(item.get("source_type") or "source")
                snippet = _truncate_snippet(str(item.get("snippet") or ""))
                if not snippet:
                    continue
                key = (entity_type, entity_id)
                graph_score = float(candidate_scores.get(key, 0.25))
                vector_similarity = float(item.get("vector_similarity") or 0.0)
                freshness = _score_freshness(item.get("source_updated_at"))
                entity_priority = _score_entity_priority(entity_type)
                graph_path = path_lookup.get(key, [entity_type])
                template_alignment = _template_alignment_score(
                    template_key=template_key,
                    entity_type=entity_type,
                    source_type=source_type,
                    graph_path=graph_path,
                )
                final_score = (
                    (0.34 * graph_score)
                    + (0.34 * vector_similarity)
                    + (0.14 * freshness)
                    + (0.08 * entity_priority)
                    + (0.10 * template_alignment)
                )
                source_updated_at = _as_datetime_utc(item.get("source_updated_at"))
                evidence.append(
                    {
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "source_type": source_type,
                        "snippet": snippet,
                        "vector_similarity": vector_similarity,
                        "graph_score": graph_score,
                        "template_alignment": template_alignment,
                        "final_score": final_score,
                        "graph_path": graph_path,
                        "updated_at": source_updated_at.isoformat().replace("+00:00", "Z") if source_updated_at else None,
                        "why_selected": "high semantic similarity with graph relevance and template alignment",
                    }
                )
        else:
            graph_candidates = [
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "graph_score": score,
                }
                for (entity_type, entity_id), score in sorted(candidate_scores.items(), key=lambda item: -item[1])
            ]
            graph_only_evidence = _load_graph_only_evidence_candidates(
                project_id=project_id,
                candidates=graph_candidates,
                limit=max(evidence_top_k * 3, 10),
            )
            for item in graph_only_evidence:
                entity_type = str(item.get("entity_type") or "").strip() or "Entity"
                entity_id = str(item.get("entity_id") or "").strip() or "?"
                source_type = str(item.get("source_type") or "source")
                snippet = _truncate_snippet(str(item.get("snippet") or ""))
                if not snippet:
                    continue
                graph_score = float(item.get("graph_score") or 0.0)
                freshness = _score_freshness(item.get("source_updated_at"))
                entity_priority = _score_entity_priority(entity_type)
                source_updated_at = _as_datetime_utc(item.get("source_updated_at"))
                key = (entity_type, entity_id)
                graph_path = path_lookup.get(key, [entity_type])
                template_alignment = _template_alignment_score(
                    template_key=template_key,
                    entity_type=entity_type,
                    source_type=source_type,
                    graph_path=graph_path,
                )
                final_score = (
                    (0.60 * graph_score)
                    + (0.18 * freshness)
                    + (0.08 * entity_priority)
                    + (0.14 * template_alignment)
                )
                evidence.append(
                    {
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "source_type": source_type,
                        "snippet": snippet,
                        "vector_similarity": None,
                        "graph_score": graph_score,
                        "template_alignment": template_alignment,
                        "final_score": final_score,
                        "graph_path": graph_path,
                        "updated_at": source_updated_at.isoformat().replace("+00:00", "Z") if source_updated_at else None,
                        "why_selected": "graph-only fallback based on topology, freshness, and template alignment",
                    }
                )

        evidence.sort(
            key=lambda item: (
                -float(item.get("final_score") or 0.0),
                -float(item.get("template_alignment") or 0.0),
                -float(item.get("graph_score") or 0.0),
                str(item.get("entity_type") or ""),
                str(item.get("entity_id") or ""),
            )
        )
        evidence = evidence[:evidence_top_k]
        for idx, item in enumerate(evidence, start=1):
            item["evidence_id"] = f"ev_{idx:03d}"
            item["final_score"] = round(float(item.get("final_score") or 0.0), 4)
            item["graph_score"] = round(float(item.get("graph_score") or 0.0), 4)
            vector_similarity = item.get("vector_similarity")
            if vector_similarity is not None:
                item["vector_similarity"] = round(float(vector_similarity), 4)
            item["template_alignment"] = round(float(item.get("template_alignment") or 0.0), 4)

        summary: dict[str, Any] | None = None
        if rag_enabled:
            try:
                summary = _build_grounded_summary(project_name=project_name, evidence=evidence)
            except Exception as exc:
                logger.warning("Grounded summary failed for project=%s: %s", project_id, exc)
                summary = None
                gaps.append("Grounded summary is unavailable; use structure and evidence directly.")

        if summary:
            key_points = summary.get("key_points") or []
            grounded = 0
            for item in key_points:
                ids = [str(item_id) for item_id in (item.get("evidence_ids") or []) if str(item_id).strip()]
                if ids:
                    grounded += 1
            ratio = int(round((grounded / max(1, len(key_points))) * 100)) if key_points else 0
            set_value("context_pack_grounded_claim_ratio", ratio)
        else:
            set_value("context_pack_grounded_claim_ratio", 0)

        structure = {
            "overview": overview,
            "focus_neighbors": focus_neighbors,
            "dependency_paths": dependency_paths,
        }
        markdown = _render_context_markdown(
            structure=structure,
            evidence=evidence,
            summary=summary,
        )
        response: dict[str, Any] = {
            "project_id": project_id,
            "focus": (
                {"entity_type": str(focus_entity_type), "entity_id": str(focus_entity_id)}
                if str(focus_entity_type or "").strip() and str(focus_entity_id or "").strip()
                else None
            ),
            "mode": "graph+vector" if vector_mode else "graph-only",
            "structure": structure,
            "evidence": evidence,
            "markdown": markdown,
        }
        if template_binding is not None:
            response["template"] = template_binding
        if summary is not None:
            response["summary"] = summary
            summary_emitted = True
        if gaps:
            response["gaps"] = gaps
        return response
    except Exception:
        incr("graph_context_failures")
        if rag_enabled:
            incr("graph_rag_failures")
        raise
    finally:
        latency_ms = int((perf_counter() - started_at) * 1000)
        observe("graph_context_latency_ms", latency_ms)
        if summary_emitted:
            observe("graph_context_latency_ms_with_summary", latency_ms)
        else:
            observe("graph_context_latency_ms_without_summary", latency_ms)


def build_graph_context_pack(
    *,
    project_id: str | None,
    focus_entity_type: str | None = None,
    focus_entity_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    if not str(project_id or "").strip():
        return {}
    if not graph_enabled():
        return {}
    try:
        return graph_context_pack(
            project_id=str(project_id),
            focus_entity_type=focus_entity_type,
            focus_entity_id=focus_entity_id,
            limit=limit,
        )
    except Exception as exc:
        logger.warning("Knowledge graph context build failed: %s", exc)
        return {}


def build_graph_context_markdown(
    *,
    project_id: str | None,
    focus_entity_type: str | None = None,
    focus_entity_id: str | None = None,
    limit: int = 20,
) -> str:
    pack = build_graph_context_pack(
        project_id=project_id,
        focus_entity_type=focus_entity_type,
        focus_entity_id=focus_entity_id,
        limit=limit,
    )
    if not pack:
        return ""
    return str(pack.get("markdown") or "").strip()
