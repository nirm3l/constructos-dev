from __future__ import annotations

import json
import threading
from typing import Any

from sqlalchemy import select

from features.notes.domain import (
    EVENT_ARCHIVED as NOTE_EVENT_ARCHIVED,
    EVENT_CREATED as NOTE_EVENT_CREATED,
    EVENT_DELETED as NOTE_EVENT_DELETED,
    EVENT_PINNED as NOTE_EVENT_PINNED,
    EVENT_RESTORED as NOTE_EVENT_RESTORED,
    EVENT_UNPINNED as NOTE_EVENT_UNPINNED,
    EVENT_UPDATED as NOTE_EVENT_UPDATED,
)
from features.chat.domain import (
    EVENT_ARCHIVED as CHAT_SESSION_EVENT_ARCHIVED,
    EVENT_ASSISTANT_MESSAGE_APPENDED as CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_APPENDED,
    EVENT_ASSISTANT_MESSAGE_UPDATED as CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_UPDATED,
    EVENT_ATTACHMENT_LINKED as CHAT_SESSION_EVENT_ATTACHMENT_LINKED,
    EVENT_CONTEXT_UPDATED as CHAT_SESSION_EVENT_CONTEXT_UPDATED,
    EVENT_MESSAGE_DELETED as CHAT_SESSION_EVENT_MESSAGE_DELETED,
    EVENT_RENAMED as CHAT_SESSION_EVENT_RENAMED,
    EVENT_RESOURCE_LINKED as CHAT_SESSION_EVENT_RESOURCE_LINKED,
    EVENT_STARTED as CHAT_SESSION_EVENT_STARTED,
    EVENT_USER_MESSAGE_APPENDED as CHAT_SESSION_EVENT_USER_MESSAGE_APPENDED,
)
from features.projects.domain import (
    EVENT_CREATED as PROJECT_EVENT_CREATED,
    EVENT_DELETED as PROJECT_EVENT_DELETED,
    EVENT_UPDATED as PROJECT_EVENT_UPDATED,
)
from features.rules.domain import (
    EVENT_CREATED as PROJECT_RULE_EVENT_CREATED,
    EVENT_DELETED as PROJECT_RULE_EVENT_DELETED,
    EVENT_UPDATED as PROJECT_RULE_EVENT_UPDATED,
)
from features.specifications.domain import (
    EVENT_ARCHIVED as SPECIFICATION_EVENT_ARCHIVED,
    EVENT_CREATED as SPECIFICATION_EVENT_CREATED,
    EVENT_DELETED as SPECIFICATION_EVENT_DELETED,
    EVENT_RESTORED as SPECIFICATION_EVENT_RESTORED,
    EVENT_UPDATED as SPECIFICATION_EVENT_UPDATED,
)
from features.tasks.domain import (
    EVENT_ARCHIVED as TASK_EVENT_ARCHIVED,
    EVENT_AUTOMATION_COMPLETED as TASK_EVENT_AUTOMATION_COMPLETED,
    EVENT_AUTOMATION_FAILED as TASK_EVENT_AUTOMATION_FAILED,
    EVENT_AUTOMATION_REQUESTED as TASK_EVENT_AUTOMATION_REQUESTED,
    EVENT_AUTOMATION_STARTED as TASK_EVENT_AUTOMATION_STARTED,
    EVENT_COMMENT_ADDED as TASK_EVENT_COMMENT_ADDED,
    EVENT_COMPLETED as TASK_EVENT_COMPLETED,
    EVENT_CREATED as TASK_EVENT_CREATED,
    EVENT_DELETED as TASK_EVENT_DELETED,
    EVENT_MOVED_TO_INBOX as TASK_EVENT_MOVED_TO_INBOX,
    EVENT_REOPENED as TASK_EVENT_REOPENED,
    EVENT_REORDERED as TASK_EVENT_REORDERED,
    EVENT_RESTORED as TASK_EVENT_RESTORED,
    EVENT_SCHEDULE_COMPLETED as TASK_EVENT_SCHEDULE_COMPLETED,
    EVENT_SCHEDULE_CONFIGURED as TASK_EVENT_SCHEDULE_CONFIGURED,
    EVENT_SCHEDULE_DISABLED as TASK_EVENT_SCHEDULE_DISABLED,
    EVENT_SCHEDULE_FAILED as TASK_EVENT_SCHEDULE_FAILED,
    EVENT_SCHEDULE_QUEUED as TASK_EVENT_SCHEDULE_QUEUED,
    EVENT_SCHEDULE_STARTED as TASK_EVENT_SCHEDULE_STARTED,
    EVENT_UPDATED as TASK_EVENT_UPDATED,
    EVENT_WATCH_TOGGLED as TASK_EVENT_WATCH_TOGGLED,
)

from .contracts import EventEnvelope
from .eventing_store import get_kurrent_client
from .chat_indexing import CHAT_INDEX_MODE_KG_AND_VECTOR, normalize_chat_index_mode, project_chat_indexing_policy
from .knowledge_graph import ensure_graph_schema, graph_enabled, run_graph_query
from .observability import incr, set_value
from .settings import (
    CHAT_GRAPH_RETENTION_MODE,
    GRAPH_PROJECTION_BATCH_SIZE,
    PERSISTENT_SUBSCRIPTION_EVENT_BUFFER_SIZE,
    PERSISTENT_SUBSCRIPTION_GRAPH_GROUP,
    PERSISTENT_SUBSCRIPTION_MAX_ACK_BATCH_SIZE,
    PERSISTENT_SUBSCRIPTION_MAX_ACK_DELAY_SECONDS,
    PERSISTENT_SUBSCRIPTION_RETRY_BACKOFF_SECONDS,
    PERSISTENT_SUBSCRIPTION_STOPPING_GRACE_SECONDS,
    logger,
)

_GRAPH_CHECKPOINT_NAME = "knowledge-graph"
_graph_stop_event = threading.Event()
_graph_thread: threading.Thread | None = None
_graph_subscription: Any | None = None
_graph_subscription_lock = threading.Lock()


def _extract_aggregate_from_stream(stream_name: str) -> tuple[str, str] | None:
    if stream_name.startswith("snapshot::"):
        return None
    base, sep, raw_id = stream_name.partition("::")
    if sep != "::" or not base or not raw_id:
        return None
    return base, raw_id


def _get_graph_checkpoint(db, name: str = _GRAPH_CHECKPOINT_NAME):
    from .models import ProjectionCheckpoint

    checkpoint = db.get(ProjectionCheckpoint, name)
    if checkpoint is None:
        checkpoint = ProjectionCheckpoint(name=name, commit_position=0)
        db.add(checkpoint)
        db.flush()
    return checkpoint


def _recorded_to_envelope(event: Any) -> tuple[int, EventEnvelope] | None:
    if getattr(event, "is_system_event", False):
        return None
    if getattr(event, "is_checkpoint", False):
        return None
    if getattr(event, "is_caught_up", False):
        return None
    if getattr(event, "is_fell_behind", False):
        return None

    commit_position = int(getattr(event, "commit_position", -1))
    parsed = _extract_aggregate_from_stream(getattr(event, "stream_name", ""))
    if parsed is None:
        return None
    aggregate_type, aggregate_id = parsed
    env = EventEnvelope(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        version=int(event.stream_position) + 1,
        event_type=event.type,
        payload=json.loads((event.data or b"{}").decode("utf-8")),
        metadata=json.loads((event.metadata or b"{}").decode("utf-8")),
    )
    return commit_position, env


def _clean_props(data: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if not key or key == "id":
            continue
        cleaned[key] = _to_neo4j_property(value)
    return cleaned


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool))


def _to_neo4j_property(value: Any) -> Any:
    if value is None:
        return None
    if _is_scalar(value):
        return value
    if isinstance(value, dict):
        # Neo4j node properties cannot be maps; preserve data as JSON text.
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, list):
        if not value:
            return []
        if all(_is_scalar(item) for item in value):
            return value
        # Nested values (map/list) are unsupported in Neo4j properties.
        return json.dumps(value, separators=(",", ":"))
    return str(value)


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_tag_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    tags: list[str] = []
    for item in raw:
        tag = str(item or "").strip().lower()
        if not tag:
            continue
        if tag not in tags:
            tags.append(tag)
    return tags


def _json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _retention_mode_purges(retention_mode: str | None) -> bool:
    normalized = str(retention_mode or "purge").strip().lower()
    return normalized != "keep"


def purge_project_chat_graph(
    project_id: str,
    *,
    retention_mode: str | None = None,
    force: bool = False,
) -> int:
    if not graph_enabled():
        return 0
    if not force and not _retention_mode_purges(retention_mode if retention_mode is not None else CHAT_GRAPH_RETENTION_MODE):
        return 0
    pid = _as_str(project_id)
    if not pid:
        return 0

    deleted_total = 0
    for label in ("ChatAttachment", "ChatMessage", "ChatSession"):
        count_rows = run_graph_query(
            f"""
            MATCH (n:{label})
            WHERE coalesce(n.project_id, '') = $project_id
            RETURN count(n) AS count
            """,
            {"project_id": pid},
            write=False,
        )
        count = int((count_rows[0] if count_rows else {}).get("count") or 0)
        if count > 0:
            run_graph_query(
                f"""
                MATCH (n:{label})
                WHERE coalesce(n.project_id, '') = $project_id
                DETACH DELETE n
                """,
                {"project_id": pid},
                write=True,
            )
        deleted_total += count
    return deleted_total


def backfill_project_chat_graph(project_id: str) -> dict[str, int]:
    from .models import ChatAttachment, ChatMessage, ChatMessageResourceLink, ChatSession, SessionLocal

    if not graph_enabled():
        return {"sessions": 0, "messages": 0, "attachments": 0, "resource_links": 0, "nodes_touched": 0}
    pid = _as_str(project_id)
    if not pid:
        return {"sessions": 0, "messages": 0, "attachments": 0, "resource_links": 0, "nodes_touched": 0}

    with SessionLocal() as db:
        sessions = db.execute(select(ChatSession).where(ChatSession.project_id == pid)).scalars().all()
        messages = db.execute(select(ChatMessage).where(ChatMessage.project_id == pid)).scalars().all()
        attachments = db.execute(select(ChatAttachment).where(ChatAttachment.project_id == pid)).scalars().all()
        resource_links = db.execute(
            select(ChatMessageResourceLink).where(ChatMessageResourceLink.project_id == pid)
        ).scalars().all()

    session_count = 0
    message_count = 0
    attachment_count = 0
    resource_link_count = 0

    for session in sessions:
        session_id = _as_str(session.id)
        if not session_id:
            continue
        workspace_id = _as_str(session.workspace_id)
        project_id_value = _as_str(session.project_id)
        props: dict[str, Any] = {
            "workspace_id": workspace_id,
            "project_id": project_id_value,
            "session_key": session.session_key,
            "title": session.title,
            "created_by": session.created_by,
            "is_archived": bool(session.is_archived),
            "codex_session_id": session.codex_session_id,
            "mcp_servers": _json_list(session.mcp_servers),
            "session_attachment_refs": _json_list(session.session_attachment_refs),
            "usage": _json_dict(session.usage_json),
            "last_message_at": session.last_message_at,
            "last_message_preview": session.last_message_preview,
            "last_task_event_at": session.last_task_event_at,
            "last_event_type": "ChatPolicyBackfill",
            "last_event_version": 0,
            "last_commit_position": -1,
        }
        _merge_node("ChatSession", session_id, props)
        if workspace_id:
            _merge_node("Workspace", workspace_id, {})
        _sync_optional_relation(
            source_label="ChatSession",
            source_id=session_id,
            relation="IN_WORKSPACE",
            target_label="Workspace",
            target_id=workspace_id,
        )
        _sync_optional_relation(
            source_label="ChatSession",
            source_id=session_id,
            relation="IN_PROJECT",
            target_label="Project",
            target_id=project_id_value,
            target_props={"workspace_id": workspace_id},
        )
        created_by = _as_str(session.created_by)
        if created_by:
            _merge_node("User", created_by, {})
            run_graph_query(
                """
                MATCH (s:ChatSession {id:$session_id})
                MATCH (u:User {id:$user_id})
                MERGE (s)-[:STARTED_BY]->(u)
                """,
                {
                    "session_id": session_id,
                    "user_id": created_by,
                },
                write=True,
            )
        session_count += 1

    for message in messages:
        session_id = _as_str(message.session_id)
        message_id = _as_str(message.id)
        if not session_id or not message_id:
            continue
        workspace_id = _as_str(message.workspace_id)
        project_id_value = _as_str(message.project_id)
        role = str(message.role or "").strip().lower()
        if role not in {"user", "assistant"}:
            role = "message"
        props: dict[str, Any] = {
            "workspace_id": workspace_id,
            "project_id": project_id_value,
            "session_id": session_id,
            "role": role,
            "content": message.content or "",
            "order_index": message.order_index,
            "created_at": message.turn_created_at,
            "attachment_refs": _json_list(message.attachment_refs),
            "usage": _json_dict(message.usage_json),
            "is_deleted": bool(message.is_deleted),
            "last_event_type": "ChatPolicyBackfill",
            "last_event_version": 0,
            "last_commit_position": -1,
        }
        _merge_node(
            "ChatSession",
            session_id,
            {
                "workspace_id": workspace_id,
                "project_id": project_id_value,
                "last_commit_position": -1,
            },
        )
        _merge_node("ChatMessage", message_id, props)
        if workspace_id:
            _merge_node("Workspace", workspace_id, {})
        _sync_optional_relation(
            source_label="ChatMessage",
            source_id=message_id,
            relation="IN_WORKSPACE",
            target_label="Workspace",
            target_id=workspace_id,
        )
        _sync_optional_relation(
            source_label="ChatMessage",
            source_id=message_id,
            relation="IN_PROJECT",
            target_label="Project",
            target_id=project_id_value,
            target_props={"workspace_id": workspace_id},
        )
        run_graph_query(
            """
            MATCH (s:ChatSession {id:$session_id})
            MATCH (m:ChatMessage {id:$message_id})
            MERGE (s)-[:HAS_MESSAGE]->(m)
            """,
            {
                "session_id": session_id,
                "message_id": message_id,
            },
            write=True,
        )
        message_count += 1

    for attachment in attachments:
        session_id = _as_str(attachment.session_id)
        message_id = _as_str(attachment.message_id)
        attachment_id = _as_str(attachment.id)
        if not session_id or not message_id or not attachment_id:
            continue
        workspace_id = _as_str(attachment.workspace_id)
        project_id_value = _as_str(attachment.project_id)
        props: dict[str, Any] = {
            "workspace_id": workspace_id,
            "project_id": project_id_value,
            "session_id": session_id,
            "message_id": message_id,
            "path": attachment.path,
            "name": attachment.name,
            "mime_type": attachment.mime_type,
            "size_bytes": attachment.size_bytes,
            "checksum": attachment.checksum,
            "extraction_status": attachment.extraction_status,
            "extracted_text": attachment.extracted_text,
            "is_deleted": bool(attachment.is_deleted),
            "last_event_type": "ChatPolicyBackfill",
            "last_event_version": 0,
            "last_commit_position": -1,
        }
        _merge_node("ChatAttachment", attachment_id, props)
        if workspace_id:
            _merge_node("Workspace", workspace_id, {})
        _sync_optional_relation(
            source_label="ChatAttachment",
            source_id=attachment_id,
            relation="IN_WORKSPACE",
            target_label="Workspace",
            target_id=workspace_id,
        )
        _sync_optional_relation(
            source_label="ChatAttachment",
            source_id=attachment_id,
            relation="IN_PROJECT",
            target_label="Project",
            target_id=project_id_value,
            target_props={"workspace_id": workspace_id},
        )
        run_graph_query(
            """
            MATCH (m:ChatMessage {id:$message_id})
            MATCH (a:ChatAttachment {id:$attachment_id})
            MERGE (m)-[:HAS_ATTACHMENT]->(a)
            """,
            {
                "message_id": message_id,
                "attachment_id": attachment_id,
            },
            write=True,
        )
        run_graph_query(
            """
            MATCH (s:ChatSession {id:$session_id})
            MATCH (a:ChatAttachment {id:$attachment_id})
            MERGE (s)-[:HAS_ATTACHMENT]->(a)
            """,
            {
                "session_id": session_id,
                "attachment_id": attachment_id,
            },
            write=True,
        )
        attachment_count += 1

    for link in resource_links:
        session_id = _as_str(link.session_id)
        message_id = _as_str(link.message_id)
        resource_id = _as_str(link.resource_id)
        resource_label = _chat_resource_label(link.resource_type)
        if not session_id or not message_id or not resource_id or not resource_label:
            continue
        workspace_id = _as_str(link.workspace_id)
        project_id_value = _as_str(link.project_id)
        _merge_node(
            "ChatSession",
            session_id,
            {
                "workspace_id": workspace_id,
                "project_id": project_id_value,
                "last_commit_position": -1,
            },
        )
        _merge_node(
            "ChatMessage",
            message_id,
            {
                "workspace_id": workspace_id,
                "project_id": project_id_value,
                "session_id": session_id,
                "last_commit_position": -1,
            },
        )
        _merge_node(
            resource_label,
            resource_id,
            {
                "workspace_id": workspace_id,
                "project_id": project_id_value,
            },
        )

        relation_type = _chat_relation_type(link.relation)
        run_graph_query(
            f"""
            MATCH (m:ChatMessage {{id:$message_id}})
            MATCH (r:{resource_label} {{id:$resource_id}})
            MERGE (m)-[:{relation_type}]->(r)
            """,
            {
                "message_id": message_id,
                "resource_id": resource_id,
            },
            write=True,
        )
        run_graph_query(
            f"""
            MATCH (s:ChatSession {{id:$session_id}})
            MATCH (r:{resource_label} {{id:$resource_id}})
            MERGE (r)-[:DISCUSSED_IN]->(s)
            MERGE (s)-[:REFERENCES_RESOURCE]->(r)
            """,
            {
                "session_id": session_id,
                "resource_id": resource_id,
            },
            write=True,
        )
        resource_link_count += 1

    return {
        "sessions": session_count,
        "messages": message_count,
        "attachments": attachment_count,
        "resource_links": resource_link_count,
        "nodes_touched": session_count + message_count + attachment_count + resource_link_count,
    }


def sync_project_chat_graph_for_policy(
    project_id: str,
    *,
    force_purge: bool = False,
    retention_mode: str | None = None,
) -> dict[str, int]:
    if not graph_enabled():
        return {"deleted_nodes": 0, "synced_nodes": 0}
    pid = _as_str(project_id)
    if not pid:
        return {"deleted_nodes": 0, "synced_nodes": 0}
    if force_purge:
        deleted = purge_project_chat_graph(pid, retention_mode=retention_mode, force=True)
        return {"deleted_nodes": deleted, "synced_nodes": 0}

    if not _chat_graph_enabled_for_project(pid):
        deleted = purge_project_chat_graph(pid, retention_mode=retention_mode, force=False)
        return {"deleted_nodes": deleted, "synced_nodes": 0}

    backfill = backfill_project_chat_graph(pid)
    return {"deleted_nodes": 0, "synced_nodes": int(backfill.get("nodes_touched") or 0)}


def _chat_graph_enabled_for_project(project_id: str | None) -> bool:
    pid = _as_str(project_id)
    if not pid:
        return False
    rows = run_graph_query(
        """
        MATCH (p:Project {id:$project_id})
        RETURN coalesce(p.chat_index_mode, 'OFF') AS chat_index_mode, coalesce(p.is_deleted, false) AS is_deleted
        LIMIT 1
        """,
        {"project_id": pid},
        write=False,
    )
    if not rows:
        return False
    row = rows[0]
    if bool(row.get("is_deleted", False)):
        return False
    policy = project_chat_indexing_policy(
        chat_index_mode=normalize_chat_index_mode(str(row.get("chat_index_mode") or "OFF")),
        chat_attachment_ingestion_mode=None,
    )
    return bool(policy.graph_enabled)


def _chat_resource_label(resource_type: str | None) -> str | None:
    key = str(resource_type or "").strip().lower().replace("-", "").replace("_", "")
    if key == "task":
        return "Task"
    if key == "note":
        return "Note"
    if key == "specification":
        return "Specification"
    if key in {"projectrule", "rule"}:
        return "ProjectRule"
    return None


def _chat_relation_type(relation: str | None) -> str:
    raw = str(relation or "").strip().upper().replace("-", "_").replace(" ", "_")
    if raw == "CREATED":
        return "CREATED"
    if raw in {"MENTIONED", "MENTIONS"}:
        return "MENTIONS"
    if raw in {"UPDATED", "MODIFIED"}:
        return "UPDATED"
    return "LINKED"


def _merge_node(label: str, node_id: str | None, props: dict[str, Any]) -> None:
    nid = _as_str(node_id)
    if not nid:
        return
    run_graph_query(
        f"MERGE (n:{label} {{id:$node_id}}) SET n += $props",
        {
            "node_id": nid,
            "props": _clean_props(props),
        },
        write=True,
    )


def _sync_optional_relation(
    *,
    source_label: str,
    source_id: str | None,
    relation: str,
    target_label: str,
    target_id: str | None,
    target_props: dict[str, Any] | None = None,
) -> None:
    sid = _as_str(source_id)
    if not sid:
        return
    run_graph_query(
        f"MATCH (n:{source_label} {{id:$source_id}}) OPTIONAL MATCH (n)-[old:{relation}]->(:{target_label}) DELETE old",
        {"source_id": sid},
        write=True,
    )
    tid = _as_str(target_id)
    if not tid:
        return
    run_graph_query(
        f"""
        MATCH (n:{source_label} {{id:$source_id}})
        MERGE (t:{target_label} {{id:$target_id}})
        SET t += $target_props
        MERGE (n)-[:{relation}]->(t)
        """,
        {
            "source_id": sid,
            "target_id": tid,
            "target_props": _clean_props(target_props or {}),
        },
        write=True,
    )


def _sync_tags(*, source_label: str, source_id: str | None, tags: list[str]) -> None:
    sid = _as_str(source_id)
    if not sid:
        return
    run_graph_query(
        f"MATCH (n:{source_label} {{id:$source_id}}) OPTIONAL MATCH (n)-[r:TAGGED_WITH]->(:Tag) DELETE r",
        {"source_id": sid},
        write=True,
    )
    if not tags:
        return
    run_graph_query(
        f"""
        MATCH (n:{source_label} {{id:$source_id}})
        UNWIND $tags AS tag
        MERGE (t:Tag {{value: tag}})
        MERGE (n)-[:TAGGED_WITH]->(t)
        """,
        {
            "source_id": sid,
            "tags": tags,
        },
        write=True,
    )


def _toggle_task_watcher(task_id: str | None, user_id: str | None, watched: bool | None = None) -> None:
    tid = _as_str(task_id)
    uid = _as_str(user_id)
    if not tid or not uid:
        return
    _merge_node("Task", tid, {})
    _merge_node("User", uid, {})
    if watched is True:
        run_graph_query(
            """
            MATCH (t:Task {id:$task_id})
            MATCH (u:User {id:$user_id})
            MERGE (t)-[:WATCHED_BY]->(u)
            """,
            {
                "task_id": tid,
                "user_id": uid,
            },
            write=True,
        )
        return
    if watched is False:
        run_graph_query(
            """
            MATCH (t:Task {id:$task_id})
            MATCH (u:User {id:$user_id})
            OPTIONAL MATCH (t)-[w:WATCHED_BY]->(u)
            DELETE w
            """,
            {
                "task_id": tid,
                "user_id": uid,
            },
            write=True,
        )
        return
    run_graph_query(
        """
        MATCH (t:Task {id:$task_id})
        MATCH (u:User {id:$user_id})
        OPTIONAL MATCH (t)-[w:WATCHED_BY]->(u)
        WITH t, u, w
        FOREACH (_ IN CASE WHEN w IS NULL THEN [1] ELSE [] END | MERGE (t)-[:WATCHED_BY]->(u))
        FOREACH (_ IN CASE WHEN w IS NOT NULL THEN [1] ELSE [] END | DELETE w)
        """,
        {
            "task_id": tid,
            "user_id": uid,
        },
        write=True,
    )


def _register_task_comment(task_id: str | None, user_id: str | None, version: int) -> None:
    tid = _as_str(task_id)
    uid = _as_str(user_id)
    if not tid or not uid:
        return
    _merge_node("Task", tid, {})
    _merge_node("User", uid, {})
    run_graph_query(
        """
        MATCH (t:Task {id:$task_id})
        MATCH (u:User {id:$user_id})
        MERGE (t)-[r:COMMENTED_BY]->(u)
        ON CREATE SET r.count = 1
        ON MATCH SET r.count = coalesce(r.count, 0) + 1
        SET r.last_comment_event_version = $event_version,
            r.last_commented_at = timestamp()
        """,
        {
            "task_id": tid,
            "user_id": uid,
            "event_version": int(version),
        },
        write=True,
    )


def _project_project_event(ev: EventEnvelope, commit_position: int) -> None:
    p = ev.payload or {}
    workspace_id = _as_str(p.get("workspace_id") or ev.metadata.get("workspace_id"))
    props: dict[str, Any] = {
        "workspace_id": workspace_id,
        "last_event_type": ev.event_type,
        "last_event_version": ev.version,
        "last_commit_position": commit_position,
    }
    for key in (
        "name",
        "description",
        "status",
        "custom_statuses",
        "external_refs",
        "attachment_refs",
        "embedding_enabled",
        "embedding_model",
        "context_pack_evidence_top_k",
        "chat_index_mode",
        "chat_attachment_ingestion_mode",
    ):
        if key in p:
            props[key] = p.get(key)
    if ev.event_type == PROJECT_EVENT_CREATED:
        props["is_deleted"] = False
    if ev.event_type == PROJECT_EVENT_DELETED:
        props["is_deleted"] = True

    _merge_node("Project", ev.aggregate_id, props)
    if workspace_id:
        _merge_node("Workspace", workspace_id, {})
    _sync_optional_relation(
        source_label="Project",
        source_id=ev.aggregate_id,
        relation="IN_WORKSPACE",
        target_label="Workspace",
        target_id=workspace_id,
    )


def _task_props_from_event(ev: EventEnvelope) -> dict[str, Any]:
    p = ev.payload or {}
    props: dict[str, Any] = {
        "last_event_type": ev.event_type,
        "last_event_version": ev.version,
    }
    for key in (
        "workspace_id",
        "project_id",
        "specification_id",
        "title",
        "description",
        "status",
        "priority",
        "due_date",
        "assignee_id",
        "assigned_agent_code",
        "labels",
        "instruction",
        "execution_triggers",
        "task_type",
        "scheduled_instruction",
        "scheduled_at_utc",
        "schedule_timezone",
        "schedule_state",
        "last_schedule_run_at",
        "last_schedule_error",
        "recurring_rule",
        "order_index",
        "completed_at",
    ):
        if key in p:
            props[key] = p.get(key)

    if ev.event_type == TASK_EVENT_CREATED:
        props.setdefault("archived", False)
        props.setdefault("is_deleted", False)
        props.setdefault("automation_state", "idle")
    elif ev.event_type == TASK_EVENT_COMPLETED:
        props["status"] = "Done"
        props["completed_at"] = p.get("completed_at")
    elif ev.event_type == TASK_EVENT_REOPENED:
        props["status"] = p.get("status", "To do")
        props["completed_at"] = None
    elif ev.event_type == TASK_EVENT_ARCHIVED:
        props["archived"] = True
    elif ev.event_type == TASK_EVENT_RESTORED:
        props["archived"] = False
    elif ev.event_type == TASK_EVENT_DELETED:
        props["is_deleted"] = True
    elif ev.event_type == TASK_EVENT_MOVED_TO_INBOX:
        props["project_id"] = None
    elif ev.event_type == TASK_EVENT_AUTOMATION_REQUESTED:
        props["automation_state"] = "queued"
        props["last_agent_error"] = None
        props["last_requested_instruction"] = p.get("instruction")
        props["last_requested_source"] = p.get("source")
        props["last_requested_trigger_task_id"] = p.get("trigger_task_id")
        props["last_requested_from_status"] = p.get("from_status")
        props["last_requested_to_status"] = p.get("to_status")
        props["last_requested_triggered_at"] = p.get("triggered_at")
    elif ev.event_type == TASK_EVENT_AUTOMATION_STARTED:
        props["automation_state"] = "running"
        props["last_agent_error"] = None
        props["last_agent_run_at"] = p.get("started_at")
    elif ev.event_type == TASK_EVENT_AUTOMATION_COMPLETED:
        props["automation_state"] = "completed"
        props["last_agent_run_at"] = p.get("completed_at")
        props["last_agent_error"] = None
        props["last_agent_comment"] = p.get("summary")
    elif ev.event_type == TASK_EVENT_AUTOMATION_FAILED:
        props["automation_state"] = "failed"
        props["last_agent_run_at"] = p.get("failed_at")
        props["last_agent_error"] = p.get("error")
        props["last_agent_comment"] = p.get("summary")
    elif ev.event_type == TASK_EVENT_SCHEDULE_CONFIGURED:
        props["task_type"] = "scheduled_instruction"
        props["scheduled_instruction"] = p.get("scheduled_instruction")
        props["scheduled_at_utc"] = p.get("scheduled_at_utc")
        props["schedule_timezone"] = p.get("schedule_timezone")
        props["schedule_state"] = p.get("schedule_state", "idle")
        props["last_schedule_error"] = None
    elif ev.event_type == TASK_EVENT_SCHEDULE_QUEUED:
        props["schedule_state"] = "queued"
        props["last_schedule_error"] = None
    elif ev.event_type == TASK_EVENT_SCHEDULE_STARTED:
        props["schedule_state"] = "running"
        props["last_schedule_error"] = None
        props["last_schedule_run_at"] = p.get("started_at")
    elif ev.event_type == TASK_EVENT_SCHEDULE_COMPLETED:
        props["schedule_state"] = "done"
        props["last_schedule_error"] = None
        props["last_schedule_run_at"] = p.get("completed_at")
    elif ev.event_type == TASK_EVENT_SCHEDULE_FAILED:
        props["schedule_state"] = "failed"
        props["last_schedule_error"] = p.get("error")
        props["last_schedule_run_at"] = p.get("failed_at")
    elif ev.event_type == TASK_EVENT_SCHEDULE_DISABLED:
        props["task_type"] = "manual"
        props["scheduled_instruction"] = None
        props["scheduled_at_utc"] = None
        props["schedule_timezone"] = None
        props["schedule_state"] = "idle"
        props["last_schedule_error"] = None

    return props


def _project_task_event(ev: EventEnvelope, commit_position: int) -> None:
    p = ev.payload or {}
    metadata = ev.metadata or {}
    task_id = _as_str(ev.aggregate_id) or _as_str(p.get("task_id"))
    if not task_id:
        return

    props = _task_props_from_event(ev)
    props["last_commit_position"] = commit_position

    workspace_id = _as_str(props.get("workspace_id") or metadata.get("workspace_id"))
    if workspace_id and "workspace_id" not in props:
        props["workspace_id"] = workspace_id

    _merge_node("Task", task_id, props)

    if workspace_id:
        _merge_node("Workspace", workspace_id, {})
    _sync_optional_relation(
        source_label="Task",
        source_id=task_id,
        relation="IN_WORKSPACE",
        target_label="Workspace",
        target_id=workspace_id,
    )

    if ev.event_type in {TASK_EVENT_CREATED, TASK_EVENT_MOVED_TO_INBOX} or "project_id" in p:
        project_id = _as_str(props.get("project_id"))
        _sync_optional_relation(
            source_label="Task",
            source_id=task_id,
            relation="IN_PROJECT",
            target_label="Project",
            target_id=project_id,
            target_props={"workspace_id": workspace_id},
        )

    if ev.event_type == TASK_EVENT_CREATED or "specification_id" in p:
        _sync_optional_relation(
            source_label="Task",
            source_id=task_id,
            relation="IMPLEMENTS",
            target_label="Specification",
            target_id=_as_str(props.get("specification_id")),
            target_props={"project_id": _as_str(props.get("project_id")), "workspace_id": workspace_id},
        )

    if ev.event_type == TASK_EVENT_CREATED or "assignee_id" in p:
        assignee_id = _as_str(props.get("assignee_id"))
        if assignee_id:
            _merge_node("User", assignee_id, {})
        _sync_optional_relation(
            source_label="Task",
            source_id=task_id,
            relation="ASSIGNED_TO",
            target_label="User",
            target_id=assignee_id,
        )

    if ev.event_type == TASK_EVENT_CREATED or "labels" in p:
        _sync_tags(source_label="Task", source_id=task_id, tags=_as_tag_list(props.get("labels")))

    if ev.event_type == TASK_EVENT_WATCH_TOGGLED:
        watched_payload = p.get("watched")
        watched_value = None if watched_payload is None else bool(watched_payload)
        _toggle_task_watcher(task_id, _as_str(p.get("user_id")), watched_value)

    if ev.event_type == TASK_EVENT_COMMENT_ADDED:
        _register_task_comment(task_id, _as_str(p.get("user_id")), ev.version)


def _note_props_from_event(ev: EventEnvelope) -> dict[str, Any]:
    p = ev.payload or {}
    props: dict[str, Any] = {
        "last_event_type": ev.event_type,
        "last_event_version": ev.version,
    }
    for key in (
        "workspace_id",
        "project_id",
        "task_id",
        "specification_id",
        "title",
        "body",
        "tags",
        "external_refs",
        "attachment_refs",
        "pinned",
        "archived",
        "is_deleted",
        "created_by",
        "updated_by",
    ):
        if key in p:
            props[key] = p.get(key)

    if ev.event_type == NOTE_EVENT_ARCHIVED:
        props["archived"] = True
    elif ev.event_type == NOTE_EVENT_RESTORED:
        props["archived"] = False
    elif ev.event_type == NOTE_EVENT_PINNED:
        props["pinned"] = True
    elif ev.event_type == NOTE_EVENT_UNPINNED:
        props["pinned"] = False
    elif ev.event_type == NOTE_EVENT_DELETED:
        props["is_deleted"] = True
    return props


def _project_note_event(ev: EventEnvelope, commit_position: int) -> None:
    p = ev.payload or {}
    metadata = ev.metadata or {}
    note_id = _as_str(ev.aggregate_id)
    if not note_id:
        return

    props = _note_props_from_event(ev)
    props["last_commit_position"] = commit_position
    workspace_id = _as_str(props.get("workspace_id") or metadata.get("workspace_id"))
    if workspace_id and "workspace_id" not in props:
        props["workspace_id"] = workspace_id

    _merge_node("Note", note_id, props)

    if workspace_id:
        _merge_node("Workspace", workspace_id, {})
    _sync_optional_relation(
        source_label="Note",
        source_id=note_id,
        relation="IN_WORKSPACE",
        target_label="Workspace",
        target_id=workspace_id,
    )

    if ev.event_type == NOTE_EVENT_CREATED or "project_id" in p:
        _sync_optional_relation(
            source_label="Note",
            source_id=note_id,
            relation="IN_PROJECT",
            target_label="Project",
            target_id=_as_str(props.get("project_id")),
            target_props={"workspace_id": workspace_id},
        )

    if ev.event_type == NOTE_EVENT_CREATED or "task_id" in p:
        _sync_optional_relation(
            source_label="Note",
            source_id=note_id,
            relation="ABOUT_TASK",
            target_label="Task",
            target_id=_as_str(props.get("task_id")),
        )

    if ev.event_type == NOTE_EVENT_CREATED or "specification_id" in p:
        _sync_optional_relation(
            source_label="Note",
            source_id=note_id,
            relation="ABOUT_SPECIFICATION",
            target_label="Specification",
            target_id=_as_str(props.get("specification_id")),
            target_props={"project_id": _as_str(props.get("project_id")), "workspace_id": workspace_id},
        )

    if ev.event_type == NOTE_EVENT_CREATED or "tags" in p:
        _sync_tags(source_label="Note", source_id=note_id, tags=_as_tag_list(props.get("tags")))


def _specification_props_from_event(ev: EventEnvelope) -> dict[str, Any]:
    p = ev.payload or {}
    props: dict[str, Any] = {
        "last_event_type": ev.event_type,
        "last_event_version": ev.version,
    }
    for key in (
        "workspace_id",
        "project_id",
        "title",
        "body",
        "status",
        "tags",
        "external_refs",
        "attachment_refs",
        "created_by",
        "updated_by",
        "archived",
        "is_deleted",
    ):
        if key in p:
            props[key] = p.get(key)

    if ev.event_type == SPECIFICATION_EVENT_ARCHIVED:
        props["archived"] = True
        props["status"] = "Archived"
    elif ev.event_type == SPECIFICATION_EVENT_RESTORED:
        props["archived"] = False
    elif ev.event_type == SPECIFICATION_EVENT_DELETED:
        props["is_deleted"] = True
    return props


def _project_specification_event(ev: EventEnvelope, commit_position: int) -> None:
    p = ev.payload or {}
    metadata = ev.metadata or {}
    specification_id = _as_str(ev.aggregate_id)
    if not specification_id:
        return

    props = _specification_props_from_event(ev)
    props["last_commit_position"] = commit_position
    workspace_id = _as_str(props.get("workspace_id") or metadata.get("workspace_id"))
    project_id = _as_str(props.get("project_id") or metadata.get("project_id"))

    _merge_node("Specification", specification_id, props)
    if workspace_id:
        _merge_node("Workspace", workspace_id, {})
    _sync_optional_relation(
        source_label="Specification",
        source_id=specification_id,
        relation="IN_WORKSPACE",
        target_label="Workspace",
        target_id=workspace_id,
    )
    _sync_optional_relation(
        source_label="Specification",
        source_id=specification_id,
        relation="IN_PROJECT",
        target_label="Project",
        target_id=project_id,
        target_props={"workspace_id": workspace_id},
    )

    if ev.event_type == SPECIFICATION_EVENT_CREATED or "tags" in p:
        _sync_tags(source_label="Specification", source_id=specification_id, tags=_as_tag_list(props.get("tags")))


def _project_rule_props_from_event(ev: EventEnvelope) -> dict[str, Any]:
    p = ev.payload or {}
    props: dict[str, Any] = {
        "last_event_type": ev.event_type,
        "last_event_version": ev.version,
    }
    for key in ("workspace_id", "project_id", "title", "body", "created_by", "updated_by", "is_deleted"):
        if key in p:
            props[key] = p.get(key)
    if ev.event_type == PROJECT_RULE_EVENT_DELETED:
        props["is_deleted"] = True
    return props


def _project_project_rule_event(ev: EventEnvelope, commit_position: int) -> None:
    metadata = ev.metadata or {}
    rule_id = _as_str(ev.aggregate_id)
    if not rule_id:
        return

    props = _project_rule_props_from_event(ev)
    props["last_commit_position"] = commit_position
    workspace_id = _as_str(props.get("workspace_id") or metadata.get("workspace_id"))
    project_id = _as_str(props.get("project_id") or metadata.get("project_id"))

    _merge_node("ProjectRule", rule_id, props)
    if workspace_id:
        _merge_node("Workspace", workspace_id, {})
    _sync_optional_relation(
        source_label="ProjectRule",
        source_id=rule_id,
        relation="IN_WORKSPACE",
        target_label="Workspace",
        target_id=workspace_id,
    )
    _sync_optional_relation(
        source_label="ProjectRule",
        source_id=rule_id,
        relation="IN_PROJECT",
        target_label="Project",
        target_id=project_id,
        target_props={"workspace_id": workspace_id},
    )


def _project_chat_session_event(ev: EventEnvelope, commit_position: int) -> None:
    p = ev.payload or {}
    m = ev.metadata or {}
    session_id = _as_str(ev.aggregate_id)
    if not session_id:
        return
    workspace_id = _as_str(p.get("workspace_id") or m.get("workspace_id"))
    project_id = _as_str(p.get("project_id") or m.get("project_id"))
    if project_id and not _chat_graph_enabled_for_project(project_id):
        return

    props: dict[str, Any] = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "last_event_type": ev.event_type,
        "last_event_version": ev.version,
        "last_commit_position": commit_position,
    }
    for key in (
        "session_key",
        "title",
        "created_by",
        "is_archived",
        "codex_session_id",
        "mcp_servers",
        "session_attachment_refs",
        "usage",
        "last_message_at",
        "last_message_preview",
        "last_task_event_at",
    ):
        if key in p:
            props[key] = p.get(key)
    if ev.event_type == CHAT_SESSION_EVENT_ARCHIVED:
        props["is_archived"] = True

    _merge_node("ChatSession", session_id, props)
    if workspace_id:
        _merge_node("Workspace", workspace_id, {})
    _sync_optional_relation(
        source_label="ChatSession",
        source_id=session_id,
        relation="IN_WORKSPACE",
        target_label="Workspace",
        target_id=workspace_id,
    )
    _sync_optional_relation(
        source_label="ChatSession",
        source_id=session_id,
        relation="IN_PROJECT",
        target_label="Project",
        target_id=project_id,
        target_props={"workspace_id": workspace_id},
    )

    created_by = _as_str(p.get("created_by"))
    if created_by:
        _merge_node("User", created_by, {})
        run_graph_query(
            """
            MATCH (s:ChatSession {id:$session_id})
            MATCH (u:User {id:$user_id})
            MERGE (s)-[:STARTED_BY]->(u)
            """,
            {
                "session_id": session_id,
                "user_id": created_by,
            },
            write=True,
        )


def _project_chat_message_event(ev: EventEnvelope, commit_position: int) -> None:
    p = ev.payload or {}
    m = ev.metadata or {}
    session_id = _as_str(ev.aggregate_id)
    message_id = _as_str(p.get("message_id"))
    if not session_id or not message_id:
        return
    workspace_id = _as_str(p.get("workspace_id") or m.get("workspace_id"))
    project_id = _as_str(p.get("project_id") or m.get("project_id"))
    if project_id and not _chat_graph_enabled_for_project(project_id):
        return

    role = str(p.get("role") or "").strip().lower()
    if not role:
        role = "assistant" if ev.event_type in {CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_APPENDED, CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_UPDATED} else "user"
    props: dict[str, Any] = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "session_id": session_id,
        "role": role,
        "last_event_type": ev.event_type,
        "last_event_version": ev.version,
        "last_commit_position": commit_position,
    }
    for key in ("content", "order_index", "created_at", "attachment_refs", "usage"):
        if key in p:
            props[key] = p.get(key)
    if ev.event_type == CHAT_SESSION_EVENT_MESSAGE_DELETED:
        props["is_deleted"] = True

    _merge_node(
        "ChatSession",
        session_id,
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "last_commit_position": commit_position,
        },
    )
    _merge_node("ChatMessage", message_id, props)
    if workspace_id:
        _merge_node("Workspace", workspace_id, {})
    _sync_optional_relation(
        source_label="ChatMessage",
        source_id=message_id,
        relation="IN_WORKSPACE",
        target_label="Workspace",
        target_id=workspace_id,
    )
    _sync_optional_relation(
        source_label="ChatMessage",
        source_id=message_id,
        relation="IN_PROJECT",
        target_label="Project",
        target_id=project_id,
        target_props={"workspace_id": workspace_id},
    )
    run_graph_query(
        """
        MATCH (s:ChatSession {id:$session_id})
        MATCH (m:ChatMessage {id:$message_id})
        MERGE (s)-[:HAS_MESSAGE]->(m)
        """,
        {
            "session_id": session_id,
            "message_id": message_id,
        },
        write=True,
    )


def _project_chat_attachment_event(ev: EventEnvelope, commit_position: int) -> None:
    p = ev.payload or {}
    m = ev.metadata or {}
    session_id = _as_str(ev.aggregate_id)
    message_id = _as_str(p.get("message_id"))
    attachment_id = _as_str(p.get("attachment_id"))
    if not session_id or not message_id or not attachment_id:
        return
    workspace_id = _as_str(p.get("workspace_id") or m.get("workspace_id"))
    project_id = _as_str(p.get("project_id") or m.get("project_id"))
    if project_id and not _chat_graph_enabled_for_project(project_id):
        return

    props: dict[str, Any] = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "session_id": session_id,
        "message_id": message_id,
        "last_event_type": ev.event_type,
        "last_event_version": ev.version,
        "last_commit_position": commit_position,
    }
    for key in ("path", "name", "mime_type", "size_bytes", "checksum", "extraction_status", "extracted_text"):
        if key in p:
            props[key] = p.get(key)
    _merge_node("ChatAttachment", attachment_id, props)
    if workspace_id:
        _merge_node("Workspace", workspace_id, {})
    _sync_optional_relation(
        source_label="ChatAttachment",
        source_id=attachment_id,
        relation="IN_WORKSPACE",
        target_label="Workspace",
        target_id=workspace_id,
    )
    _sync_optional_relation(
        source_label="ChatAttachment",
        source_id=attachment_id,
        relation="IN_PROJECT",
        target_label="Project",
        target_id=project_id,
        target_props={"workspace_id": workspace_id},
    )
    run_graph_query(
        """
        MATCH (m:ChatMessage {id:$message_id})
        MATCH (a:ChatAttachment {id:$attachment_id})
        MERGE (m)-[:HAS_ATTACHMENT]->(a)
        """,
        {
            "message_id": message_id,
            "attachment_id": attachment_id,
        },
        write=True,
    )
    run_graph_query(
        """
        MATCH (s:ChatSession {id:$session_id})
        MATCH (a:ChatAttachment {id:$attachment_id})
        MERGE (s)-[:HAS_ATTACHMENT]->(a)
        """,
        {
            "session_id": session_id,
            "attachment_id": attachment_id,
        },
        write=True,
    )


def _project_chat_resource_link_event(ev: EventEnvelope, commit_position: int) -> None:
    p = ev.payload or {}
    m = ev.metadata or {}
    session_id = _as_str(ev.aggregate_id)
    message_id = _as_str(p.get("message_id"))
    resource_id = _as_str(p.get("resource_id"))
    resource_label = _chat_resource_label(p.get("resource_type"))
    if not session_id or not message_id or not resource_id or not resource_label:
        return
    workspace_id = _as_str(p.get("workspace_id") or m.get("workspace_id"))
    project_id = _as_str(p.get("project_id") or m.get("project_id"))
    if project_id and not _chat_graph_enabled_for_project(project_id):
        return

    _merge_node(
        "ChatSession",
        session_id,
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "last_commit_position": commit_position,
        },
    )
    _merge_node(
        "ChatMessage",
        message_id,
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "session_id": session_id,
            "last_commit_position": commit_position,
        },
    )
    _merge_node(
        resource_label,
        resource_id,
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
        },
    )

    relation_type = _chat_relation_type(p.get("relation"))
    run_graph_query(
        f"""
        MATCH (m:ChatMessage {{id:$message_id}})
        MATCH (r:{resource_label} {{id:$resource_id}})
        MERGE (m)-[:{relation_type}]->(r)
        """,
        {
            "message_id": message_id,
            "resource_id": resource_id,
        },
        write=True,
    )
    run_graph_query(
        f"""
        MATCH (s:ChatSession {{id:$session_id}})
        MATCH (r:{resource_label} {{id:$resource_id}})
        MERGE (r)-[:DISCUSSED_IN]->(s)
        MERGE (s)-[:REFERENCES_RESOURCE]->(r)
        """,
        {
            "session_id": session_id,
            "resource_id": resource_id,
        },
        write=True,
    )


def _project_graph_event(ev: EventEnvelope, commit_position: int) -> None:
    metadata = ev.metadata or {}
    actor_id = _as_str(metadata.get("actor_id"))
    if actor_id:
        _merge_node("User", actor_id, {})

    if ev.event_type in {PROJECT_EVENT_CREATED, PROJECT_EVENT_UPDATED, PROJECT_EVENT_DELETED}:
        _project_project_event(ev, commit_position)
        payload = ev.payload or {}
        if ev.event_type == PROJECT_EVENT_DELETED:
            sync_project_chat_graph_for_policy(ev.aggregate_id, force_purge=True)
            return
        if ev.event_type == PROJECT_EVENT_CREATED:
            mode = normalize_chat_index_mode(str(payload.get("chat_index_mode") or "OFF"))
            if mode == CHAT_INDEX_MODE_KG_AND_VECTOR:
                sync_project_chat_graph_for_policy(ev.aggregate_id)
            return
        if "chat_index_mode" in payload:
            sync_project_chat_graph_for_policy(ev.aggregate_id)
        return

    if ev.event_type in {
        TASK_EVENT_CREATED,
        TASK_EVENT_UPDATED,
        TASK_EVENT_REORDERED,
        TASK_EVENT_COMPLETED,
        TASK_EVENT_REOPENED,
        TASK_EVENT_ARCHIVED,
        TASK_EVENT_RESTORED,
        TASK_EVENT_DELETED,
        TASK_EVENT_MOVED_TO_INBOX,
        TASK_EVENT_AUTOMATION_REQUESTED,
        TASK_EVENT_AUTOMATION_STARTED,
        TASK_EVENT_AUTOMATION_COMPLETED,
        TASK_EVENT_AUTOMATION_FAILED,
        TASK_EVENT_SCHEDULE_CONFIGURED,
        TASK_EVENT_SCHEDULE_QUEUED,
        TASK_EVENT_SCHEDULE_STARTED,
        TASK_EVENT_SCHEDULE_COMPLETED,
        TASK_EVENT_SCHEDULE_FAILED,
        TASK_EVENT_SCHEDULE_DISABLED,
        TASK_EVENT_WATCH_TOGGLED,
        TASK_EVENT_COMMENT_ADDED,
    }:
        _project_task_event(ev, commit_position)
        return

    if ev.event_type in {
        NOTE_EVENT_CREATED,
        NOTE_EVENT_UPDATED,
        NOTE_EVENT_ARCHIVED,
        NOTE_EVENT_RESTORED,
        NOTE_EVENT_PINNED,
        NOTE_EVENT_UNPINNED,
        NOTE_EVENT_DELETED,
    }:
        _project_note_event(ev, commit_position)
        return

    if ev.event_type in {
        SPECIFICATION_EVENT_CREATED,
        SPECIFICATION_EVENT_UPDATED,
        SPECIFICATION_EVENT_ARCHIVED,
        SPECIFICATION_EVENT_RESTORED,
        SPECIFICATION_EVENT_DELETED,
    }:
        _project_specification_event(ev, commit_position)
        return

    if ev.event_type in {
        PROJECT_RULE_EVENT_CREATED,
        PROJECT_RULE_EVENT_UPDATED,
        PROJECT_RULE_EVENT_DELETED,
    }:
        _project_project_rule_event(ev, commit_position)
        return

    if ev.event_type in {
        CHAT_SESSION_EVENT_STARTED,
        CHAT_SESSION_EVENT_RENAMED,
        CHAT_SESSION_EVENT_ARCHIVED,
        CHAT_SESSION_EVENT_CONTEXT_UPDATED,
    }:
        _project_chat_session_event(ev, commit_position)
        return

    if ev.event_type in {
        CHAT_SESSION_EVENT_USER_MESSAGE_APPENDED,
        CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_APPENDED,
        CHAT_SESSION_EVENT_ASSISTANT_MESSAGE_UPDATED,
        CHAT_SESSION_EVENT_MESSAGE_DELETED,
    }:
        _project_chat_message_event(ev, commit_position)
        return

    if ev.event_type == CHAT_SESSION_EVENT_ATTACHMENT_LINKED:
        _project_chat_attachment_event(ev, commit_position)
        return

    if ev.event_type == CHAT_SESSION_EVENT_RESOURCE_LINKED:
        _project_chat_resource_link_event(ev, commit_position)


def project_kurrent_graph_once(limit: int | None = None) -> int:
    if not graph_enabled():
        return 0
    client = get_kurrent_client()
    if client is None:
        return 0

    try:
        ensure_graph_schema()
    except Exception as exc:
        incr("graph_projection_failures")
        logger.warning("Knowledge graph projection skipped (schema unavailable): %s", exc)
        return 0

    batch_limit = max(1, int(limit or GRAPH_PROJECTION_BATCH_SIZE))
    try:
        from .models import SessionLocal

        with SessionLocal() as db:
            checkpoint = _get_graph_checkpoint(db)
            start_position = checkpoint.commit_position if checkpoint.commit_position > 0 else None
            rows = client.read_all(commit_position=start_position, limit=batch_limit)

            processed = 0
            for event in rows:
                packed = _recorded_to_envelope(event)
                if packed is None:
                    continue
                commit_position, env = packed
                if commit_position <= checkpoint.commit_position:
                    continue
                _project_graph_event(env, commit_position)
                checkpoint.commit_position = commit_position
                db.commit()
                processed += 1
    except Exception as exc:
        incr("graph_projection_failures")
        logger.warning("Knowledge graph catch-up failed: %s", exc)
        return 0

    if processed:
        incr("graph_projection_events_processed", processed)
    set_value("graph_projection_lag_commits", 0)
    return processed


def _graph_worker_loop() -> None:
    client = get_kurrent_client()
    if client is None:
        return

    while not _graph_stop_event.is_set():
        subscription = None
        try:
            ensure_graph_schema()
            subscription = client.read_subscription_to_all(
                group_name=PERSISTENT_SUBSCRIPTION_GRAPH_GROUP,
                event_buffer_size=max(1, int(PERSISTENT_SUBSCRIPTION_EVENT_BUFFER_SIZE)),
                max_ack_batch_size=max(1, int(PERSISTENT_SUBSCRIPTION_MAX_ACK_BATCH_SIZE)),
                max_ack_delay=max(0.0, float(PERSISTENT_SUBSCRIPTION_MAX_ACK_DELAY_SECONDS)),
                stopping_grace=max(0.0, float(PERSISTENT_SUBSCRIPTION_STOPPING_GRACE_SECONDS)),
            )
            _set_graph_subscription(subscription)
            for event in subscription:
                if _graph_stop_event.is_set():
                    break
                packed = _recorded_to_envelope(event)
                if packed is None:
                    subscription.ack(event)
                    continue
                commit_position, env = packed
                try:
                    _project_graph_event(env, commit_position)
                    incr("graph_projection_events_processed", 1)
                    set_value("graph_projection_lag_commits", 0)
                    subscription.ack(event)
                except Exception as exc:
                    incr("graph_projection_failures")
                    logger.warning("Knowledge graph projection event failed, retrying event: %s", exc)
                    subscription.nack(event, "retry")
        except Exception as exc:
            incr("graph_projection_failures")
            logger.warning("Knowledge graph projection worker retrying after error: %s", exc)
            _graph_stop_event.wait(max(0.2, float(PERSISTENT_SUBSCRIPTION_RETRY_BACKOFF_SECONDS)))
        finally:
            _set_graph_subscription(None)
            if subscription is not None:
                try:
                    subscription.stop()
                except Exception:
                    pass


def _set_graph_subscription(subscription: Any | None) -> None:
    global _graph_subscription
    with _graph_subscription_lock:
        _graph_subscription = subscription


def _stop_graph_subscription() -> None:
    with _graph_subscription_lock:
        subscription = _graph_subscription
    if subscription is None:
        return
    try:
        subscription.stop()
    except Exception:
        pass


def start_graph_projection_worker() -> None:
    global _graph_thread
    if not graph_enabled():
        return
    if get_kurrent_client() is None:
        return
    if _graph_thread and _graph_thread.is_alive():
        return
    _graph_stop_event.clear()
    _graph_thread = threading.Thread(target=_graph_worker_loop, name="kurrent-graph-projection-worker", daemon=True)
    _graph_thread.start()


def stop_graph_projection_worker() -> None:
    global _graph_thread
    _graph_stop_event.set()
    _stop_graph_subscription()
    if _graph_thread and _graph_thread.is_alive():
        _graph_thread.join(timeout=3)
    _graph_thread = None
