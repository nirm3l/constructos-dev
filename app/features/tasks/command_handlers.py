from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from plugins import task_policy as plugin_task_policy
from plugins.registry import list_workflow_plugins
from plugins.team_mode.task_roles import (
    derive_task_role,
    ensure_team_mode_labels,
    normalize_team_agents,
)
from plugins.team_mode.state_machine import evaluate_team_mode_transition
from plugins.team_mode.gates import evaluate_team_mode_gates
from plugins.team_mode.semantics import REQUIRED_SEMANTIC_STATUSES, normalize_review_policy, normalize_status_semantics, semantic_status_key
from shared.core import (
    AggregateEventRepository,
    BulkAction,
    CommentCreate,
    DEFAULT_STATUSES,
    Project,
    ProjectCommandState,
    ProjectMember,
    ProjectPluginConfig,
    Specification,
    ReorderPayload,
    Task,
    TaskComment,
    TaskGroup,
    TaskCreate,
    TaskPatch,
    TaskWatcher,
    User,
    allocate_id,
    coerce_originator_id,
    ensure_project_access,
    ensure_role,
    get_kurrent_client,
    get_user_zoneinfo,
    load_project_command_state,
    load_specification_command_state,
    load_task_command_state,
    load_task_group_command_state,
    load_task_view,
    normalize_datetime_to_utc,
    rebuild_state,
    to_iso_utc,
)
from shared.delivery_evidence import has_merge_to_main_ref
from shared.settings import AGENT_SYSTEM_USER_ID, CLAUDE_SYSTEM_USER_ID, CODEX_SYSTEM_USER_ID
from shared.team_mode_lifecycle import review_resolution_transition
from shared.task_automation import (
    TRIGGER_KIND_SCHEDULE,
    TRIGGER_KIND_STATUS_CHANGE,
    STATUS_MATCH_ALL,
    STATUS_MATCH_ANY,
    STATUS_SCOPE_EXTERNAL,
    STATUS_SCOPE_SELF,
    build_legacy_schedule_trigger,
    derive_legacy_schedule_fields,
    first_enabled_schedule_trigger,
    has_enabled_schedule_trigger,
    normalize_execution_triggers,
)
from shared.task_delivery import (
    DELIVERY_MODE_DEPLOYABLE_SLICE,
    normalize_delivery_mode,
    task_matches_dependency_requirement,
)
from shared.task_relationships import normalize_task_relationships
from shared.project_repository import resolve_project_repository_path
from features.notifications.domain import NotificationAggregate
from features.agents.intent_classifier import (
    AUTOMATION_REQUEST_INTENT_FIELDS,
    classify_instruction_intent,
    is_team_mode_kickoff_classification,
    resolve_instruction_intent,
)
from features.agents.provider_auth import resolve_provider_effective_auth_source
from .domain import TaskAggregate

MENTION_PATTERN = re.compile(r"@([A-Za-z0-9_\-]+)")
_UNSET = object()
_LOG = logging.getLogger(__name__)
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _slugify(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or fallback


def _run_git(*, cwd: Path, args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode, str(proc.stdout or "").strip(), str(proc.stderr or "").strip()


def _cleanup_task_worktree(*, project_name: str, task_id: str) -> bool:
    repo_root = resolve_project_repository_path(
        project_name=project_name,
        project_id=None,
    )
    task_short = _slugify(task_id[:8], fallback="task")
    task_worktree = repo_root / ".constructos" / "worktrees" / task_short
    if not task_worktree.exists():
        return False
    if repo_root.exists():
        code, _out, _err = _run_git(cwd=repo_root, args=["worktree", "remove", "--force", str(task_worktree)])
        if code == 0:
            _run_git(cwd=repo_root, args=["worktree", "prune"])
            return True
    shutil.rmtree(task_worktree, ignore_errors=True)
    return True


def _maybe_cleanup_plugin_worktree(
    *,
    db: Session,
    task_id: str,
    project_id: str | None,
    assignee_id: str | None,
    status: str,
) -> None:
    normalized_project_id = str(project_id or "").strip()
    normalized_assignee_id = str(assignee_id or "").strip()
    normalized_status = str(status or "").strip()
    if not normalized_project_id or not normalized_assignee_id:
        return
    enabled_plugin_keys = [
        str(getattr(plugin, "key", "")).strip().lower()
        for plugin in list_workflow_plugins()
        if str(getattr(plugin, "key", "")).strip()
    ]
    if not enabled_plugin_keys:
        return
    has_enabled_workflow_plugin = db.execute(
        select(ProjectPluginConfig.id).where(
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key.in_(enabled_plugin_keys),
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).first()
    if not has_enabled_workflow_plugin:
        return
    task_row = db.execute(
        select(Task.status, Task.labels).where(
            Task.id == task_id,
            Task.project_id == normalized_project_id,
            Task.assignee_id == normalized_assignee_id,
            Task.is_deleted == False,  # noqa: E712
        )
    ).first()
    member_role = ""
    if task_row is not None:
        task_status, task_labels = task_row
        member_role = derive_task_role(
            task_like={
                "assignee_id": normalized_assignee_id,
                "labels": task_labels,
                "status": str(task_status or normalized_status),
            },
            member_role_by_user_id={},
        )
    if not member_role:
        member_role = str(
            db.execute(
                select(ProjectMember.role).where(
                    ProjectMember.project_id == normalized_project_id,
                    ProjectMember.user_id == normalized_assignee_id,
                )
            ).scalar_one_or_none()
            or ""
        ).strip()
    if not plugin_task_policy.should_cleanup_task_worktree(
        plugin_enabled=True,
        task_status=normalized_status,
        assignee_role=member_role,
    ):
        return
    project_name = db.execute(
        select(Project.name).where(Project.id == normalized_project_id, Project.is_deleted == False)
    ).scalar_one_or_none()
    normalized_project_name = str(project_name or "").strip()
    if not normalized_project_name:
        return
    try:
        _cleanup_task_worktree(project_name=normalized_project_name, task_id=task_id)
    except Exception as exc:
        _LOG.warning("Failed to cleanup task worktree for task %s: %s", task_id, exc)


def _normalize_tags(values: list[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        tag = str(raw).strip().lower()
        if tag.startswith("delivery_mode:"):
            continue
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _load_team_mode_agents_for_project(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
) -> list[dict[str, str]]:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return []
    config_row = db.execute(
        select(ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if not config_row:
        return []
    try:
        config_obj = json.loads(str(config_row or "").strip() or "{}")
    except Exception:
        return []
    if not isinstance(config_obj, dict):
        return []
    return normalize_team_agents(config_obj.get("team"))


def _load_team_mode_status_semantics_for_project(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
) -> dict[str, str] | None:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return None
    config_row = db.execute(
        select(ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if not config_row:
        return None
    try:
        config_obj = json.loads(str(config_row or "").strip() or "{}")
    except Exception:
        return dict(REQUIRED_SEMANTIC_STATUSES)
    if not isinstance(config_obj, dict):
        return dict(REQUIRED_SEMANTIC_STATUSES)
    return normalize_status_semantics(config_obj.get("status_semantics"))


def _effective_completed_status_for_project(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
) -> str:
    semantics = _load_team_mode_status_semantics_for_project(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    if isinstance(semantics, dict):
        return str(semantics.get("completed") or "").strip() or REQUIRED_SEMANTIC_STATUSES["completed"]
    return "Done"


def _is_completed_status(status: str | None, *, completed_status: str | None) -> bool:
    normalized = str(status or "").strip()
    if not normalized:
        return False
    if normalized.casefold() == "done":
        return True
    if str(completed_status or "").strip() and normalized.casefold() == str(completed_status or "").strip().casefold():
        return True
    return semantic_status_key(status=normalized) == "completed"


def _normalize_assigned_agent_code_for_project(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    assigned_agent_code: str | None,
) -> str | None:
    normalized_code = str(assigned_agent_code or "").strip()
    if not normalized_code:
        return None
    agents = _load_team_mode_agents_for_project(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    if not agents:
        raise HTTPException(status_code=422, detail="assigned_agent_code requires Team Mode plugin enabled with configured agents")
    valid_codes = {str(item.get("id") or "").strip() for item in agents if str(item.get("id") or "").strip()}
    if normalized_code not in valid_codes:
        raise HTTPException(status_code=422, detail=f"assigned_agent_code '{normalized_code}' is not defined in Team Mode config")
    return normalized_code


def _apply_team_mode_agent_labels(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    task_id: str | None,
    assignee_id: str | None,
    assigned_agent_code: str | None,
    status: str | None,
    labels: list[str] | None,
) -> tuple[list[str], str | None]:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return list(labels or []), None
    agents = _load_team_mode_agents_for_project(
        db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    if not agents:
        return ensure_team_mode_labels(labels=list(labels or []), role=None, agent_slot=None), None
    normalized_assignee_id = str(assignee_id or "").strip()
    normalized_assigned_agent_code = str(assigned_agent_code or "").strip()
    if not normalized_assigned_agent_code:
        return ensure_team_mode_labels(labels=list(labels or []), role=None, agent_slot=None), None
    matching_agent = next(
        (
            agent
            for agent in agents
            if str(agent.get("id") or "").strip() == normalized_assigned_agent_code
        ),
        None,
    )
    selected_slot = normalized_assigned_agent_code if matching_agent is not None else None
    selected_role = str(matching_agent.get("authority_role") or "").strip() or None if matching_agent is not None else None
    return (
        ensure_team_mode_labels(
            labels=list(labels or []),
            role=selected_role if (selected_slot or normalized_assignee_id) else None,
            agent_slot=selected_slot,
        ),
        selected_slot,
    )


def _team_mode_enabled_for_project(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return False
    return (
        db.execute(
            select(ProjectPluginConfig.id).where(
                ProjectPluginConfig.workspace_id == str(workspace_id),
                ProjectPluginConfig.project_id == normalized_project_id,
                ProjectPluginConfig.plugin_key == "team_mode",
                ProjectPluginConfig.enabled == True,  # noqa: E712
                ProjectPluginConfig.is_deleted == False,  # noqa: E712
            )
        ).scalar_one_or_none()
        is not None
    )


def _should_default_new_task_to_team_mode_developer(
    *,
    specification_id: str | None,
    task_type: str | None,
    execution_triggers: list[dict[str, object]] | None,
    initial_status: str | None,
) -> bool:
    if not str(specification_id or "").strip():
        return False
    normalized_task_type = str(task_type or "").strip().lower()
    if normalized_task_type == "scheduled_instruction":
        return False
    if has_enabled_schedule_trigger(execution_triggers):
        return False
    semantic = semantic_status_key(status=initial_status)
    if semantic in {"in_review", "awaiting_decision", "completed"}:
        return False
    return True


def _backfill_team_mode_structural_dependencies(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    specification_id: str | None,
    actor_user_id: str,
) -> None:
    normalized_specification_id = str(specification_id or "").strip()
    if not normalized_specification_id:
        return
    if not _team_mode_enabled_for_project(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
    ):
        return
    team_agents = _load_team_mode_agents_for_project(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    agent_role_by_code = {
        str(agent.get("id") or "").strip(): str(agent.get("authority_role") or "").strip()
        for agent in team_agents
        if str(agent.get("id") or "").strip()
    }
    task_rows = db.execute(
        select(
            Task.id,
            Task.title,
            Task.status,
            Task.priority,
            Task.assignee_id,
            Task.assigned_agent_code,
            Task.labels,
            Task.task_relationships,
        ).where(
            Task.workspace_id == str(workspace_id),
            Task.project_id == str(project_id),
            Task.specification_id == normalized_specification_id,
            Task.is_deleted == False,  # noqa: E712
        )
        .order_by(Task.created_at.asc(), Task.id.asc())
    ).all()
    developer_tasks: list[dict[str, object]] = []
    for task_id, title, status, priority, assignee_id, assigned_agent_code, labels, task_relationships in task_rows:
        task_like = {
            "id": str(task_id or "").strip(),
            "title": str(title or "").strip(),
            "status": str(status or "").strip(),
            "priority": str(priority or "").strip(),
            "assignee_id": str(assignee_id or "").strip(),
            "assigned_agent_code": str(assigned_agent_code or "").strip(),
            "labels": labels,
            "task_relationships": normalize_task_relationships(task_relationships),
        }
        if derive_task_role(
            task_like=task_like,
            member_role_by_user_id={},
            agent_role_by_code=agent_role_by_code,
            allow_status_fallback=False,
        ) != "Developer":
            continue
        developer_tasks.append(task_like)
    if len(developer_tasks) < 2:
        return

    def _priority_rank(value: object) -> int:
        normalized = str(value or "").strip().casefold()
        if normalized == "high":
            return 0
        if normalized in {"med", "medium"}:
            return 1
        if normalized == "low":
            return 2
        return 3

    developer_tasks.sort(
        key=lambda task: (
            _priority_rank(task.get("priority")),
            str(task.get("id") or "").strip(),
        )
    )
    repo = AggregateEventRepository(db)
    for task in developer_tasks:
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            continue
        existing_relationships = normalize_task_relationships(task.get("task_relationships"))
        if existing_relationships:
            continue
        task_rank = _priority_rank(task.get("priority"))
        dependency_ids = [
            str(candidate.get("id") or "").strip()
            for candidate in developer_tasks
            if str(candidate.get("id") or "").strip()
            and str(candidate.get("id") or "").strip() != task_id
            and _priority_rank(candidate.get("priority")) < task_rank
        ]
        if not dependency_ids:
            continue
        aggregate = _load_task_aggregate(repo, task_id)
        aggregate.update(
            changes={
                "task_relationships": [
                    {
                        "kind": "depends_on",
                        "task_ids": dependency_ids,
                        "match_mode": "all",
                        "statuses": ["merged"],
                    }
                ]
            }
        )
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=actor_user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=task_id,
        )


def _normalize_external_refs(values: list[dict] | None) -> list[dict]:
    if not values:
        return []
    out: list[dict] = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "").strip()
        if not url:
            continue
        item = {"url": url}
        title = str(raw.get("title") or "").strip()
        source = str(raw.get("source") or "").strip()
        if title:
            item["title"] = title
        if source:
            item["source"] = source
        out.append(item)
    return out


def _team_mode_project_is_unstarted(
    db: Session,
    *,
    project_id: str,
    exclude_task_id: str,
) -> bool:
    task_ids = [
        str(item or "").strip()
        for item in db.execute(
            select(Task.id).where(
                Task.project_id == project_id,
                Task.is_deleted == False,  # noqa: E712
            )
        ).scalars().all()
        if str(item or "").strip()
    ]
    for task_id in task_ids:
        if task_id == exclude_task_id:
            continue
        state, _ = rebuild_state(db, "Task", task_id)
        if str(state.get("last_requested_source") or "").strip():
            return False
        if str(state.get("last_lead_handoff_token") or "").strip():
            return False
        if isinstance(state.get("last_deploy_execution"), dict) and state.get("last_deploy_execution"):
            return False
        refs = state.get("external_refs")
        if isinstance(refs, list) and any(isinstance(item, dict) and str(item.get("url") or "").strip() for item in refs):
            return False
    return True


def _verify_team_mode_project_topology(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
) -> dict[str, object] | None:
    plugin_row = db.execute(
        select(ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == str(workspace_id),
            ProjectPluginConfig.project_id == str(project_id),
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).first()
    if plugin_row is None:
        return None

    config_obj: dict[str, object] = {}
    try:
        parsed_cfg = json.loads(str(plugin_row[0] or "").strip() or "{}")
        if isinstance(parsed_cfg, dict):
            config_obj = parsed_cfg
    except Exception:
        config_obj = {}

    member_role_by_user_id = {
        str(user_id): str(role or "").strip()
        for user_id, role in db.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(
                ProjectMember.project_id == str(project_id),
            )
        ).all()
    }
    task_rows = db.execute(
        select(
            Task.id,
            Task.assignee_id,
            Task.assigned_agent_code,
            Task.labels,
            Task.status,
            Task.execution_triggers,
            Task.task_relationships,
            Task.external_refs,
        ).where(
            Task.project_id == str(project_id),
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        )
    ).all()
    tasks = [
        {
            "id": str(task_id or "").strip(),
            "assignee_id": str(assignee_id or "").strip() or None,
            "assigned_agent_code": str(assigned_agent_code or "").strip() or None,
            "labels": labels,
            "status": str(status or "").strip(),
            "execution_triggers": execution_triggers,
            "task_relationships": task_relationships,
            "external_refs": external_refs,
        }
        for task_id, assignee_id, assigned_agent_code, labels, status, execution_triggers, task_relationships, external_refs in task_rows
    ]
    project_row = db.get(Project, str(project_id))
    return evaluate_team_mode_gates(
        project_id=str(project_id),
        workspace_id=str(workspace_id),
        event_storming_enabled=bool(getattr(project_row, "event_storming_enabled", False)),
        expected_event_storming_enabled=None,
        plugin_policy=config_obj,
        plugin_policy_source="project_plugin_config",
        tasks=tasks,
        member_role_by_user_id=member_role_by_user_id,
        notes_by_task={},
        comments_by_task={},
        extract_deploy_ports=lambda _value: set(),
        has_deploy_stack_marker=lambda _value: False,
    )


def _normalize_attachment_refs(values: list[dict] | None) -> list[dict]:
    if not values:
        return []
    out: list[dict] = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        path = str(raw.get("path") or "").strip()
        if not path:
            continue
        item = {"path": path}
        name = str(raw.get("name") or "").strip()
        mime_type = str(raw.get("mime_type") or "").strip()
        size_bytes = raw.get("size_bytes")
        if name:
            item["name"] = name
        if mime_type:
            item["mime_type"] = mime_type
        if isinstance(size_bytes, int) and size_bytes >= 0:
            item["size_bytes"] = size_bytes
        out.append(item)
    return out


def _normalize_task_title(value: str) -> str:
    return " ".join(str(value or "").split())


def _validate_assignee_id(db: Session, assignee_id: str | None, *, project_id: str | None = None) -> str | None:
    normalized = str(assignee_id or "").strip() or None
    if not normalized:
        return None
    if not _UUID_PATTERN.match(normalized):
        normalized_project_id = str(project_id or "").strip()
        if not normalized_project_id:
            raise HTTPException(
                status_code=422,
                detail="assignee_id must be a user_id UUID (not username/full name)",
            )
        normalized_casefold = normalized.casefold()
        candidate_keys: set[str] = {normalized_casefold}
        if not normalized_casefold.startswith("agent.") and "." not in normalized_casefold:
            candidate_keys.add(f"agent.{normalized_casefold}")
        members = db.execute(
            select(ProjectMember.user_id, User.username, User.full_name)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == normalized_project_id)
        ).all()
        matches: list[str] = []
        for member_user_id, username, full_name in members:
            username_key = str(username or "").strip().casefold()
            full_name_key = str(full_name or "").strip().casefold()
            if username_key in candidate_keys or full_name_key in candidate_keys:
                matches.append(str(member_user_id))
        unique_matches = sorted(set(matches))
        if len(unique_matches) == 1:
            return unique_matches[0]
        if len(unique_matches) > 1:
            raise HTTPException(
                status_code=422,
                detail="assignee_id is ambiguous within this project; provide member user_id UUID",
            )
        raise HTTPException(
            status_code=422,
            detail="assignee_id must be a project-member user_id UUID or resolvable member username/full name",
        )
    assignee = db.get(User, normalized)
    if assignee is None:
        raise HTTPException(status_code=422, detail="assignee_id does not reference an existing user")
    return normalized


def _resolve_available_system_bot_assignee_for_project(
    db: Session,
    *,
    project_id: str | None,
    requested_assignee_id: str | None,
    assigned_agent_code: str | None,
) -> str | None:
    normalized_project_id = str(project_id or "").strip()
    normalized_requested_assignee_id = str(requested_assignee_id or "").strip()
    normalized_assigned_agent_code = str(assigned_agent_code or "").strip()
    if not normalized_project_id or not normalized_assigned_agent_code:
        return normalized_requested_assignee_id or None

    requested_provider: str | None = None
    if normalized_requested_assignee_id and normalized_requested_assignee_id not in {CODEX_SYSTEM_USER_ID, CLAUDE_SYSTEM_USER_ID}:
        requested_user = db.get(User, normalized_requested_assignee_id)
        if requested_user is not None and str(requested_user.user_type or "").strip().lower() == "agent":
            return normalized_requested_assignee_id
        normalized_requested_assignee_id = ""
    elif normalized_requested_assignee_id == CODEX_SYSTEM_USER_ID:
        requested_provider = "codex"
    elif normalized_requested_assignee_id == CLAUDE_SYSTEM_USER_ID:
        requested_provider = "claude"

    if requested_provider and resolve_provider_effective_auth_source(requested_provider) != "none":
        return normalized_requested_assignee_id or None

    project_bot_rows = db.execute(
        select(ProjectMember.user_id, User.username)
        .join(User, User.id == ProjectMember.user_id)
        .where(
            ProjectMember.project_id == normalized_project_id,
            User.is_active == True,  # noqa: E712
            User.user_type == "agent",
            User.id.in_([CODEX_SYSTEM_USER_ID, CLAUDE_SYSTEM_USER_ID]),
        )
        .order_by(ProjectMember.id.asc())
    ).all()
    available_project_bot_ids_by_provider: dict[str, str] = {}
    for user_id, username in project_bot_rows:
        normalized_user_id = str(user_id or "").strip()
        normalized_username = str(username or "").strip().lower()
        if not normalized_user_id:
            continue
        if normalized_user_id == CODEX_SYSTEM_USER_ID or normalized_username == "codex-bot":
            available_project_bot_ids_by_provider["codex"] = normalized_user_id
        elif normalized_user_id == CLAUDE_SYSTEM_USER_ID or normalized_username == "claude-bot":
            available_project_bot_ids_by_provider["claude"] = normalized_user_id

    preferred_fallback_providers = ("claude", "codex") if requested_provider == "codex" else ("codex", "claude")
    for provider in preferred_fallback_providers:
        if resolve_provider_effective_auth_source(provider) == "none":
            continue
        fallback_user_id = str(available_project_bot_ids_by_provider.get(provider) or "").strip()
        if fallback_user_id:
            return fallback_user_id
    if normalized_requested_assignee_id:
        return normalized_requested_assignee_id

    for provider in ("codex", "claude"):
        if resolve_provider_effective_auth_source(provider) == "none":
            continue
        fallback_user_id = str(available_project_bot_ids_by_provider.get(provider) or "").strip()
        if fallback_user_id:
            return fallback_user_id
        if provider == "codex":
            return CODEX_SYSTEM_USER_ID
        if provider == "claude":
            return CLAUDE_SYSTEM_USER_ID
    return None


def _normalize_team_mode_routed_assignee(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    assignee_id: str | None,
    assigned_agent_code: str | None,
) -> str | None:
    normalized_project_id = str(project_id or "").strip()
    normalized_assignee_id = str(assignee_id or "").strip()
    normalized_assigned_agent_code = str(assigned_agent_code or "").strip()
    if not workspace_id or not normalized_project_id or not normalized_assigned_agent_code:
        return normalized_assignee_id or None
    if not normalized_assignee_id:
        return None

    team_agents = _load_team_mode_agents_for_project(
        db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    matching_agent = next(
        (
            agent
            for agent in team_agents
            if str(agent.get("id") or "").strip() == normalized_assigned_agent_code
        ),
        None,
    )
    if matching_agent is not None:
        executor_user_id = str(matching_agent.get("executor_user_id") or "").strip()
        if executor_user_id and executor_user_id == normalized_assignee_id:
            return normalized_assignee_id

    assignee = db.get(User, normalized_assignee_id)
    if assignee is None:
        return normalized_assignee_id
    if str(assignee.user_type or "").strip().lower() == "agent":
        return normalized_assignee_id
    return None


def _task_title_key(value: str) -> str:
    return _normalize_task_title(value).casefold()


def _task_aggregate_id(project_id: str, title: str) -> str:
    key = _task_title_key(title)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"task:{project_id}:{key}"))


def _extract_unique_mentioned_usernames(body: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for username in MENTION_PATTERN.findall(body or ""):
        normalized = username.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(username)
    return out


def _emit_mention_notifications(
    db: Session,
    *,
    actor: User,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    body: str,
) -> None:
    usernames = _extract_unique_mentioned_usernames(body)
    if not usernames:
        return

    mentioned_users = db.execute(select(User).where(User.username.in_(usernames))).scalars().all()
    by_username = {str(user.username or "").casefold(): user for user in mentioned_users}
    actor_username = str(actor.username or "Someone")
    repo = AggregateEventRepository(db)
    for username in usernames:
        target = by_username.get(username.casefold())
        if target is None:
            continue
        if not bool(getattr(target, "notifications_enabled", True)):
            continue
        notification_id = allocate_id(db)
        aggregate = NotificationAggregate(
            id=coerce_originator_id(notification_id),
            user_id=target.id,
            message=f"{actor_username} mentioned you on task #{task_id}",
        )
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": actor.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": task_id,
            },
            expected_version=0,
        )


def _require_project_scope(db: Session, *, workspace_id: str, project_id: str) -> ProjectCommandState:
    project = load_project_command_state(db, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Project does not belong to workspace")
    return project


def _require_specification_scope(db: Session, *, workspace_id: str, project_id: str, specification_id: str) -> Specification:
    specification = load_specification_command_state(db, specification_id)
    if not specification or specification.is_deleted:
        raise HTTPException(status_code=404, detail="Specification not found")
    if specification.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Specification does not belong to workspace")
    if specification.project_id != project_id:
        raise HTTPException(status_code=400, detail="Specification does not belong to project")
    if specification.archived:
        raise HTTPException(status_code=409, detail="Specification is archived")
    return specification


def _enforce_team_mode_transition_policy(
    *,
    db: Session,
    workspace_id: str,
    project_id: str | None,
    actor_user_id: str,
    from_status: str,
    to_status: str,
    task_id: str | None = None,
) -> None:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return
    row = db.execute(
        select(ProjectPluginConfig).where(
            ProjectPluginConfig.workspace_id == str(workspace_id),
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if row is None:
        return
    try:
        config = json.loads(str(row.config_json or "").strip() or "{}")
    except Exception:
        config = {}
    if not isinstance(config, dict):
        config = {}
    status_semantics = config.get("status_semantics")
    if not isinstance(status_semantics, dict):
        status_semantics = dict(REQUIRED_SEMANTIC_STATUSES)
    member_role_by_user_id = {
        str(user_id): str(role or "").strip()
        for user_id, role in db.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(
                ProjectMember.project_id == normalized_project_id,
            )
        ).all()
    }
    actor_role = member_role_by_user_id.get(str(actor_user_id), "")
    normalized_actor_role = str(actor_role or "").strip()
    if task_id:
        team_agents = normalize_team_agents(config.get("team"))
        agent_role_by_code = {
            str(agent.get("id") or "").strip(): str(agent.get("authority_role") or "").strip()
            for agent in team_agents
            if str(agent.get("id") or "").strip()
        }
        task_row = db.execute(
            select(Task.assignee_id, Task.assigned_agent_code, Task.status, Task.labels).where(
                Task.id == str(task_id),
                Task.project_id == normalized_project_id,
                Task.is_deleted == False,  # noqa: E712
            )
        ).first()
        if task_row is not None:
            assignee_id, assigned_agent_code, task_status, task_labels = task_row
            task_workflow_role = derive_task_role(
                task_like={
                    "assignee_id": str(assignee_id or "").strip(),
                    "assigned_agent_code": str(assigned_agent_code or "").strip(),
                    "labels": task_labels,
                    "status": str(task_status or "").strip(),
                },
                member_role_by_user_id=member_role_by_user_id,
                agent_role_by_code=agent_role_by_code,
            )
            if task_workflow_role in {"Developer", "Lead", "QA"}:
                # Team Mode workflow transitions are governed by task role, not human project membership role.
                normalized_actor_role = task_workflow_role
            if (
                task_workflow_role == "Lead"
                and str(from_status or "").strip() == "Lead"
                and str(to_status or "").strip() == "QA"
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Team Mode transition policy denied status change. "
                        "Lead must hand off to QA via automation request; "
                        "do not change the Lead task status to QA."
                    ),
                )
    allowed, reason_code = evaluate_team_mode_transition(
        status_semantics=status_semantics,
        from_status=str(from_status or "").strip(),
        to_status=str(to_status or "").strip(),
        actor_role=normalized_actor_role or None,
    )
    if allowed:
        return
    raise HTTPException(
        status_code=409,
        detail=(
            "Team Mode transition policy denied status change. "
            f"reason_code={reason_code}; "
            f"from={str(from_status or '').strip()}; "
            f"to={str(to_status or '').strip()}; "
            f"actor_role={normalized_actor_role or 'unknown'}"
        ),
    )


def _load_enabled_team_mode_config(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
) -> dict[str, Any] | None:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return None
    row = db.execute(
        select(ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == str(workspace_id),
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    try:
        parsed = json.loads(str(row or "").strip() or "{}")
    except Exception:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _resolve_team_mode_human_owner_user_id(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    team_mode_config: dict[str, Any] | None = None,
) -> str | None:
    config = team_mode_config if isinstance(team_mode_config, dict) else _load_enabled_team_mode_config(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    if not isinstance(config, dict):
        return None
    oversight = config.get("oversight") if isinstance(config.get("oversight"), dict) else {}
    user_id = str(oversight.get("human_owner_user_id") or "").strip()
    return user_id or None


def _resolve_team_mode_reviewer_user_id(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    team_mode_config: dict[str, Any] | None = None,
) -> str | None:
    config = team_mode_config if isinstance(team_mode_config, dict) else _load_enabled_team_mode_config(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    if not isinstance(config, dict):
        return None
    review_policy = normalize_review_policy(config.get("review_policy"))
    reviewer_user_id = str(review_policy.get("reviewer_user_id") or "").strip()
    if reviewer_user_id:
        return reviewer_user_id
    return _resolve_team_mode_human_owner_user_id(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        team_mode_config=config,
    )


def _resolve_team_agent_assignment_by_role(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    authority_role: str,
) -> tuple[str | None, str | None]:
    normalized_project_id = str(project_id or "").strip()
    normalized_role = str(authority_role or "").strip()
    if not workspace_id or not normalized_project_id or not normalized_role:
        return None, None
    team_agents = _load_team_mode_agents_for_project(
        db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    matching_agent = next(
        (
            agent
            for agent in team_agents
            if str(agent.get("authority_role") or "").strip() == normalized_role
        ),
        None,
    )
    if matching_agent is None:
        return None, None
    assigned_agent_code = str(matching_agent.get("id") or "").strip() or None
    assignee_id = str(matching_agent.get("executor_user_id") or "").strip() or None
    if assignee_id:
        return assignee_id, assigned_agent_code
    member_row = db.execute(
        select(ProjectMember.user_id)
        .join(User, User.id == ProjectMember.user_id)
        .where(
            ProjectMember.workspace_id == str(workspace_id),
            ProjectMember.project_id == normalized_project_id,
            ProjectMember.role == normalized_role,
            User.user_type == "agent",
            User.is_active == True,  # noqa: E712
        )
        .order_by(ProjectMember.id.asc())
    ).first()
    if member_row is None:
        return None, assigned_agent_code
    return str(member_row[0] or "").strip() or None, assigned_agent_code


def _require_task_group_scope(db: Session, *, workspace_id: str, project_id: str, task_group_id: str) -> TaskGroup:
    task_group = load_task_group_command_state(db, task_group_id)
    if not task_group or task_group.is_deleted:
        raise HTTPException(status_code=404, detail="Task group not found")
    if task_group.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Task group does not belong to workspace")
    if task_group.project_id != project_id:
        raise HTTPException(status_code=400, detail="Task group does not belong to project")
    return task_group


def _normalize_instruction(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _parse_handler_iso_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _infer_team_mode_request_origin(
    *,
    db: Session,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    task_view: dict | None,
    state_snapshot: dict[str, object],
) -> tuple[str | None, str | None]:
    normalized_project_id = str(project_id or "").strip()
    normalized_task_id = str(task_id or "").strip()
    if not workspace_id or not normalized_project_id or not normalized_task_id:
        return None, None

    team_mode_row = db.execute(
        select(ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == str(workspace_id),
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if team_mode_row is None:
        return None, None
    try:
        config_obj = json.loads(str(team_mode_row or "").strip() or "{}")
    except Exception:
        config_obj = {}
    if not isinstance(config_obj, dict):
        config_obj = {}

    member_role_by_user_id = {
        str(user_id): str(role or "").strip()
        for user_id, role in db.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(
                ProjectMember.workspace_id == str(workspace_id),
                ProjectMember.project_id == normalized_project_id,
            )
        ).all()
    }
    team_agents = normalize_team_agents(config_obj.get("team"))
    agent_role_by_code = {
        str(agent.get("id") or "").strip(): str(agent.get("authority_role") or "").strip()
        for agent in team_agents
        if str(agent.get("id") or "").strip()
    }
    workflow_role = derive_task_role(
        task_like={
            "assignee_id": str(state_snapshot.get("assignee_id") or (task_view or {}).get("assignee_id") or "").strip(),
            "assigned_agent_code": str(state_snapshot.get("assigned_agent_code") or (task_view or {}).get("assigned_agent_code") or "").strip(),
            "labels": state_snapshot.get("labels") if state_snapshot.get("labels") is not None else (task_view or {}).get("labels"),
            "status": str(state_snapshot.get("status") or (task_view or {}).get("status") or "").strip(),
        },
        member_role_by_user_id=member_role_by_user_id,
        agent_role_by_code=agent_role_by_code,
    )
    if workflow_role not in {"Developer", "Lead", "QA"}:
        return None, None
    if workflow_role == "QA" and str(state_snapshot.get("last_lead_handoff_token") or "").strip():
        return "lead_handoff", None

    def _candidate_timestamp(source_state: dict[str, object], created_at: object) -> float:
        for value in (
            source_state.get("last_requested_triggered_at"),
            source_state.get("last_activity_at"),
            source_state.get("last_requested_at"),
            source_state.get("last_agent_run_at"),
            created_at,
        ):
            parsed = _parse_handler_iso_timestamp(value)
            if parsed is not None:
                return parsed.timestamp()
            if isinstance(value, datetime):
                dt_value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
                return dt_value.astimezone(timezone.utc).timestamp()
        return 0.0

    candidates: list[tuple[int, float, str, str]] = []
    rows = db.execute(
        select(Task.id, Task.assignee_id, Task.assigned_agent_code, Task.status, Task.labels, Task.created_at).where(
            Task.workspace_id == str(workspace_id),
            Task.project_id == normalized_project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        )
    ).all()
    for candidate_id, assignee_id, assigned_agent_code, status, labels, created_at in rows:
        source_task_id = str(candidate_id or "").strip()
        if not source_task_id or source_task_id == normalized_task_id:
            continue
        source_state, _ = rebuild_state(db, "Task", source_task_id)
        source_status = str(source_state.get("status") or status or "").strip()
        source_role = derive_task_role(
            task_like={
                "assignee_id": str(source_state.get("assignee_id") or assignee_id or "").strip(),
                "assigned_agent_code": str(source_state.get("assigned_agent_code") or assigned_agent_code or "").strip(),
                "labels": source_state.get("labels") if source_state.get("labels") is not None else labels,
                "status": source_status,
            },
            member_role_by_user_id=member_role_by_user_id,
            agent_role_by_code=agent_role_by_code,
        )
        source_automation_state = str(source_state.get("automation_state") or "idle").strip().lower()
        source_semantic_status = semantic_status_key(status=source_status)
        candidate_source: str | None = None
        candidate_rank: int | None = None
        if workflow_role == "Developer":
            source_execution_mode = str(source_state.get("last_requested_execution_mode") or "").strip().lower()
            if (
                source_role == "Lead"
                and source_semantic_status in {"todo", "active", "blocked"}
                and bool(source_state.get("last_requested_execution_kickoff_intent"))
                and source_execution_mode in {"kickoff_only", "setup_then_kickoff"}
            ):
                candidate_source = "lead_kickoff_dispatch"
                candidate_rank = 0
        elif workflow_role == "Lead":
            if (
                source_role == "Developer"
                and source_semantic_status in {"active", "completed"}
                and (
                    source_automation_state == "completed"
                    or has_merge_to_main_ref(source_state.get("external_refs"))
                )
            ):
                candidate_source = "developer_handoff"
                candidate_rank = 0
            elif source_role in {"Developer", "QA"} and source_semantic_status == "blocked":
                candidate_source = "blocker_escalation"
                candidate_rank = 1
        elif workflow_role == "QA":
            if source_role == "Lead" and str(source_state.get("last_lead_handoff_token") or "").strip():
                candidate_source = "lead_handoff"
                candidate_rank = 0
        if candidate_source is None or candidate_rank is None:
            continue
        candidates.append((candidate_rank, -_candidate_timestamp(source_state, created_at), candidate_source, source_task_id))

    candidates.sort()
    if not candidates:
        return None, None
    _rank, _neg_ts, source, source_task_id = candidates[0]
    return source, source_task_id


def _fallback_task_instruction(*, title: str, description: str | None) -> str | None:
    normalized_description = _normalize_instruction(description)
    if normalized_description:
        return normalized_description
    normalized_title = _normalize_task_title(title)
    return normalized_title or None


def _with_legacy_schedule_overrides(
    *,
    instruction: str | None,
    execution_triggers: list[dict],
    task_type: str | object = _UNSET,
    scheduled_instruction: str | object = _UNSET,
    scheduled_at_utc: str | object = _UNSET,
    schedule_timezone: str | object = _UNSET,
    recurring_rule: str | object = _UNSET,
    schedule_run_on_statuses: list[str] | object = _UNSET,
) -> tuple[str | None, list[dict]]:
    effective_instruction = _normalize_instruction(instruction)
    effective_triggers = normalize_execution_triggers(execution_triggers)
    _current_schedule_idx, current_schedule_trigger = first_enabled_schedule_trigger(effective_triggers)
    current_legacy = derive_legacy_schedule_fields(
        instruction=effective_instruction,
        execution_triggers=effective_triggers,
    )

    has_legacy_override = any(
        value is not _UNSET
        for value in (
            task_type,
            scheduled_instruction,
            scheduled_at_utc,
            schedule_timezone,
            recurring_rule,
            schedule_run_on_statuses,
        )
    )
    if not has_legacy_override:
        return effective_instruction, effective_triggers

    effective_task_type_raw = task_type if task_type is not _UNSET else current_legacy.get("task_type")
    effective_task_type = str(effective_task_type_raw or "manual").strip().lower()
    explicit_schedule_override_present = any(
        value is not _UNSET
        for value in (
            scheduled_instruction,
            scheduled_at_utc,
            schedule_timezone,
            recurring_rule,
            schedule_run_on_statuses,
        )
    )
    if task_type is _UNSET and effective_task_type == "manual" and explicit_schedule_override_present:
        effective_task_type = "scheduled_instruction"
    if effective_task_type not in {"manual", "scheduled_instruction"}:
        raise HTTPException(status_code=422, detail='task_type must be "manual" or "scheduled_instruction"')

    legacy_instruction = (
        scheduled_instruction
        if scheduled_instruction is not _UNSET
        else current_legacy.get("scheduled_instruction")
    )
    legacy_scheduled_at = (
        scheduled_at_utc
        if scheduled_at_utc is not _UNSET
        else current_legacy.get("scheduled_at_utc")
    )
    legacy_timezone = (
        schedule_timezone
        if schedule_timezone is not _UNSET
        else current_legacy.get("schedule_timezone")
    )
    legacy_recurring_rule = (
        recurring_rule
        if recurring_rule is not _UNSET
        else current_legacy.get("recurring_rule")
    )
    legacy_run_on_statuses = (
        schedule_run_on_statuses
        if schedule_run_on_statuses is not _UNSET
        else (
            current_schedule_trigger.get("run_on_statuses")
            if isinstance(current_schedule_trigger, dict)
            else None
        )
    )

    if effective_task_type == "manual" and explicit_schedule_override_present:
        raise HTTPException(
            status_code=422,
            detail='task_type "manual" cannot include schedule fields; set task_type to "scheduled_instruction"',
        )

    effective_triggers = [
        trigger
        for trigger in effective_triggers
        if str(trigger.get("kind") or "") != TRIGGER_KIND_SCHEDULE
    ]
    if effective_task_type == "scheduled_instruction":
        normalized_legacy_instruction = (
            _normalize_instruction(str(legacy_instruction or ""))
            if legacy_instruction is not _UNSET
            else effective_instruction
        )
        if not str(legacy_scheduled_at or "").strip():
            raise HTTPException(
                status_code=422,
                detail='scheduled_at_utc is required when task_type is "scheduled_instruction"',
            )
        if not normalized_legacy_instruction:
            raise HTTPException(
                status_code=422,
                detail='scheduled_instruction is required when task_type is "scheduled_instruction"',
            )
        next_schedule = build_legacy_schedule_trigger(
            scheduled_at_utc=str(legacy_scheduled_at or "").strip() or None,
            schedule_timezone=str(legacy_timezone or "").strip() or None,
            recurring_rule=str(legacy_recurring_rule or "").strip() or None,
            run_on_statuses=legacy_run_on_statuses,
        )
        if next_schedule is None:
            raise HTTPException(status_code=422, detail="schedule trigger requires scheduled_at_utc")
        effective_triggers.append(next_schedule)
        effective_instruction = normalized_legacy_instruction
    return effective_instruction, normalize_execution_triggers(effective_triggers)


def _validate_automation_fields(
    *,
    instruction: str | None,
    execution_triggers: list[dict],
    source_task_id: str | None = None,
) -> None:
    normalized_instruction = _normalize_instruction(instruction)
    normalized_triggers = normalize_execution_triggers(execution_triggers)
    has_non_manual = any(str(trigger.get("kind") or "") != "manual" for trigger in normalized_triggers)
    if has_non_manual and not normalized_instruction:
        raise HTTPException(status_code=422, detail="instruction is required when non-manual execution triggers are configured")

    for trigger in normalized_triggers:
        kind = str(trigger.get("kind") or "")
        if kind == TRIGGER_KIND_SCHEDULE:
            if not str(trigger.get("scheduled_at_utc") or "").strip():
                raise HTTPException(status_code=422, detail="schedule trigger requires scheduled_at_utc")
            continue
        if kind != TRIGGER_KIND_STATUS_CHANGE:
            continue
        scope = str(trigger.get("scope") or STATUS_SCOPE_SELF).strip().lower()
        if scope not in {STATUS_SCOPE_SELF, STATUS_SCOPE_EXTERNAL}:
            raise HTTPException(status_code=422, detail='status_change scope must be "self" or "external"')
        match_mode = str(trigger.get("match_mode") or STATUS_MATCH_ANY).strip().lower()
        if match_mode not in {STATUS_MATCH_ANY, STATUS_MATCH_ALL}:
            raise HTTPException(status_code=422, detail='status_change match_mode must be "any" or "all"')
        to_statuses = trigger.get("to_statuses")
        if not isinstance(to_statuses, list) or not any(str(item or "").strip() for item in to_statuses):
            raise HTTPException(status_code=422, detail="status_change trigger requires at least one to_statuses value")
        if scope == STATUS_SCOPE_EXTERNAL and source_task_id:
            selector_task_ids = [
                str(item or "").strip()
                for item in (((trigger.get("selector") or {}).get("task_ids")) or [])
                if str(item or "").strip()
            ]
            if str(source_task_id).strip() in selector_task_ids:
                raise HTTPException(
                    status_code=422,
                    detail="status_change external trigger selector.task_ids cannot include the same task id",
                )


def _team_mode_task_dependency_ready(
    *,
    db: Session,
    workspace_id: str,
    project_id: str,
    task_id: str,
    state: dict[str, object],
) -> tuple[bool, str | None]:
    task_relationships = normalize_task_relationships(state.get("task_relationships"))
    if not task_relationships:
        return True, None
    dependency_clauses: list[tuple[bool, str]] = []
    for relationship in task_relationships:
        if str(relationship.get("kind") or "").strip().lower() != "depends_on":
            continue
        source_task_ids = [
            str(item or "").strip()
            for item in (relationship.get("task_ids") or [])
            if str(item or "").strip() and str(item or "").strip() != task_id
        ]
        statuses = {
            str(item or "").strip()
            for item in (relationship.get("statuses") or [])
            if str(item or "").strip()
        }
        if not source_task_ids or not statuses:
            continue
        match_mode = str(relationship.get("match_mode") or STATUS_MATCH_ALL).strip().lower()
        matched_sources = 0
        total_sources = 0
        for source_task_id in source_task_ids:
            source_state, _ = rebuild_state(db, "Task", source_task_id)
            if str(source_state.get("workspace_id") or "").strip() != workspace_id:
                continue
            if str(source_state.get("project_id") or "").strip() != project_id:
                continue
            total_sources += 1
            if any(task_matches_dependency_requirement(source_state, required) for required in statuses):
                matched_sources += 1
        if total_sources <= 0:
            continue
        if match_mode == STATUS_MATCH_ALL:
            if matched_sources == total_sources:
                dependency_clauses.append((True, "relationship dependency satisfied"))
                continue
        elif matched_sources > 0:
            dependency_clauses.append((True, "relationship dependency satisfied"))
            continue
        dependency_clauses.append(
            (
                False,
                f"waiting for dependency: {matched_sources}/{total_sources} source tasks reached {sorted(statuses)}",
            )
        )
    if dependency_clauses:
        for satisfied, _reason in dependency_clauses:
            if satisfied:
                return True, None
        return False, dependency_clauses[0][1]
    return True, None


def require_task_command_state(db: Session, user: User, task_id: str, *, allowed: set[str]) -> tuple[str, str | None, str, bool]:
    state = load_task_command_state(db, task_id)
    if not state or state.is_deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    if state.project_id:
        ensure_project_access(db, state.workspace_id, state.project_id, user.id, allowed)
    else:
        ensure_role(db, state.workspace_id, user.id, allowed)
    return state.workspace_id, state.project_id, state.status, state.archived


def _load_task_aggregate(repo: AggregateEventRepository, task_id: str) -> TaskAggregate:
    return repo.load_with_class(
        aggregate_type="Task",
        aggregate_id=task_id,
        aggregate_cls=TaskAggregate,
    )


def _persist_task_aggregate(
    repo: AggregateEventRepository,
    aggregate: TaskAggregate,
    *,
    actor_id: str,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    expected_version: int | None = None,
) -> None:
    repo.persist(
        aggregate,
        base_metadata={
            "actor_id": actor_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": task_id,
        },
        expected_version=expected_version,
    )


def _task_view_from_aggregate(*, task_id: str, aggregate: TaskAggregate, created_by: str) -> dict:
    instruction = _normalize_instruction(getattr(aggregate, "instruction", None) or getattr(aggregate, "scheduled_instruction", None))
    execution_triggers = normalize_execution_triggers(getattr(aggregate, "execution_triggers", []) or [])
    if not execution_triggers:
        legacy_trigger = build_legacy_schedule_trigger(
            scheduled_at_utc=getattr(aggregate, "scheduled_at_utc", None),
            schedule_timezone=getattr(aggregate, "schedule_timezone", None),
            recurring_rule=getattr(aggregate, "recurring_rule", None),
        )
        if legacy_trigger is not None:
            execution_triggers = [legacy_trigger]
    legacy_schedule = derive_legacy_schedule_fields(
        instruction=instruction,
        execution_triggers=execution_triggers,
    )
    return {
        "id": task_id,
        "workspace_id": getattr(aggregate, "workspace_id", None),
        "project_id": getattr(aggregate, "project_id", None),
        "task_group_id": getattr(aggregate, "task_group_id", None),
        "specification_id": getattr(aggregate, "specification_id", None),
        "title": getattr(aggregate, "title", ""),
        "description": getattr(aggregate, "description", ""),
        "status": getattr(aggregate, "status", "To Do"),
        "priority": getattr(aggregate, "priority", "Med"),
        "due_date": getattr(aggregate, "due_date", None),
        "assignee_id": getattr(aggregate, "assignee_id", None),
        "assigned_agent_code": (str(getattr(aggregate, "assigned_agent_code", "") or "").strip() or None),
        "labels": getattr(aggregate, "labels", []) or [],
        "subtasks": getattr(aggregate, "subtasks", []) or [],
        "attachments": getattr(aggregate, "attachments", []) or [],
        "external_refs": getattr(aggregate, "external_refs", []) or [],
        "attachment_refs": getattr(aggregate, "attachment_refs", getattr(aggregate, "attachments", [])) or [],
        "instruction": instruction,
        "execution_triggers": execution_triggers,
        "task_relationships": normalize_task_relationships(getattr(aggregate, "task_relationships", []) or []),
        "delivery_mode": normalize_delivery_mode(getattr(aggregate, "delivery_mode", None)),
        "recurring_rule": legacy_schedule.get("recurring_rule") or getattr(aggregate, "recurring_rule", None),
        "task_type": str(legacy_schedule.get("task_type") or getattr(aggregate, "task_type", "manual") or "manual"),
        "scheduled_instruction": legacy_schedule.get("scheduled_instruction"),
        "scheduled_at_utc": legacy_schedule.get("scheduled_at_utc"),
        "schedule_timezone": legacy_schedule.get("schedule_timezone"),
        "schedule_state": getattr(aggregate, "schedule_state", "idle") or "idle",
        "last_schedule_run_at": getattr(aggregate, "last_schedule_run_at", None),
        "last_schedule_error": getattr(aggregate, "last_schedule_error", None),
        "archived": bool(getattr(aggregate, "archived", False)),
        "completed_at": getattr(aggregate, "completed_at", None),
        "created_at": None,
        "updated_at": None,
        "created_by": created_by,
        "order_index": int(getattr(aggregate, "order_index", 0) or 0),
    }


@dataclass(frozen=True, slots=True)
class CommandContext:
    db: Session
    user: User


@dataclass(frozen=True, slots=True)
class CreateTaskHandler:
    ctx: CommandContext
    payload: TaskCreate

    def __call__(self) -> dict:
        ensure_role(self.ctx.db, self.payload.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member"})
        project = _require_project_scope(self.ctx.db, workspace_id=self.payload.workspace_id, project_id=self.payload.project_id)
        ensure_project_access(
            self.ctx.db,
            self.payload.workspace_id,
            self.payload.project_id,
            self.ctx.user.id,
            {"Owner", "Admin", "Member"},
        )
        title = _normalize_task_title(self.payload.title)
        if not title:
            raise HTTPException(status_code=422, detail="title cannot be empty")
        tid = _task_aggregate_id(self.payload.project_id, title)
        existing_task_state = load_task_command_state(self.ctx.db, tid)
        if existing_task_state and not existing_task_state.is_deleted:
            task_view = load_task_view(self.ctx.db, tid)
            if task_view is None:
                raise HTTPException(status_code=404, detail="Task not found")
            return task_view
        if existing_task_state and existing_task_state.is_deleted:
            raise HTTPException(
                status_code=409,
                detail="Task with this title already exists in deleted state; restore is not supported",
            )

        specification_id = (self.payload.specification_id or "").strip() or None
        task_group_id = (self.payload.task_group_id or "").strip() or None
        assignee_id = _validate_assignee_id(self.ctx.db, self.payload.assignee_id, project_id=self.payload.project_id)
        assigned_agent_code = _normalize_assigned_agent_code_for_project(
            self.ctx.db,
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            assigned_agent_code=self.payload.assigned_agent_code,
        )
        requested_status = str(self.payload.status or "").strip()
        normalized_requested_triggers = normalize_execution_triggers(self.payload.execution_triggers)
        if (
            not assigned_agent_code
            and _team_mode_enabled_for_project(
                self.ctx.db,
                workspace_id=self.payload.workspace_id,
                project_id=self.payload.project_id,
            )
            and _should_default_new_task_to_team_mode_developer(
                specification_id=specification_id,
                task_type=self.payload.task_type,
                execution_triggers=normalized_requested_triggers,
                initial_status=requested_status or None,
            )
        ):
            assignee_id, assigned_agent_code = _resolve_team_agent_assignment_by_role(
                self.ctx.db,
                workspace_id=self.payload.workspace_id,
                project_id=self.payload.project_id,
                authority_role="Developer",
            )
        assignee_id = _resolve_available_system_bot_assignee_for_project(
            self.ctx.db,
            project_id=self.payload.project_id,
            requested_assignee_id=assignee_id,
            assigned_agent_code=assigned_agent_code,
        )
        assignee_id = _normalize_team_mode_routed_assignee(
            self.ctx.db,
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            assignee_id=assignee_id,
            assigned_agent_code=assigned_agent_code,
        )

        if specification_id:
            _require_specification_scope(
                self.ctx.db,
                workspace_id=self.payload.workspace_id,
                project_id=self.payload.project_id,
                specification_id=specification_id,
            )
        if task_group_id:
            _require_task_group_scope(
                self.ctx.db,
                workspace_id=self.payload.workspace_id,
                project_id=self.payload.project_id,
                task_group_id=task_group_id,
            )
        statuses = list(project.custom_statuses or [])
        initial_status = (statuses[0] if statuses else DEFAULT_STATUSES[0]) or DEFAULT_STATUSES[0]
        if requested_status:
            initial_status = requested_status
        payload_data = self.payload.model_dump(exclude_unset=True)
        legacy_task_type = payload_data.get("task_type", _UNSET)
        if legacy_task_type is not _UNSET:
            normalized_task_type = str(legacy_task_type or "").strip().lower()
            has_explicit_schedule_fields = any(
                key in payload_data
                for key in ("scheduled_instruction", "scheduled_at_utc", "schedule_timezone", "recurring_rule")
            )
            if normalized_task_type == "manual" and not has_explicit_schedule_fields:
                legacy_task_type = _UNSET
        user_tz = get_user_zoneinfo(self.ctx.user)
        scheduled_at = normalize_datetime_to_utc(self.payload.scheduled_at_utc, user_tz)
        external_refs = _normalize_external_refs([r.model_dump() for r in self.payload.external_refs])
        attachment_refs = _normalize_attachment_refs([r.model_dump() for r in self.payload.attachment_refs])
        if not attachment_refs and self.payload.attachments:
            attachment_refs = _normalize_attachment_refs(self.payload.attachments)
        requested_instruction = _normalize_instruction(self.payload.instruction)
        if not requested_instruction:
            requested_instruction = _fallback_task_instruction(
                title=title,
                description=self.payload.description,
            )
        normalized_instruction, normalized_triggers = _with_legacy_schedule_overrides(
            instruction=requested_instruction,
            execution_triggers=normalized_requested_triggers,
            task_type=legacy_task_type,
            scheduled_instruction=payload_data.get("scheduled_instruction", _UNSET),
            scheduled_at_utc=to_iso_utc(scheduled_at) if "scheduled_at_utc" in payload_data else _UNSET,
            schedule_timezone=payload_data.get("schedule_timezone", _UNSET),
            recurring_rule=payload_data.get("recurring_rule", _UNSET),
        )
        _validate_automation_fields(
            instruction=normalized_instruction,
            execution_triggers=normalized_triggers,
            source_task_id=tid,
        )
        legacy_schedule = derive_legacy_schedule_fields(
            instruction=normalized_instruction,
            execution_triggers=normalized_triggers,
        )
        max_order = self.ctx.db.execute(
            select(func.max(Task.order_index)).where(Task.workspace_id == self.payload.workspace_id, Task.project_id == self.payload.project_id)
        ).scalar() or 0
        normalized_labels = _normalize_tags(self.payload.labels)
        normalized_labels, resolved_agent_code = _apply_team_mode_agent_labels(
            self.ctx.db,
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            task_id=tid,
            assignee_id=assignee_id,
            assigned_agent_code=assigned_agent_code,
            status=initial_status,
            labels=normalized_labels,
        )
        aggregate = TaskAggregate(
            id=coerce_originator_id(tid),
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            task_group_id=task_group_id,
            specification_id=specification_id,
            title=title,
            description=self.payload.description,
            status=initial_status,
            priority=self.payload.priority,
            due_date=to_iso_utc(normalize_datetime_to_utc(self.payload.due_date, user_tz)),
            assignee_id=assignee_id,
            assigned_agent_code=resolved_agent_code,
            labels=normalized_labels,
            subtasks=self.payload.subtasks,
            attachments=attachment_refs,
            external_refs=external_refs,
            attachment_refs=attachment_refs,
            instruction=normalized_instruction,
            execution_triggers=normalized_triggers,
            task_relationships=normalize_task_relationships(self.payload.task_relationships),
            delivery_mode=normalize_delivery_mode(self.payload.delivery_mode),
            recurring_rule=legacy_schedule.get("recurring_rule"),
            task_type=str(legacy_schedule.get("task_type") or "manual"),
            scheduled_instruction=legacy_schedule.get("scheduled_instruction"),
            scheduled_at_utc=legacy_schedule.get("scheduled_at_utc"),
            schedule_timezone=legacy_schedule.get("schedule_timezone"),
            schedule_state="idle",
            order_index=max_order + 1,
        )
        _persist_task_aggregate(
            AggregateEventRepository(self.ctx.db),
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            task_id=tid,
            expected_version=0,
        )
        try:
            self.ctx.db.commit()
        except IntegrityError as exc:
            self.ctx.db.rollback()
            message = str(exc).lower()
            if "unique constraint failed" not in message or "tasks.id" not in message:
                raise
        _backfill_team_mode_structural_dependencies(
            self.ctx.db,
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            specification_id=specification_id,
            actor_user_id=str(self.ctx.user.id),
        )
        self.ctx.db.commit()
        task_view = load_task_view(self.ctx.db, tid)
        if task_view is not None:
            return task_view
        return _task_view_from_aggregate(task_id=tid, aggregate=aggregate, created_by=self.ctx.user.id)


@dataclass(frozen=True, slots=True)
class PatchTaskHandler:
    ctx: CommandContext
    task_id: str
    payload: TaskPatch

    def __call__(self) -> dict:
        user_tz = get_user_zoneinfo(self.ctx.user)
        data = self.payload.model_dump(exclude_unset=True)
        workspace_id, project_id, _, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        if "project_id" in data:
            if not data["project_id"]:
                raise HTTPException(status_code=422, detail="project_id cannot be null")
            _require_project_scope(self.ctx.db, workspace_id=workspace_id, project_id=str(data["project_id"]))
            ensure_project_access(
                self.ctx.db,
                workspace_id,
                str(data["project_id"]),
                self.ctx.user.id,
                {"Owner", "Admin", "Member"},
            )
        if "labels" in data and data["labels"] is not None:
            data["labels"] = _normalize_tags(data["labels"])
        if "assignee_id" in data:
            try:
                data["assignee_id"] = _validate_assignee_id(
                    self.ctx.db,
                    data.get("assignee_id"),
                    project_id=str(data.get("project_id") or project_id or ""),
                )
            except HTTPException as exc:
                # Agent automation should not hard-fail a run due to bad assignee text;
                # keep current assignee and continue with the rest of the patch payload.
                if int(getattr(exc, "status_code", 0) or 0) == 422 and str(self.ctx.user.user_type or "").strip() == "agent":
                    _LOG.warning(
                        "Ignoring invalid assignee_id patch from agent user %s on task %s: %s",
                        str(self.ctx.user.id or "").strip(),
                        self.task_id,
                        str(getattr(exc, "detail", "") or "").strip(),
                    )
                    data.pop("assignee_id", None)
                else:
                    raise
        if "external_refs" in data and data["external_refs"] is not None:
            data["external_refs"] = _normalize_external_refs(data["external_refs"])
        if "attachment_refs" in data and data["attachment_refs"] is not None:
            data["attachment_refs"] = _normalize_attachment_refs(data["attachment_refs"])
            data["attachments"] = data["attachment_refs"]
        elif "attachments" in data and data["attachments"] is not None:
            data["attachments"] = _normalize_attachment_refs(data["attachments"])
            data["attachment_refs"] = data["attachments"]
        current_row = self.ctx.db.get(Task, self.task_id)
        current_state = None
        if get_kurrent_client() is not None:
            current_state, _ = rebuild_state(self.ctx.db, "Task", self.task_id)
        if current_row is None and not current_state:
            raise HTTPException(status_code=404, detail="Task not found")
        current_assigned_agent_code = str(
            (
                current_state.get("assigned_agent_code")
                if current_state
                else (current_row.assigned_agent_code if current_row is not None else "")
            )
            or ""
        ).strip() or None

        current_task_type = (
            (str(current_state.get("task_type")) if current_state else None)
            or (current_row.task_type if current_row is not None else None)
            or "manual"
        )
        current_status = (
            str((current_state or {}).get("status") or "").strip()
            or (str(current_row.status or "").strip() if current_row is not None else "")
        )
        current_instruction = _normalize_instruction(
            (current_state.get("instruction") if current_state else None)
            or (current_state.get("scheduled_instruction") if current_state else None)
            or (current_row.instruction if current_row is not None else None)
            or (current_row.scheduled_instruction if current_row is not None else None)
        )
        current_scheduled_instruction = (
            (current_state.get("scheduled_instruction") if current_state else None)
            or (current_row.scheduled_instruction if current_row is not None else None)
        )
        current_scheduled_at_utc = (
            (current_state.get("scheduled_at_utc") if current_state else None)
            or (to_iso_utc(current_row.scheduled_at_utc) if current_row is not None else None)
        )
        current_schedule_timezone = (
            (current_state.get("schedule_timezone") if current_state else None)
            or (current_row.schedule_timezone if current_row is not None else None)
        )
        current_recurring_rule = (
            (current_state.get("recurring_rule") if current_state else None)
            or (current_row.recurring_rule if current_row is not None else None)
        )
        current_schedule_state = (
            (current_state.get("schedule_state") if current_state else None)
            or (current_row.schedule_state if current_row is not None else None)
            or "idle"
        )
        current_execution_triggers = normalize_execution_triggers(
            current_state.get("execution_triggers") if current_state else (
                current_row.execution_triggers if current_row is not None else []
            )
        )
        current_task_relationships = normalize_task_relationships(
            current_state.get("task_relationships") if current_state else (
                current_row.task_relationships if current_row is not None else []
            )
        )
        if str(current_task_type).strip().lower() == "manual":
            current_execution_triggers = [
                trigger
                for trigger in current_execution_triggers
                if str(trigger.get("kind") or "") != TRIGGER_KIND_SCHEDULE
            ]
        if not current_execution_triggers and str(current_task_type).strip().lower() != "manual":
            legacy_trigger = build_legacy_schedule_trigger(
                scheduled_at_utc=current_scheduled_at_utc,
                schedule_timezone=current_schedule_timezone,
                recurring_rule=current_recurring_rule,
            )
            if legacy_trigger is not None:
                current_execution_triggers = [legacy_trigger]
        current_specification_id = (
            (current_state.get("specification_id") if current_state else None)
            or (current_row.specification_id if current_row is not None else None)
        )
        current_task_group_id = (
            (current_state.get("task_group_id") if current_state else None)
            or (current_row.task_group_id if current_row is not None else None)
        )
        effective_project_id = str(data.get("project_id", project_id) or "")
        if not effective_project_id:
            raise HTTPException(status_code=422, detail="project_id is required")
        project_id_changed = "project_id" in data and str(data.get("project_id") or "") != str(project_id or "")
        if project_id_changed and current_specification_id and "specification_id" not in data:
            raise HTTPException(status_code=409, detail="Cannot change project while task is linked to specification")
        if project_id_changed and current_task_group_id and "task_group_id" not in data:
            raise HTTPException(status_code=409, detail="Cannot change project while task is linked to task group")
        if "task_group_id" in data:
            if data.get("task_group_id"):
                _require_task_group_scope(
                    self.ctx.db,
                    workspace_id=workspace_id,
                    project_id=effective_project_id,
                    task_group_id=str(data["task_group_id"]),
                )
            else:
                data["task_group_id"] = None
        if "specification_id" in data:
            specification_id = data.get("specification_id")
            if specification_id:
                _require_specification_scope(
                    self.ctx.db,
                    workspace_id=workspace_id,
                    project_id=effective_project_id,
                    specification_id=str(specification_id),
                )
            else:
                data["specification_id"] = None
        if "assigned_agent_code" in data:
            requested_assigned_agent_code = str(data.get("assigned_agent_code") or "").strip() or None
            if (
                str(self.ctx.user.user_type or "").strip().lower() == "agent"
                and requested_assigned_agent_code != current_assigned_agent_code
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Agent automation cannot change assigned_agent_code on existing tasks; request human rerouting.",
                )
            data["assigned_agent_code"] = _normalize_assigned_agent_code_for_project(
                self.ctx.db,
                workspace_id=workspace_id,
                project_id=effective_project_id,
                assigned_agent_code=data.get("assigned_agent_code"),
            )
        event_payload = dict(data)
        existing_labels: list[str] = []
        raw_existing_labels = (
            current_state.get("labels") if current_state is not None else (
                current_row.labels if current_row is not None else []
            )
        )
        if isinstance(raw_existing_labels, list):
            existing_labels = _normalize_tags([str(item or "") for item in raw_existing_labels])
        else:
            try:
                parsed_existing_labels = json.loads(str(raw_existing_labels or "").strip() or "[]")
            except Exception:
                parsed_existing_labels = []
            if isinstance(parsed_existing_labels, list):
                existing_labels = _normalize_tags([str(item or "") for item in parsed_existing_labels])
        effective_assignee_id = str(
            event_payload.get("assignee_id")
            if "assignee_id" in event_payload
            else ((current_state.get("assignee_id") if current_state else None) or (current_row.assignee_id if current_row is not None else ""))
            or ""
        ).strip() or None
        effective_assigned_agent_code = str(
            event_payload.get("assigned_agent_code")
            if "assigned_agent_code" in event_payload
            else (
                (current_state.get("assigned_agent_code") if current_state else None)
                or (current_row.assigned_agent_code if current_row is not None else "")
            )
            or ""
        ).strip() or None
        effective_assignee_id = _normalize_team_mode_routed_assignee(
            self.ctx.db,
            workspace_id=workspace_id,
            project_id=effective_project_id,
            assignee_id=effective_assignee_id,
            assigned_agent_code=effective_assigned_agent_code,
        )
        if effective_assignee_id is None and effective_assigned_agent_code:
            event_payload["assignee_id"] = None
        effective_status_for_labels = str(event_payload.get("status") or current_status or "").strip()
        incoming_labels = (
            _normalize_tags(event_payload.get("labels"))
            if "labels" in event_payload and isinstance(event_payload.get("labels"), list)
            else existing_labels
        )
        resolved_labels, resolved_agent_code = _apply_team_mode_agent_labels(
            self.ctx.db,
            workspace_id=workspace_id,
            project_id=effective_project_id,
            task_id=self.task_id,
            assignee_id=effective_assignee_id,
            assigned_agent_code=effective_assigned_agent_code,
            status=effective_status_for_labels,
            labels=incoming_labels,
        )
        event_payload["labels"] = resolved_labels
        event_payload["assigned_agent_code"] = resolved_agent_code
        if "due_date" in event_payload:
            event_payload["due_date"] = to_iso_utc(normalize_datetime_to_utc(event_payload["due_date"], user_tz))
        if "scheduled_at_utc" in event_payload:
            event_payload["scheduled_at_utc"] = to_iso_utc(normalize_datetime_to_utc(event_payload["scheduled_at_utc"], user_tz))
        if "instruction" in event_payload:
            event_payload["instruction"] = _normalize_instruction(event_payload.get("instruction"))
        if "scheduled_instruction" in event_payload and event_payload["scheduled_instruction"] is not None:
            event_payload["scheduled_instruction"] = str(event_payload["scheduled_instruction"]).strip() or None

        requested_instruction = event_payload.get("instruction", current_instruction)
        requested_triggers = (
            normalize_execution_triggers(event_payload.get("execution_triggers"))
            if "execution_triggers" in event_payload
            else current_execution_triggers
        )
        requested_relationships = (
            normalize_task_relationships(event_payload.get("task_relationships"))
            if "task_relationships" in event_payload
            else current_task_relationships
        )
        if "delivery_mode" in event_payload:
            event_payload["delivery_mode"] = normalize_delivery_mode(event_payload.get("delivery_mode"))
        elif current_state:
            event_payload["delivery_mode"] = normalize_delivery_mode(current_state.get("delivery_mode"))
        else:
            event_payload["delivery_mode"] = DELIVERY_MODE_DEPLOYABLE_SLICE
        normalized_instruction, normalized_triggers = _with_legacy_schedule_overrides(
            instruction=requested_instruction,
            execution_triggers=requested_triggers,
            task_type=event_payload.get("task_type", _UNSET),
            scheduled_instruction=event_payload.get("scheduled_instruction", _UNSET),
            scheduled_at_utc=event_payload.get("scheduled_at_utc", _UNSET),
            schedule_timezone=event_payload.get("schedule_timezone", _UNSET),
            recurring_rule=event_payload.get("recurring_rule", _UNSET),
        )
        _validate_automation_fields(
            instruction=normalized_instruction,
            execution_triggers=normalized_triggers,
            source_task_id=self.task_id,
        )
        legacy_schedule = derive_legacy_schedule_fields(
            instruction=normalized_instruction,
            execution_triggers=normalized_triggers,
        )
        event_payload["instruction"] = normalized_instruction
        event_payload["execution_triggers"] = normalized_triggers
        event_payload["task_relationships"] = requested_relationships
        event_payload["task_type"] = str(legacy_schedule.get("task_type") or "manual")
        event_payload["scheduled_instruction"] = legacy_schedule.get("scheduled_instruction")
        event_payload["scheduled_at_utc"] = legacy_schedule.get("scheduled_at_utc")
        event_payload["schedule_timezone"] = legacy_schedule.get("schedule_timezone")
        event_payload["recurring_rule"] = legacy_schedule.get("recurring_rule")

        automation_config_fields = {
            "instruction",
            "execution_triggers",
            "task_relationships",
            "task_type",
            "scheduled_instruction",
            "scheduled_at_utc",
            "schedule_timezone",
            "recurring_rule",
        }
        automation_config_touched = any(field in data for field in automation_config_fields)
        if automation_config_touched:
            event_payload["schedule_state"] = "idle"
            event_payload["last_schedule_error"] = None
        if not has_enabled_schedule_trigger(normalized_triggers):
            event_payload["schedule_state"] = "idle"
            event_payload["last_schedule_error"] = None
        elif "schedule_state" in event_payload and event_payload["schedule_state"] is None:
            event_payload["schedule_state"] = current_schedule_state or "idle"

        requested_status = str(event_payload.get("status") or "").strip()
        if requested_status and current_status:
            _enforce_team_mode_transition_policy(
                db=self.ctx.db,
                workspace_id=workspace_id,
                project_id=str(event_payload.get("project_id") or project_id or "").strip() or None,
                actor_user_id=str(self.ctx.user.id),
                from_status=current_status,
                to_status=requested_status,
                task_id=self.task_id,
            )
        team_mode_config = _load_enabled_team_mode_config(
            self.ctx.db,
            workspace_id=workspace_id,
            project_id=str(event_payload.get("project_id") or project_id or "").strip() or None,
        )
        status_semantics = normalize_status_semantics(
            team_mode_config.get("status_semantics") if isinstance(team_mode_config, dict) else None
        )
        current_semantic_status = semantic_status_key(status=current_status, status_semantics=status_semantics)
        requested_semantic_status = semantic_status_key(status=requested_status, status_semantics=status_semantics)
        review_policy = normalize_review_policy(
            team_mode_config.get("review_policy") if isinstance(team_mode_config, dict) else None
        )
        if requested_semantic_status == "in_review" and bool(review_policy.get("require_code_review")):
            reviewer_user_id = _resolve_team_mode_reviewer_user_id(
                self.ctx.db,
                workspace_id=workspace_id,
                project_id=str(event_payload.get("project_id") or project_id or "").strip() or None,
                team_mode_config=team_mode_config,
            )
            if not reviewer_user_id:
                raise HTTPException(
                    status_code=409,
                    detail="Code review requires a configured human reviewer before entering In Review.",
                )
            review_source_assignee_id = effective_assignee_id
            review_source_assigned_agent_code = resolved_agent_code
            if current_semantic_status == "in_review":
                review_source_assignee_id = str(
                    event_payload.get("review_source_assignee_id")
                    or (current_state.get("review_source_assignee_id") if current_state else None)
                    or ""
                ).strip() or None
                review_source_assigned_agent_code = str(
                    event_payload.get("review_source_assigned_agent_code")
                    or (current_state.get("review_source_assigned_agent_code") if current_state else None)
                    or ""
                ).strip() or None
            lead_assignee_id, lead_agent_code = _resolve_team_agent_assignment_by_role(
                self.ctx.db,
                workspace_id=workspace_id,
                project_id=str(event_payload.get("project_id") or project_id or "").strip() or None,
                authority_role="Lead",
            )
            event_payload["assignee_id"] = reviewer_user_id
            event_payload["assigned_agent_code"] = None
            event_payload["review_required"] = True
            event_payload["review_status"] = "pending"
            event_payload["review_requested_at"] = to_iso_utc(datetime.now(timezone.utc))
            event_payload["review_source_assignee_id"] = review_source_assignee_id
            event_payload["review_source_assigned_agent_code"] = review_source_assigned_agent_code
            event_payload["review_next_lead_assignee_id"] = lead_assignee_id
            event_payload["review_next_lead_assigned_agent_code"] = lead_agent_code
            event_payload["team_mode_phase"] = "in_review"

        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.update(changes=event_payload)
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=event_payload.get("project_id", project_id),
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        task_view = load_task_view(self.ctx.db, self.task_id)
        if task_view is None:
            raise HTTPException(status_code=404, detail="Task not found")
        _maybe_cleanup_plugin_worktree(
            db=self.ctx.db,
            task_id=self.task_id,
            project_id=str(task_view.get("project_id") or "").strip() or None,
            assignee_id=str(task_view.get("assignee_id") or "").strip() or None,
            status=str(task_view.get("status") or "").strip(),
        )
        return task_view


@dataclass(frozen=True, slots=True)
class CompleteTaskHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, status, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        completed_status = _effective_completed_status_for_project(
            self.ctx.db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if _is_completed_status(status, completed_status=completed_status):
            task_view = load_task_view(self.ctx.db, self.task_id)
            if task_view is None:
                raise HTTPException(status_code=404, detail="Task not found")
            return task_view
        _enforce_team_mode_transition_policy(
            db=self.ctx.db,
            workspace_id=workspace_id,
            project_id=project_id,
            actor_user_id=str(self.ctx.user.id),
            from_status=str(status or "").strip(),
            to_status=completed_status,
            task_id=self.task_id,
        )
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.complete(
            completed_at=to_iso_utc(datetime.now(timezone.utc)),
            status=completed_status,
        )
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        task_view = load_task_view(self.ctx.db, self.task_id)
        if task_view is None:
            raise HTTPException(status_code=404, detail="Task not found")
        _maybe_cleanup_plugin_worktree(
            db=self.ctx.db,
            task_id=self.task_id,
            project_id=str(task_view.get("project_id") or "").strip() or None,
            assignee_id=str(task_view.get("assignee_id") or "").strip() or None,
            status=str(task_view.get("status") or "").strip(),
        )
        return task_view


@dataclass(frozen=True, slots=True)
class ReviewTaskHandler:
    ctx: CommandContext
    task_id: str
    action: str
    comment: str | None = None

    def __call__(self) -> dict:
        workspace_id, project_id, status, _ = require_task_command_state(
            self.ctx.db,
            self.ctx.user,
            self.task_id,
            allowed={"Owner", "Admin", "Member"},
        )
        normalized_project_id = str(project_id or "").strip()
        if not normalized_project_id:
            raise HTTPException(status_code=409, detail="Review actions require a project task.")
        team_mode_config = _load_enabled_team_mode_config(
            self.ctx.db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
        )
        if not isinstance(team_mode_config, dict):
            raise HTTPException(status_code=409, detail="Review actions require Team Mode to be enabled.")
        status_semantics = normalize_status_semantics(team_mode_config.get("status_semantics"))
        if semantic_status_key(status=status, status_semantics=status_semantics) != "in_review":
            raise HTTPException(status_code=409, detail="Review action is only allowed when the task is In Review.")

        normalized_action = str(self.action or "").strip().lower()
        if normalized_action not in {"approve", "request_changes"}:
            raise HTTPException(status_code=422, detail='action must be "approve" or "request_changes"')

        state_snapshot, _ = rebuild_state(self.ctx.db, "Task", self.task_id)
        review_source_assignee_id = str(state_snapshot.get("review_source_assignee_id") or "").strip() or None
        review_source_assigned_agent_code = str(state_snapshot.get("review_source_assigned_agent_code") or "").strip() or None
        review_next_lead_assignee_id = str(state_snapshot.get("review_next_lead_assignee_id") or "").strip() or None
        review_next_lead_assigned_agent_code = str(state_snapshot.get("review_next_lead_assigned_agent_code") or "").strip() or None

        if normalized_action == "approve":
            transition = review_resolution_transition(action="approve")
            target_assignee_id = review_source_assignee_id
            target_assigned_agent_code = review_source_assigned_agent_code
            if not target_assigned_agent_code:
                target_assignee_id, target_assigned_agent_code = _resolve_team_agent_assignment_by_role(
                    self.ctx.db,
                    workspace_id=workspace_id,
                    project_id=normalized_project_id,
                    authority_role="Developer",
                )
            if not target_assigned_agent_code:
                raise HTTPException(status_code=409, detail="Review approval requires a configured Developer agent.")
            target_status = str(transition.get("status") or status_semantics["active"])
            target_phase = str(transition.get("phase") or "implementation")
            request_source = "review_approved"
            default_comment = "Code review approved. Returning task to Developer to complete merge handoff."
        else:
            transition = review_resolution_transition(action="request_changes")
            target_assignee_id = review_source_assignee_id
            target_assigned_agent_code = review_source_assigned_agent_code
            if not target_assigned_agent_code:
                target_assignee_id, target_assigned_agent_code = _resolve_team_agent_assignment_by_role(
                    self.ctx.db,
                    workspace_id=workspace_id,
                    project_id=normalized_project_id,
                    authority_role="Developer",
                )
            if not target_assigned_agent_code:
                raise HTTPException(status_code=409, detail="Requesting changes requires a configured Developer agent.")
            target_status = str(transition.get("status") or status_semantics["active"])
            target_phase = str(transition.get("phase") or "implementation")
            request_source = "review_changes_requested"
            default_comment = "Code review requested changes. Returning task to implementation."

        effective_comment = _normalize_instruction(self.comment) or default_comment
        requested_at = to_iso_utc(datetime.now(timezone.utc))
        instruction = _normalize_instruction(
            str(state_snapshot.get("instruction") or "").strip()
            or str(state_snapshot.get("scheduled_instruction") or "").strip()
        )

        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.update(
            changes={
                "status": target_status,
                "assignee_id": target_assignee_id,
                "assigned_agent_code": target_assigned_agent_code,
                "review_required": normalized_action != "approve",
                "review_status": str(transition.get("review_status") or ("approved" if normalized_action == "approve" else "changes_requested")),
                "reviewed_by_user_id": str(self.ctx.user.id),
                "reviewed_at": requested_at,
                "team_mode_phase": target_phase,
                "team_mode_blocking_gate": None,
                "team_mode_blocked_reason": None,
                "team_mode_blocked_at": None,
            }
        )
        aggregate.add_comment(task_id=self.task_id, user_id=self.ctx.user.id, body=effective_comment)
        if instruction:
            aggregate.request_automation(
                requested_at=requested_at,
                instruction=instruction,
                source=request_source,
                execution_intent=True,
                execution_kickoff_intent=False,
                project_creation_intent=False,
                workflow_scope="team_mode",
                execution_mode="resume_execution",
                task_completion_requested=False,
                classifier_reason="Explicit code review decision.",
            )
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        if instruction:
            try:
                from features.agents.runner import start_automation_runner, wake_automation_runner

                start_automation_runner()
                wake_automation_runner()
            except Exception:
                pass
        task_view = load_task_view(self.ctx.db, self.task_id)
        if task_view is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task_view


@dataclass(frozen=True, slots=True)
class ReopenTaskHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, status, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        completed_status = _effective_completed_status_for_project(
            self.ctx.db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if not _is_completed_status(status, completed_status=completed_status):
            task_view = load_task_view(self.ctx.db, self.task_id)
            if task_view is None:
                raise HTTPException(status_code=404, detail="Task not found")
            return task_view
        reopen_status = "To Do"
        if project_id:
            project = load_project_command_state(self.ctx.db, project_id)
            if project is not None and not project.is_deleted:
                statuses = list(project.custom_statuses or [])
                reopen_status = (statuses[0] if statuses else DEFAULT_STATUSES[0]) or DEFAULT_STATUSES[0]
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.reopen(status=reopen_status)
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        task_view = load_task_view(self.ctx.db, self.task_id)
        if task_view is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task_view


@dataclass(frozen=True, slots=True)
class ArchiveTaskHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, _, archived = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        if archived:
            return {"ok": True}
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.archive()
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class RestoreTaskHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, _, archived = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        if not archived:
            return {"ok": True}
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.restore()
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class BulkTaskActionHandler:
    ctx: CommandContext
    payload: BulkAction

    def __call__(self, task_id: str) -> bool:
        workspace_id, project_id, status, archived = require_task_command_state(self.ctx.db, self.ctx.user, task_id, allowed={"Owner", "Admin", "Member"})
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, task_id)
        completed_status = _effective_completed_status_for_project(
            self.ctx.db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if self.payload.action == "complete":
            if _is_completed_status(status, completed_status=completed_status):
                return False
            _enforce_team_mode_transition_policy(
                db=self.ctx.db,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=str(self.ctx.user.id),
                from_status=str(status or "").strip(),
                to_status=completed_status,
                task_id=task_id,
            )
            aggregate.complete(
                completed_at=to_iso_utc(datetime.now(timezone.utc)),
                status=completed_status,
            )
        elif self.payload.action == "archive":
            if archived:
                return False
            aggregate.archive()
        elif self.payload.action == "delete":
            aggregate.delete()
        elif self.payload.action == "set_status":
            target_status = str(self.payload.payload.get("status", status) or "").strip() or str(status or "").strip()
            _enforce_team_mode_transition_policy(
                db=self.ctx.db,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=str(self.ctx.user.id),
                from_status=str(status or "").strip(),
                to_status=target_status,
                task_id=task_id,
            )
            aggregate.update(changes={"status": target_status})
        elif self.payload.action == "reopen":
            if not _is_completed_status(status, completed_status=completed_status):
                return False
            reopen_status = str(self.payload.payload.get("status", "To Do") or "").strip() or "To Do"
            _enforce_team_mode_transition_policy(
                db=self.ctx.db,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=str(self.ctx.user.id),
                from_status=str(status or "").strip(),
                to_status=reopen_status,
                task_id=task_id,
            )
            aggregate.reopen(status=reopen_status)
        else:
            return False
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=task_id,
        )
        self.ctx.db.commit()
        task_view = load_task_view(self.ctx.db, task_id)
        if task_view:
            _maybe_cleanup_plugin_worktree(
                db=self.ctx.db,
                task_id=task_id,
                project_id=str(task_view.get("project_id") or "").strip() or None,
                assignee_id=str(task_view.get("assignee_id") or "").strip() or None,
                status=str(task_view.get("status") or "").strip(),
            )
        return True


@dataclass(frozen=True, slots=True)
class ReorderTasksHandler:
    ctx: CommandContext
    workspace_id: str
    project_id: str
    payload: ReorderPayload

    def __call__(self, task_id: str, order_index: int) -> bool:
        state = load_task_command_state(self.ctx.db, task_id)
        if (
            not state
            or state.is_deleted
            or state.workspace_id != self.workspace_id
            or state.project_id != self.project_id
        ):
            return False
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, task_id)
        target_status = str(self.payload.status or "").strip()
        if target_status:
            _enforce_team_mode_transition_policy(
                db=self.ctx.db,
                workspace_id=self.workspace_id,
                project_id=state.project_id,
                actor_user_id=str(self.ctx.user.id),
                from_status=str(state.status or "").strip(),
                to_status=target_status,
                task_id=task_id,
            )
        aggregate.reorder(order_index=order_index, status=self.payload.status)
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=self.workspace_id,
            project_id=state.project_id,
            task_id=task_id,
        )
        self.ctx.db.commit()
        return True


@dataclass(frozen=True, slots=True)
class AddCommentHandler:
    ctx: CommandContext
    task_id: str
    payload: CommentCreate

    def __call__(self) -> dict:
        workspace_id, project_id, _, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member", "Guest"})
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.add_comment(task_id=self.task_id, user_id=self.ctx.user.id, body=self.payload.body)
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        _emit_mention_notifications(
            self.ctx.db,
            actor=self.ctx.user,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
            body=self.payload.body,
        )
        self.ctx.db.commit()
        last = self.ctx.db.execute(select(TaskComment).where(TaskComment.task_id == self.task_id).order_by(TaskComment.id.desc()).limit(1)).scalar_one_or_none()
        if last:
            return {"id": last.id, "task_id": self.task_id, "body": last.body, "created_at": to_iso_utc(last.created_at)}
        return {"id": None, "task_id": self.task_id, "body": self.payload.body, "created_at": None}


@dataclass(frozen=True, slots=True)
class DeleteCommentHandler:
    ctx: CommandContext
    task_id: str
    comment_id: int

    def __call__(self) -> dict:
        workspace_id, project_id, _, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member", "Guest"})
        comment = self.ctx.db.get(TaskComment, self.comment_id)
        if not comment or comment.task_id != self.task_id:
            raise HTTPException(status_code=404, detail="Comment not found")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.delete_comment(task_id=self.task_id, comment_id=self.comment_id)
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class ToggleWatchHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, _, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member", "Guest"})
        currently_watched = (
            self.ctx.db.execute(
                select(func.count()).select_from(TaskWatcher).where(
                    TaskWatcher.task_id == self.task_id,
                    TaskWatcher.user_id == self.ctx.user.id,
                )
            ).scalar_one()
            or 0
        ) > 0
        next_watched = not currently_watched
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.toggle_watch(task_id=self.task_id, user_id=self.ctx.user.id, watched=next_watched)
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        return {"watched": next_watched}


@dataclass(frozen=True, slots=True)
class RequestAutomationRunHandler:
    ctx: CommandContext
    task_id: str
    instruction: str | None = None
    source: str | None = None
    source_task_id: str | None = None
    chat_session_id: str | None = None
    execution_intent: bool | None = None
    execution_kickoff_intent: bool | None = None
    project_creation_intent: bool | None = None
    workflow_scope: str | None = None
    execution_mode: str | None = None
    task_completion_requested: bool | None = None
    classifier_reason: str | None = None
    wake_runner: bool = True

    def __call__(self) -> dict:
        workspace_id, project_id, _, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        requested_at = to_iso_utc(datetime.now(timezone.utc))
        task_view = load_task_view(self.ctx.db, self.task_id)
        state_snapshot, _ = rebuild_state(self.ctx.db, "Task", self.task_id)
        current_automation_state = str(state_snapshot.get("automation_state") or task_view.get("automation_state") if task_view else "").strip().lower()
        actor_user_type = str(getattr(self.ctx.user, "user_type", "") or "").strip().lower()
        actor_is_agent = bool(str(self.ctx.user.id or "").strip() == AGENT_SYSTEM_USER_ID or actor_user_type == "agent")
        # Prevent infinite self-requeue loops from in-flight automation runs.
        # Human users can still request a rerun manually if needed.
        if (
            actor_is_agent
            and current_automation_state in {"queued", "running"}
        ):
            return {
                "ok": True,
                "task_id": self.task_id,
                "automation_state": current_automation_state,
                "requested_at": requested_at,
                "skipped": True,
                "reason": "Task automation is already in progress with the same instruction.",
            }
        requested_source = str(self.source or "").strip().lower()
        requested_source_task_id = str(self.source_task_id or "").strip() or None
        if requested_source_task_id == str(self.task_id or "").strip():
            requested_source_task_id = None
        if not requested_source:
            requested_source = "manual"
        elif requested_source not in {
            "manual",
            "manual_stream",
            "lead_kickoff_dispatch",
            "developer_handoff",
            "developer_handoff_recovery",
            "lead_handoff",
            "lead_triage_return",
            "main_reconcile",
            "runner_orchestrator",
            "trigger_reconcile",
            "status_change",
            "schedule",
            "auto_retry",
            "blocker_escalation",
            "setup_orchestration_default",
            "runner_recover_after_interrupt",
            "runner_recover_after_failure",
        }:
            requested_source = "manual"
        if requested_source in {"manual", "manual_stream"} and not requested_source_task_id and project_id:
            inferred_source, inferred_source_task_id = _infer_team_mode_request_origin(
                db=self.ctx.db,
                workspace_id=str(workspace_id),
                project_id=str(project_id),
                task_id=self.task_id,
                task_view=task_view,
                state_snapshot=state_snapshot,
            )
            if inferred_source_task_id:
                requested_source_task_id = inferred_source_task_id
                if inferred_source:
                    requested_source = inferred_source
        if (
            actor_is_agent
            and current_automation_state == "completed"
            and requested_source in {"runner_orchestrator", "developer_handoff", "lead_kickoff_dispatch"}
            and str(state_snapshot.get("last_requested_source") or "").strip() == requested_source
            and str(state_snapshot.get("last_requested_source_task_id") or "").strip() == str(requested_source_task_id or "").strip()
        ):
            return {
                "ok": True,
                "task_id": self.task_id,
                "automation_state": current_automation_state,
                "requested_at": requested_at,
                "skipped": True,
                "reason": "Task automation request skipped because the same Team Mode handoff is already recorded.",
            }

        fallback_instruction = _normalize_instruction(task_view.get("instruction") if task_view else None)
        effective_instruction = _normalize_instruction(self.instruction)
        explicit_execution_classification = any(
            value is not None
            for value in (
                self.execution_intent,
                self.execution_kickoff_intent,
                self.project_creation_intent,
                self.workflow_scope,
                self.execution_mode,
                self.task_completion_requested,
                self.classifier_reason,
            )
        )
        should_default_to_team_mode_kickoff = False
        default_kickoff_workflow_role = None
        if (
            requested_source in {"manual", "manual_stream"}
            and project_id
            and not explicit_execution_classification
        ):
            team_mode_row = self.ctx.db.execute(
                select(ProjectPluginConfig.config_json).where(
                    ProjectPluginConfig.workspace_id == str(workspace_id),
                    ProjectPluginConfig.project_id == str(project_id),
                    ProjectPluginConfig.plugin_key == "team_mode",
                    ProjectPluginConfig.enabled == True,  # noqa: E712
                    ProjectPluginConfig.is_deleted == False,  # noqa: E712
                )
            ).first()
            if team_mode_row is not None:
                config_obj: dict[str, object] = {}
                try:
                    parsed_cfg = json.loads(str(team_mode_row[0] or "").strip() or "{}")
                    if isinstance(parsed_cfg, dict):
                        config_obj = parsed_cfg
                except Exception:
                    config_obj = {}
                member_role_by_user_id = {
                    str(user_id): str(role or "").strip()
                    for user_id, role in self.ctx.db.execute(
                        select(ProjectMember.user_id, ProjectMember.role).where(
                            ProjectMember.workspace_id == str(workspace_id),
                            ProjectMember.project_id == str(project_id),
                        )
                    ).all()
                }
                team_agents = normalize_team_agents(config_obj.get("team"))
                agent_role_by_code = {
                    str(agent.get("id") or "").strip(): str(agent.get("authority_role") or "").strip()
                    for agent in team_agents
                    if str(agent.get("id") or "").strip()
                }
                default_kickoff_workflow_role = derive_task_role(
                    task_like={
                        "assignee_id": str(state_snapshot.get("assignee_id") or (task_view or {}).get("assignee_id") or "").strip(),
                        "assigned_agent_code": str(state_snapshot.get("assigned_agent_code") or (task_view or {}).get("assigned_agent_code") or "").strip(),
                        "labels": state_snapshot.get("labels") if state_snapshot.get("labels") is not None else (task_view or {}).get("labels"),
                        "status": str(state_snapshot.get("status") or (task_view or {}).get("status") or "").strip(),
                    },
                    member_role_by_user_id=member_role_by_user_id,
                    agent_role_by_code=agent_role_by_code,
                )
            if str(default_kickoff_workflow_role or "").strip() == "Lead" and _team_mode_project_is_unstarted(
                self.ctx.db,
                project_id=str(project_id),
                exclude_task_id=self.task_id,
            ):
                should_default_to_team_mode_kickoff = True
        if should_default_to_team_mode_kickoff:
            effective_instruction = f"Team Mode kickoff for project {project_id}. Dispatch-only run."
        effective_instruction = effective_instruction or fallback_instruction
        if not effective_instruction:
            raise HTTPException(status_code=422, detail="instruction is required")

        classification: dict[str, Any] = {
            "execution_intent": self.execution_intent,
            "execution_kickoff_intent": self.execution_kickoff_intent,
            "project_creation_intent": self.project_creation_intent,
            "project_knowledge_lookup_intent": False,
            "grounded_answer_required": False,
            "workflow_scope": str(self.workflow_scope or "").strip().lower() or None,
            "execution_mode": str(self.execution_mode or "").strip().lower() or None,
            "deploy_requested": None,
            "docker_compose_requested": None,
            "requested_port": None,
            "project_name_provided": None,
            "task_completion_requested": self.task_completion_requested,
            "reason": str(self.classifier_reason or "").strip(),
        }

        if requested_source in {"manual", "manual_stream"} and not should_default_to_team_mode_kickoff:
            classification = resolve_instruction_intent(
                instruction=effective_instruction,
                workspace_id=workspace_id,
                project_id=project_id,
                session_id=None,
                current=classification,
                classify_fn=classify_instruction_intent,
                required_fields=AUTOMATION_REQUEST_INTENT_FIELDS,
            )
        if should_default_to_team_mode_kickoff:
            classification = {
                **classification,
                "execution_intent": True,
                "execution_kickoff_intent": True,
                "project_creation_intent": bool(classification.get("project_creation_intent")),
                "workflow_scope": "team_mode",
                "execution_mode": "kickoff_only",
                "reason": str(classification.get("reason") or "").strip() or "Defaulted to kickoff for fresh Team Mode Lead run.",
            }

        if project_id:
            plugin_row = self.ctx.db.execute(
                select(ProjectPluginConfig.config_json).where(
                    ProjectPluginConfig.workspace_id == str(workspace_id),
                    ProjectPluginConfig.project_id == str(project_id),
                    ProjectPluginConfig.plugin_key == "team_mode",
                    ProjectPluginConfig.enabled == True,  # noqa: E712
                    ProjectPluginConfig.is_deleted == False,  # noqa: E712
                )
            ).first()
            if plugin_row is not None:
                config_obj: dict[str, object] = {}
                try:
                    parsed_cfg = json.loads(str(plugin_row[0] or "").strip() or "{}")
                    if isinstance(parsed_cfg, dict):
                        config_obj = parsed_cfg
                except Exception:
                    config_obj = {}
                member_role_by_user_id = {
                    str(user_id): str(role or "").strip()
                    for user_id, role in self.ctx.db.execute(
                        select(ProjectMember.user_id, ProjectMember.role).where(
                            ProjectMember.project_id == str(project_id),
                        )
                    ).all()
                }
                team_agents = normalize_team_agents(config_obj.get("team"))
                agent_role_by_code = {
                    str(agent.get("id") or "").strip(): str(agent.get("authority_role") or "").strip()
                    for agent in team_agents
                    if str(agent.get("id") or "").strip()
                }
                workflow_role = derive_task_role(
                    task_like={
                        "assignee_id": str(state_snapshot.get("assignee_id") or (task_view or {}).get("assignee_id") or "").strip(),
                        "assigned_agent_code": str(state_snapshot.get("assigned_agent_code") or (task_view or {}).get("assigned_agent_code") or "").strip(),
                        "labels": state_snapshot.get("labels") if state_snapshot.get("labels") is not None else (task_view or {}).get("labels"),
                        "status": str(state_snapshot.get("status") or (task_view or {}).get("status") or "").strip(),
                    },
                    member_role_by_user_id=member_role_by_user_id,
                    agent_role_by_code=agent_role_by_code,
                )
                if (
                    str(workflow_role or "").strip() in {"Developer", "QA"}
                    and requested_source in {"manual", "manual_stream"}
                ):
                    classification["execution_intent"] = True
                    classification["execution_kickoff_intent"] = False
                    classification["workflow_scope"] = "team_mode"
                    classification["execution_mode"] = "resume_execution"
                    requested_source = "runner_orchestrator"
                # Team Mode kickoff is Lead-only dispatch.
                # Non-Lead tasks can be queued by explicit Lead handoff/events, but never by kickoff instruction.
                if is_team_mode_kickoff_classification(classification) and str(workflow_role or "").strip() != "Lead":
                    return {
                        "ok": True,
                        "task_id": self.task_id,
                        "automation_state": current_automation_state or "idle",
                        "requested_at": requested_at,
                        "skipped": True,
                        "reason": (
                            "Team Mode kickoff dispatch is Lead-only; non-Lead tasks cannot be "
                            "queued with kickoff instruction."
                        ),
                    }
                topology_verification = _verify_team_mode_project_topology(
                    self.ctx.db,
                    workspace_id=str(workspace_id),
                    project_id=str(project_id),
                )
                if topology_verification is not None and not bool((topology_verification.get("ok") or False)):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Team Mode execution cannot continue because Team Mode project requirements are incomplete. "
                            "Ensure exactly one Lead, required semantic statuses, and a human owner are configured."
                        ),
                    )
                if str(workflow_role or "").strip() == "QA":
                    existing_lead_handoff = bool(str(state_snapshot.get("last_lead_handoff_token") or "").strip())
                    valid_lead_handoff = (
                        requested_source == "lead_handoff"
                        and bool(str(requested_source_task_id or "").strip())
                    )
                    if not valid_lead_handoff and not existing_lead_handoff:
                        return {
                            "ok": True,
                            "task_id": self.task_id,
                            "automation_state": current_automation_state or "idle",
                            "requested_at": requested_at,
                            "skipped": True,
                            "reason": (
                                "Team Mode QA automation requires an explicit Lead handoff with source_task_id. "
                            "Manual or orchestrator QA queueing is not allowed."
                        ),
                    }
                    if existing_lead_handoff and requested_source in {"manual", "manual_stream"}:
                        requested_source = "lead_handoff"
                if (
                    str(workflow_role or "").strip() in {"Developer", "Lead", "QA"}
                    and not is_team_mode_kickoff_classification(classification)
                ):
                    classification["workflow_scope"] = "team_mode"
                    if not str(classification.get("execution_mode") or "").strip():
                        classification["execution_mode"] = "resume_execution"
                    dependency_ready, dependency_reason = _team_mode_task_dependency_ready(
                        db=self.ctx.db,
                        workspace_id=str(workspace_id),
                        project_id=str(project_id),
                        task_id=self.task_id,
                        state=state_snapshot,
                    )
                    if not dependency_ready:
                        return {
                            "ok": True,
                            "task_id": self.task_id,
                            "automation_state": current_automation_state or "idle",
                            "requested_at": requested_at,
                            "skipped": True,
                            "reason": (
                                "Team Mode execution is waiting for structural dependencies. "
                                + str(dependency_reason or "Dependency requirements are not satisfied.")
                            ),
                        }
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.request_automation(
            requested_at=requested_at,
            instruction=effective_instruction,
            source=requested_source,
            source_task_id=requested_source_task_id,
            chat_session_id=str(self.chat_session_id or "").strip() or None,
            execution_intent=bool(classification.get("execution_intent")),
            execution_kickoff_intent=bool(classification.get("execution_kickoff_intent")),
            project_creation_intent=bool(classification.get("project_creation_intent")),
            workflow_scope=str(classification.get("workflow_scope") or "").strip() or None,
            execution_mode=str(classification.get("execution_mode") or "").strip() or None,
            task_completion_requested=bool(classification.get("task_completion_requested")),
            classifier_reason=str(classification.get("reason") or "").strip() or None,
        )
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        if self.wake_runner:
            try:
                from features.agents.runner import start_automation_runner, wake_automation_runner

                start_automation_runner()
                wake_automation_runner()
            except Exception:
                # Runner wake-up/start is best-effort; polling loop remains fallback.
                pass
        return {"ok": True, "task_id": self.task_id, "automation_state": "queued", "requested_at": requested_at}
