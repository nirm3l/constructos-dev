from __future__ import annotations

import json
import threading
from typing import Any

from features.notes.domain import (
    EVENT_ARCHIVED as NOTE_EVENT_ARCHIVED,
    EVENT_CREATED as NOTE_EVENT_CREATED,
    EVENT_DELETED as NOTE_EVENT_DELETED,
    EVENT_PINNED as NOTE_EVENT_PINNED,
    EVENT_RESTORED as NOTE_EVENT_RESTORED,
    EVENT_UNPINNED as NOTE_EVENT_UNPINNED,
    EVENT_UPDATED as NOTE_EVENT_UPDATED,
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
from .knowledge_graph import ensure_graph_schema, graph_enabled, run_graph_query
from .observability import incr, set_value
from .settings import (
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
        "labels",
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


def _project_graph_event(ev: EventEnvelope, commit_position: int) -> None:
    metadata = ev.metadata or {}
    actor_id = _as_str(metadata.get("actor_id"))
    if actor_id:
        _merge_node("User", actor_id, {})

    if ev.event_type in {PROJECT_EVENT_CREATED, PROJECT_EVENT_UPDATED, PROJECT_EVENT_DELETED}:
        _project_project_event(ev, commit_position)
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
