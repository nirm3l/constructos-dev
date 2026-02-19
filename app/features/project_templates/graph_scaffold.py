from __future__ import annotations

import re

from shared.knowledge_graph import graph_enabled, run_graph_query
from shared.settings import logger

from .catalog import ProjectTemplateDefinition

_LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_REL_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def _safe_label(value: str) -> str:
    label = str(value or "").strip()
    if not _LABEL_RE.fullmatch(label):
        raise ValueError(f"Unsupported graph label: {value}")
    return label


def _safe_relation(value: str) -> str:
    relation = str(value or "").strip().upper()
    if not _REL_RE.fullmatch(relation):
        raise ValueError(f"Unsupported graph relation: {value}")
    return relation


def _scaffold_node_id(*, project_id: str, node_key: str) -> str:
    normalized = str(node_key or "").strip().lower().replace(" ", "_")
    return f"{project_id}:template:{normalized}"


def sync_template_graph_scaffold(
    *,
    project_id: str,
    workspace_id: str,
    template: ProjectTemplateDefinition,
) -> None:
    if not graph_enabled():
        return

    try:
        template_node_id = f"template:{template.key}"
        template_version_node_id = f"template:{template.key}@{template.version}"
        run_graph_query(
            """
            MERGE (p:Project {id:$project_id})
            SET p.workspace_id = coalesce(p.workspace_id, $workspace_id)
            MERGE (t:Template {id:$template_node_id})
            SET t.key = $template_key,
                t.name = $template_name
            MERGE (v:TemplateVersion {id:$template_version_node_id})
            SET v.key = $template_key,
                v.version = $template_version,
                v.name = ($template_name + ' v' + $template_version)
            MERGE (p)-[:USES_TEMPLATE]->(t)
            MERGE (p)-[:USES_TEMPLATE_VERSION]->(v)
            MERGE (v)-[:VERSION_OF]->(t)
            """,
            {
                "project_id": project_id,
                "workspace_id": workspace_id,
                "template_node_id": template_node_id,
                "template_version_node_id": template_version_node_id,
                "template_key": template.key,
                "template_name": template.name,
                "template_version": template.version,
            },
            write=True,
        )

        for node in template.graph_nodes:
            label = _safe_label(node.label)
            node_id = _scaffold_node_id(project_id=project_id, node_key=node.node_key)
            props = {
                "title": node.title,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "template_key": template.key,
                "template_version": template.version,
                "template_name": template.name,
            }
            props.update(node.props or {})
            run_graph_query(
                f"MERGE (n:{label} {{id:$node_id}}) SET n += $props",
                {
                    "node_id": node_id,
                    "props": props,
                },
                write=True,
            )
            run_graph_query(
                f"""
                MATCH (n:{label} {{id:$node_id}})
                MATCH (p:Project {{id:$project_id}})
                MERGE (n)-[:IN_PROJECT]->(p)
                """,
                {
                    "node_id": node_id,
                    "project_id": project_id,
                },
                write=True,
            )

        for edge in template.graph_edges:
            relation = _safe_relation(edge.relation)
            source_label = _safe_label(edge.source_label)
            target_label = _safe_label(edge.target_label)
            source_id = _scaffold_node_id(project_id=project_id, node_key=edge.source_node_key)
            target_id = _scaffold_node_id(project_id=project_id, node_key=edge.target_node_key)
            run_graph_query(
                f"""
                MATCH (a:{source_label} {{id:$source_id}})
                MATCH (b:{target_label} {{id:$target_id}})
                MERGE (a)-[:{relation}]->(b)
                """,
                {
                    "source_id": source_id,
                    "target_id": target_id,
                },
                write=True,
            )
    except Exception as exc:
        logger.warning(
            "Template graph scaffold sync failed project_id=%s template=%s: %s",
            project_id,
            template.key,
            exc,
        )

