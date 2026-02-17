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
            "counts": {"tasks": 0, "notes": 0, "specifications": 0, "project_rules": 0},
            "top_tags": [],
            "top_relationships": [],
        }

    counts_rows = run_graph_query(
        """
        MATCH (p:Project {id:$project_id})
        OPTIONAL MATCH (p)<-[:IN_PROJECT]-(t:Task)
        WHERE coalesce(t.is_deleted, false) = false
        WITH p, count(t) AS task_count
        OPTIONAL MATCH (p)<-[:IN_PROJECT]-(n:Note)
        WHERE coalesce(n.is_deleted, false) = false
        WITH p, task_count, count(n) AS note_count
        OPTIONAL MATCH (p)<-[:IN_PROJECT]-(s:Specification)
        WHERE coalesce(s.is_deleted, false) = false
        WITH p, task_count, note_count, count(s) AS specification_count
        OPTIONAL MATCH (p)<-[:IN_PROJECT]-(r:ProjectRule)
        WHERE coalesce(r.is_deleted, false) = false
        RETURN task_count, note_count, specification_count, count(r) AS rule_count
        """,
        {"project_id": project_id},
    )
    counts = counts_rows[0] if counts_rows else {}

    top_tags = run_graph_query(
        """
        MATCH (p:Project {id:$project_id})<-[:IN_PROJECT]-(n)-[:TAGGED_WITH]->(tag:Tag)
        WHERE coalesce(n.is_deleted, false) = false
        RETURN tag.value AS tag, count(*) AS usage
        ORDER BY usage DESC, tag ASC
        LIMIT $limit
        """,
        {"project_id": project_id, "limit": limit},
    )

    top_relationships = run_graph_query(
        """
        MATCH (p:Project {id:$project_id})<-[:IN_PROJECT]-(n)-[r]-()
        WHERE coalesce(n.is_deleted, false) = false
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
        },
        "top_tags": [{"tag": str(row.get("tag") or ""), "usage": int(row.get("usage") or 0)} for row in top_tags],
        "top_relationships": [
            {"relationship": str(row.get("relationship") or ""), "count": int(row.get("count") or 0)}
            for row in top_relationships
        ],
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
        "- tasks={tasks}, notes={notes}, specifications={specs}, project_rules={rules}".format(
            tasks=int(counts.get("tasks") or 0),
            notes=int(counts.get("notes") or 0),
            specs=int(counts.get("specifications") or 0),
            rules=int(counts.get("project_rules") or 0),
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
        MATCH (n)
        WHERE n.project_id = $project_id
          AND coalesce(n.is_deleted, false) = false
        OPTIONAL MATCH (n)-[r]-()
        RETURN
          head(labels(n)) AS entity_type,
          n.id AS entity_id,
          coalesce(n.title, n.name, n.id) AS title,
          count(r) AS degree
        ORDER BY degree DESC, title ASC
        LIMIT $limit
        """,
        {
            "project_id": project_id,
            "limit": safe_limit,
        },
    )

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
