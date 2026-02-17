from __future__ import annotations

import re
import threading
from collections.abc import Iterable
from typing import Any

from .observability import incr
from .settings import (
    GRAPH_CONTEXT_MAX_HOPS,
    GRAPH_CONTEXT_MAX_TOKENS,
    KNOWLEDGE_GRAPH_ENABLED,
    NEO4J_DATABASE,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USERNAME,
    logger,
)

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
    "task": "Task",
    "note": "Note",
    "comment": "Comment",
    "taskcomment": "Comment",
    "task_comment": "Comment",
    "specification": "Specification",
    "projectrule": "ProjectRule",
    "project_rule": "ProjectRule",
    "user": "User",
    "tag": "Tag",
}


def graph_enabled() -> bool:
    return bool(KNOWLEDGE_GRAPH_ENABLED and NEO4J_URI)


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
            "CREATE CONSTRAINT task_id_unique IF NOT EXISTS FOR (n:Task) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT note_id_unique IF NOT EXISTS FOR (n:Note) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT specification_id_unique IF NOT EXISTS FOR (n:Specification) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT project_rule_id_unique IF NOT EXISTS FOR (n:ProjectRule) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (n:User) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT tag_value_unique IF NOT EXISTS FOR (n:Tag) REQUIRE n.value IS UNIQUE",
            "CREATE INDEX project_workspace_idx IF NOT EXISTS FOR (n:Project) ON (n.workspace_id)",
            "CREATE INDEX task_project_idx IF NOT EXISTS FOR (n:Task) ON (n.project_id)",
            "CREATE INDEX note_project_idx IF NOT EXISTS FOR (n:Note) ON (n.project_id)",
            "CREATE INDEX specification_project_idx IF NOT EXISTS FOR (n:Specification) ON (n.project_id)",
            "CREATE INDEX project_rule_project_idx IF NOT EXISTS FOR (n:ProjectRule) ON (n.project_id)",
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
        RETURN p.id AS project_id, coalesce(p.name, '') AS project_name
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

    preferred_order = ["specification", "comment", "task", "note", "projectrule", "user", "tag", "workspace"]
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
    if task_ids and remaining_node_slots:
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
            label = f"{author} · {count} comment{'s' if count != 1 else ''}"
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
    for row in edge_rows:
        source = str(row.get("source_entity_id") or "").strip()
        target = str(row.get("target_entity_id") or "").strip()
        relationship = str(row.get("relationship") or "RELATED").strip() or "RELATED"
        if not source or not target or source == target:
            continue
        if source > target:
            source, target = target, source
        key = (source, target, relationship)
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

    rows = run_graph_query(
        """
        MATCH (n)
        WHERE n.project_id = $project_id
          AND coalesce(n.is_deleted, false) = false
          AND (
            toLower(coalesce(n.title, '')) CONTAINS $q
            OR toLower(coalesce(n.description, '')) CONTAINS $q
            OR toLower(coalesce(n.body, '')) CONTAINS $q
            OR toLower(coalesce(n.name, '')) CONTAINS $q
          )
        OPTIONAL MATCH (n)-[r]-()
        RETURN
          head(labels(n)) AS entity_type,
          n.id AS entity_id,
          coalesce(n.title, n.name, n.id) AS title,
          count(r) AS score
        ORDER BY score DESC, title ASC
        LIMIT $limit
        """,
        {
            "project_id": project_id,
            "q": q,
            "limit": safe_limit,
        },
    )
    return {
        "project_id": project_id,
        "query": query,
        "items": rows,
    }


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


def _render_context_markdown(
    *,
    overview: dict[str, Any],
    focus_neighbors: list[dict[str, Any]],
    connected_resources: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    project_name = str(overview.get("project_name") or "").strip() or overview.get("project_id") or "(unknown)"
    counts = overview.get("counts") or {}

    lines.append(f"# Graph Context: {project_name}")
    lines.append("")
    lines.append("## Counts")
    lines.append(
        "- tasks={tasks}, notes={notes}, specifications={specs}, project_rules={rules}, comments={comments}".format(
            tasks=int(counts.get("tasks") or 0),
            notes=int(counts.get("notes") or 0),
            specs=int(counts.get("specifications") or 0),
            rules=int(counts.get("project_rules") or 0),
            comments=int(counts.get("comments") or 0),
        )
    )

    lines.append("")
    lines.append("## Top Tags")
    top_tags = overview.get("top_tags") or []
    if not top_tags:
        lines.append("- _(none)_")
    else:
        for item in top_tags:
            tag = str(item.get("tag") or "").strip() or "(empty)"
            usage = int(item.get("usage") or 0)
            lines.append(f"- {tag} ({usage})")

    lines.append("")
    lines.append("## Key Relations")
    top_relationships = overview.get("top_relationships") or []
    if not top_relationships:
        lines.append("- _(none)_")
    else:
        for item in top_relationships:
            rel = str(item.get("relationship") or "").strip() or "(unknown)"
            count = int(item.get("count") or 0)
            lines.append(f"- {rel} ({count})")

    lines.append("")
    lines.append("## Focus Neighbors")
    if not focus_neighbors:
        lines.append("- _(none)_")
    else:
        for item in focus_neighbors:
            et = str(item.get("entity_type") or "").strip() or "Entity"
            eid = str(item.get("entity_id") or "").strip() or "?"
            title = str(item.get("title") or "").strip() or eid
            rel_path = "/".join([str(x) for x in (item.get("path_types") or []) if str(x).strip()]) or "RELATED"
            lines.append(f"- {et} {eid}: {title} via {rel_path}")

    lines.append("")
    lines.append("## Connected Resources")
    if not connected_resources:
        lines.append("- _(none)_")
    else:
        for item in connected_resources:
            et = str(item.get("entity_type") or "").strip() or "Entity"
            eid = str(item.get("entity_id") or "").strip() or "?"
            title = str(item.get("title") or "").strip() or eid
            degree = int(item.get("degree") or 0)
            lines.append(f"- {et} {eid}: {title} (degree={degree})")

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
    safe_limit = max(1, min(int(limit or 20), 60))
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

    markdown = _render_context_markdown(
        overview=overview,
        focus_neighbors=focus_neighbors,
        connected_resources=connected_resources,
    )
    return {
        "project_id": project_id,
        "focus_entity_type": focus_entity_type,
        "focus_entity_id": focus_entity_id,
        "overview": overview,
        "focus_neighbors": focus_neighbors,
        "connected_resources": connected_resources,
        "markdown": markdown,
    }


def build_graph_context_markdown(
    *,
    project_id: str | None,
    focus_entity_type: str | None = None,
    focus_entity_id: str | None = None,
    limit: int = 20,
) -> str:
    if not str(project_id or "").strip():
        return ""
    if not graph_enabled():
        return ""
    incr("graph_context_requests")
    try:
        pack = graph_context_pack(
            project_id=str(project_id),
            focus_entity_type=focus_entity_type,
            focus_entity_id=focus_entity_id,
            limit=limit,
        )
        return str(pack.get("markdown") or "").strip()
    except Exception as exc:
        incr("graph_context_failures")
        logger.warning("Knowledge graph context build failed: %s", exc)
        return ""
