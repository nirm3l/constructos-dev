from __future__ import annotations

import json
import logging
import os
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
    canonicalize_role,
    derive_task_role,
    ensure_team_mode_labels,
    normalize_team_agents,
)
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
from features.notifications.domain import NotificationAggregate
from .domain import TaskAggregate

MENTION_PATTERN = re.compile(r"@([A-Za-z0-9_\-]+)")
_UNSET = object()
_LOG = logging.getLogger(__name__)
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_DEFAULT_CODEX_WORKDIR = "/home/app/workspace"


def _slugify(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or fallback


def _resolve_workspace_root() -> Path:
    raw = str(os.getenv("AGENT_CODEX_WORKDIR", _DEFAULT_CODEX_WORKDIR)).strip() or _DEFAULT_CODEX_WORKDIR
    path = Path(raw).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


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
    workspace_root = _resolve_workspace_root()
    project_slug = _slugify(project_name, fallback="project")
    repo_root = workspace_root / project_slug
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
    if not normalized_assignee_id:
        return ensure_team_mode_labels(labels=list(labels or []), role=None, agent_slot=None), None
    if not normalized_assigned_agent_code:
        return ensure_team_mode_labels(labels=list(labels or []), role=None, agent_slot=None), None
    valid_codes = {str(item.get("id") or "").strip() for item in agents if str(item.get("id") or "").strip()}
    selected_slot = normalized_assigned_agent_code if normalized_assigned_agent_code in valid_codes else None
    return (
        ensure_team_mode_labels(
            labels=list(labels or []),
            role=None,
            agent_slot=None,
        ),
        selected_slot,
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


def _is_team_mode_transition_allowed(
    *,
    workflow: dict[str, object],
    from_status: str,
    to_status: str,
    actor_role: str | None,
) -> tuple[bool, str]:
    if from_status == to_status:
        return True, "noop"
    statuses_raw = workflow.get("statuses")
    statuses = [str(item or "").strip() for item in statuses_raw] if isinstance(statuses_raw, list) else []
    statuses = [item for item in statuses if item]
    if statuses and to_status not in set(statuses):
        return False, "target_status_not_allowed"

    transitions_raw = workflow.get("transitions")
    transitions = transitions_raw if isinstance(transitions_raw, list) else []
    if not transitions:
        return False, "no_transitions_declared"

    normalized_actor_role = canonicalize_role(actor_role)
    if not normalized_actor_role:
        return False, "actor_role_missing"

    for item in transitions:
        if not isinstance(item, dict):
            continue
        transition_from = str(item.get("from") or "").strip()
        transition_to = str(item.get("to") or "").strip()
        if transition_from != from_status or transition_to != to_status:
            continue
        allowed_roles_raw = item.get("allowed_roles")
        allowed_roles = (
            {str(role or "").strip() for role in allowed_roles_raw if str(role or "").strip()}
            if isinstance(allowed_roles_raw, list)
            else set()
        )
        if "*" in allowed_roles or normalized_actor_role in allowed_roles:
            return True, "allowed"
        return False, "actor_role_not_permitted"

    return False, "transition_not_declared"


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
    workflow = config.get("workflow")
    if not isinstance(workflow, dict):
        workflow = {}
    actor_role = db.execute(
        select(ProjectMember.role).where(
            ProjectMember.project_id == normalized_project_id,
            ProjectMember.user_id == str(actor_user_id),
        )
    ).scalar_one_or_none()
    normalized_actor_role = str(actor_role or "").strip()
    if not normalized_actor_role and task_id:
        task_row = db.execute(
            select(Task.assignee_id, Task.status, Task.labels).where(
                Task.id == str(task_id),
                Task.project_id == normalized_project_id,
                Task.is_deleted == False,  # noqa: E712
            )
        ).first()
        if task_row is not None:
            assignee_id, task_status, task_labels = task_row
            if str(assignee_id or "").strip() == str(actor_user_id):
                normalized_actor_role = derive_task_role(
                    task_like={
                        "assignee_id": str(assignee_id or "").strip(),
                        "labels": task_labels,
                        "status": str(task_status or "").strip(),
                    },
                    member_role_by_user_id={},
                )
    allowed, reason_code = _is_team_mode_transition_allowed(
        workflow=workflow,
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
        "status": getattr(aggregate, "status", "To do"),
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
        if assigned_agent_code and not assignee_id:
            raise HTTPException(status_code=422, detail="assigned_agent_code requires assignee_id")

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
        requested_status = str(self.payload.status or "").strip()
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
        normalized_instruction, normalized_triggers = _with_legacy_schedule_overrides(
            instruction=self.payload.instruction,
            execution_triggers=self.payload.execution_triggers,
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
        if current_row is None and get_kurrent_client() is not None:
            current_state, _ = rebuild_state(self.ctx.db, "Task", self.task_id)
        if current_row is None and not current_state:
            raise HTTPException(status_code=404, detail="Task not found")

        current_task_type = (
            (current_row.task_type if current_row is not None else None)
            or (str(current_state.get("task_type")) if current_state else None)
            or "manual"
        )
        current_status = (
            str(current_row.status or "").strip()
            if current_row is not None
            else str((current_state or {}).get("status") or "").strip()
        )
        current_instruction = _normalize_instruction(
            (current_row.instruction if current_row is not None else (current_state.get("instruction") if current_state else None))
            or (current_row.scheduled_instruction if current_row is not None else (current_state.get("scheduled_instruction") if current_state else None))
        )
        current_scheduled_instruction = (
            current_row.scheduled_instruction if current_row is not None else (current_state.get("scheduled_instruction") if current_state else None)
        )
        current_scheduled_at_utc = (
            to_iso_utc(current_row.scheduled_at_utc)
            if current_row is not None
            else (current_state.get("scheduled_at_utc") if current_state else None)
        )
        current_schedule_timezone = (
            current_row.schedule_timezone if current_row is not None else (current_state.get("schedule_timezone") if current_state else None)
        )
        current_recurring_rule = (
            current_row.recurring_rule if current_row is not None else (current_state.get("recurring_rule") if current_state else None)
        )
        current_schedule_state = (
            current_row.schedule_state if current_row is not None else (current_state.get("schedule_state") if current_state else "idle")
        )
        current_execution_triggers = normalize_execution_triggers(
            current_row.execution_triggers if current_row is not None else (current_state.get("execution_triggers") if current_state else [])
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
            current_row.specification_id if current_row is not None else (current_state.get("specification_id") if current_state else None)
        )
        current_task_group_id = (
            current_row.task_group_id if current_row is not None else (current_state.get("task_group_id") if current_state else None)
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
            data["assigned_agent_code"] = _normalize_assigned_agent_code_for_project(
                self.ctx.db,
                workspace_id=workspace_id,
                project_id=effective_project_id,
                assigned_agent_code=data.get("assigned_agent_code"),
            )
        event_payload = dict(data)
        existing_labels: list[str] = []
        raw_existing_labels = (
            current_row.labels if current_row is not None else (current_state.get("labels") if current_state else [])
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
            else (current_row.assignee_id if current_row is not None else (current_state.get("assignee_id") if current_state else ""))
            or ""
        ).strip() or None
        effective_assigned_agent_code = str(
            event_payload.get("assigned_agent_code")
            if "assigned_agent_code" in event_payload
            else (
                current_row.assigned_agent_code
                if current_row is not None
                else (current_state.get("assigned_agent_code") if current_state else "")
            )
            or ""
        ).strip() or None
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
        event_payload["task_type"] = str(legacy_schedule.get("task_type") or "manual")
        event_payload["scheduled_instruction"] = legacy_schedule.get("scheduled_instruction")
        event_payload["scheduled_at_utc"] = legacy_schedule.get("scheduled_at_utc")
        event_payload["schedule_timezone"] = legacy_schedule.get("schedule_timezone")
        event_payload["recurring_rule"] = legacy_schedule.get("recurring_rule")

        automation_config_fields = {
            "instruction",
            "execution_triggers",
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
        if status == "Done":
            task_view = load_task_view(self.ctx.db, self.task_id)
            if task_view is None:
                raise HTTPException(status_code=404, detail="Task not found")
            return task_view
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.complete(completed_at=to_iso_utc(datetime.now(timezone.utc)))
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
class ReopenTaskHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, status, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        if status != "Done":
            task_view = load_task_view(self.ctx.db, self.task_id)
            if task_view is None:
                raise HTTPException(status_code=404, detail="Task not found")
            return task_view
        reopen_status = "To do"
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
        if self.payload.action == "complete":
            if status == "Done":
                return False
            _enforce_team_mode_transition_policy(
                db=self.ctx.db,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=str(self.ctx.user.id),
                from_status=str(status or "").strip(),
                to_status="Done",
                task_id=task_id,
            )
            aggregate.complete(completed_at=to_iso_utc(datetime.now(timezone.utc)))
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
            if status != "Done":
                return False
            reopen_status = str(self.payload.payload.get("status", "To do") or "").strip() or "To do"
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
    wake_runner: bool = True

    def __call__(self) -> dict:
        workspace_id, project_id, _, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        requested_at = to_iso_utc(datetime.now(timezone.utc))
        task_view = load_task_view(self.ctx.db, self.task_id)
        fallback_instruction = _normalize_instruction(task_view.get("instruction") if task_view else None)
        effective_instruction = _normalize_instruction(self.instruction) or fallback_instruction
        if not effective_instruction:
            raise HTTPException(status_code=422, detail="instruction is required")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.request_automation(
            requested_at=requested_at,
            instruction=effective_instruction,
            source="manual",
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
