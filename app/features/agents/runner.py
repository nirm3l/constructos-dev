from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from datetime import datetime, timezone
import re
import tomllib

from sqlalchemy import select

from plugins import executor_policy as plugin_executor_policy
from plugins.runner_policy import (
    blocker_escalation_notification,
    is_agent_project_role,
    is_blocker_source_role,
    is_developer_role,
    is_lead_role,
    is_qa_role,
    is_recurring_oversight_task,
    lead_role_for_escalation,
    normalize_success_outcome,
    success_validation_error,
    preflight_error as plugin_preflight_error,
)
from features.agents.intent_classifier import is_team_mode_kickoff_classification
from plugins.team_mode.task_roles import (
    canonicalize_role,
    derive_task_role,
    normalize_team_agents,
    parse_labels,
    pick_agent_for_task,
)
from plugins.team_mode.state_machine import evaluate_team_mode_transition
from plugins.team_mode.workflow_orchestrator import (
    TEAM_MODE_WORKFLOW_ROLES,
    plan_next_runnable_tasks,
    plan_team_mode_dispatch,
)
from .executor import AutomationOutcome, build_automation_usage_metadata, execute_task_automation_stream
from .service import AgentTaskService
from .gates import run_runtime_deploy_health_check
from features.tasks.domain import (
    EVENT_UPDATED as TASK_EVENT_UPDATED,
    EVENT_COMPLETED as TASK_EVENT_COMPLETED,
    EVENT_AUTOMATION_COMPLETED,
    EVENT_AUTOMATION_REQUESTED,
    EVENT_AUTOMATION_FAILED,
    EVENT_AUTOMATION_STARTED,
    EVENT_COMMENT_ADDED,
    EVENT_SCHEDULE_COMPLETED,
    EVENT_SCHEDULE_FAILED,
    EVENT_SCHEDULE_QUEUED,
    EVENT_SCHEDULE_STARTED,
)
from shared.contracts import ConcurrencyConflictError
from shared.eventing import append_event, rebuild_state
from shared.models import Note, Project, ProjectMember, ProjectPluginConfig, ProjectRule, SessionLocal, Task, User as UserModel
from shared.serializers import to_iso_utc
from shared.typed_notifications import append_notification_created_event
from shared.project_repository import (
    find_project_compose_manifest,
    resolve_project_repository_path,
    resolve_task_branch_name,
    resolve_task_worktree_path,
)
from shared.settings import (
    AGENT_EXECUTOR_TIMEOUT_SECONDS,
    AGENT_RUNNER_ENABLED,
    AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS,
    AGENT_RUNNER_INTERVAL_SECONDS,
    AGENT_RUNNER_MAX_CONCURRENCY,
    AGENT_SYSTEM_USER_ID,
    MCP_AUTH_TOKEN,
    logger,
)
from shared.task_automation import (
    STATUS_MATCH_ALL,
    STATUS_SCOPE_EXTERNAL,
    TRIGGER_KIND_STATUS_CHANGE,
    first_enabled_schedule_trigger,
    normalize_execution_triggers,
    parse_schedule_due_at,
    rearm_first_schedule_trigger,
    selector_matches_task,
    schedule_trigger_matches_status,
)
from shared.task_relationships import normalize_task_relationships

_runner_stop_event = threading.Event()
_runner_wakeup_event = threading.Event()
_runner_thread: threading.Thread | None = None
_COMMIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
_COMMIT_SHA_EXPLICIT_RE = re.compile(
    r"(?i)(?:\b(?:commit|sha|changeset|hash)\s*[:=#]?\s*|/commit/)([0-9a-f]{7,40})\b"
)
_TASK_BRANCH_RE = re.compile(r"\btask/[a-z0-9][a-z0-9._/-]*\b", re.IGNORECASE)
_TRANSIENT_INTERRUPT_RE = re.compile(r"(?:exit=-15|sigterm|terminated by signal 15)", re.IGNORECASE)
_RECOVERABLE_FAILURE_RE = re.compile(
    r"(?:exit=-15|sigterm|terminated by signal 15|timeout|timed out|429|rate limit|502|503|504|bad gateway|gateway timeout|temporarily unavailable|connection reset)",
    re.IGNORECASE,
)
_MAX_RECOVERABLE_RETRIES = 3
_KICKOFF_EXECUTION_HOLDOFF_SECONDS = 20
_AUTOMATION_STREAM_PROGRESS_MAX_CHARS = 24000
_AUTOMATION_STREAM_FLUSH_INTERVAL_SECONDS = 0.35
_AUTOMATION_STREAM_NOISY_STATUS_MESSAGES = {
    "Codex started processing the request.",
    "Reasoning step completed.",
}
_STATUS_CHANGE_AUTOMATION_ACTIONS = {
    "automation",
    "execute_instruction",
    "queue",
    "queue_automation",
    "queue_instruction",
    "request_automation",
    "request_instruction",
    "run",
    "run_automation",
    "run_instruction",
    "run_task_instruction",
    "start_automation",
    "start_instruction",
    "trigger_automation",
    "trigger_instruction",
}
_AUTOMATION_BLOCKED_MARKER = "BLOCKED"
_TEAM_MODE_QA_LEAD_HANDOFF_GATED_FRAGMENT = "qa automation is gated until lead handoff is complete"
_TEAM_MODE_QA_CURRENT_DEPLOY_CYCLE_GATED_FRAGMENT = "qa automation is gated until lead handoff is complete for the current deploy cycle"
_TEAM_MODE_LEAD_MERGE_READY_GATED_FRAGMENT = "lead automation is gated until merge-ready developer output exists"
_MERGE_TO_MAIN_REF_PREFIX = "merge:main:"
_DEPLOY_STACK_REF_PREFIX = "deploy:stack:"
_DEPLOY_COMMAND_REF_PREFIX = "deploy:command:"
_DEPLOY_HEALTH_REF_PREFIX = "deploy:health:"
_DEPLOY_COMPOSE_REF_PREFIX = "deploy:compose:"
_DEPLOY_RUNTIME_REF_PREFIX = "deploy:runtime:"


def execute_task_automation(**kwargs):
    return execute_task_automation_stream(**kwargs)


@dataclass(frozen=True, slots=True)
class QueuedAutomationRun:
    task_id: str
    workspace_id: str
    project_id: str | None
    title: str
    description: str
    status: str
    instruction: str
    request_source: str
    is_scheduled_run: bool
    trigger_task_id: str | None
    trigger_from_status: str | None
    trigger_to_status: str | None
    triggered_at: str | None
    actor_user_id: str
    execution_kickoff_intent: bool = False
    workflow_scope: str | None = None
    execution_mode: str | None = None
    task_completion_requested: bool = False


def _request_classification_from_state(state: dict[str, object] | None) -> dict[str, object]:
    source = dict(state or {})
    return {
        "execution_kickoff_intent": bool(source.get("last_requested_execution_kickoff_intent")),
        "workflow_scope": str(source.get("last_requested_workflow_scope") or "").strip().lower() or None,
        "execution_mode": str(source.get("last_requested_execution_mode") or "").strip().lower() or None,
    }


def _is_classified_team_mode_kickoff(
    *,
    state: dict[str, object] | None = None,
    run: QueuedAutomationRun | None = None,
) -> bool:
    classification = _request_classification_from_state(state)
    if run is not None:
        if not classification.get("workflow_scope"):
            classification["workflow_scope"] = str(run.workflow_scope or "").strip().lower() or None
        if not classification.get("execution_mode"):
            classification["execution_mode"] = str(run.execution_mode or "").strip().lower() or None
        if not bool(classification.get("execution_kickoff_intent")):
            classification["execution_kickoff_intent"] = bool(run.execution_kickoff_intent)
    return is_team_mode_kickoff_classification(classification)


def _parse_iso_utc(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        candidate = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(candidate)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _normalize_nonnegative_int(value) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 0
    return max(0, parsed)


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _parse_iso_timestamp(value: object) -> datetime | None:
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


def _project_has_git_delivery_skill(*, db, workspace_id: str, project_id: str | None) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return False
    row = db.execute(
        select(ProjectPluginConfig.id).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "git_delivery",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    return row is not None


def _project_git_delivery_require_dev_tests(*, db, workspace_id: str, project_id: str | None) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return False
    row = db.execute(
        select(ProjectPluginConfig.compiled_policy_json, ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "git_delivery",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        return False
    compiled_raw = str(row[0] or "").strip()
    config_raw = str(row[1] or "").strip()
    try:
        compiled = json.loads(compiled_raw or "{}")
    except Exception:
        compiled = {}
    if isinstance(compiled, dict):
        execution = compiled.get("execution")
        if isinstance(execution, dict) and isinstance(execution.get("require_dev_tests"), bool):
            return bool(execution.get("require_dev_tests"))
    try:
        config = json.loads(config_raw or "{}")
    except Exception:
        config = {}
    if isinstance(config, dict):
        execution = config.get("execution")
        if isinstance(execution, dict) and isinstance(execution.get("require_dev_tests"), bool):
            return bool(execution.get("require_dev_tests"))
    return False


def _project_git_delivery_require_nontrivial_dev_changes(*, db, workspace_id: str, project_id: str | None) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return True
    row = db.execute(
        select(ProjectPluginConfig.compiled_policy_json, ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "git_delivery",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        return True
    compiled_raw = str(row[0] or "").strip()
    config_raw = str(row[1] or "").strip()
    try:
        compiled = json.loads(compiled_raw or "{}")
    except Exception:
        compiled = {}
    if isinstance(compiled, dict):
        execution = compiled.get("execution")
        if isinstance(execution, dict) and isinstance(execution.get("require_nontrivial_dev_changes"), bool):
            return bool(execution.get("require_nontrivial_dev_changes"))
    try:
        config = json.loads(config_raw or "{}")
    except Exception:
        config = {}
    if isinstance(config, dict):
        execution = config.get("execution")
        if isinstance(execution, dict) and isinstance(execution.get("require_nontrivial_dev_changes"), bool):
            return bool(execution.get("require_nontrivial_dev_changes"))
    return True


def _project_has_team_mode_skill(*, db, workspace_id: str, project_id: str | None) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return False
    row = db.execute(
        select(ProjectPluginConfig.id).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    return row is not None


def _project_team_mode_execution_enabled(*, db, workspace_id: str, project_id: str | None) -> bool:
    return _project_has_team_mode_skill(db=db, workspace_id=workspace_id, project_id=project_id)


def _project_requires_runtime_deploy_health(*, db, workspace_id: str, project_id: str | None) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return False
    row = db.execute(
        select(ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "docker_compose",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    try:
        config = json.loads(str(row or "").strip() or "{}")
    except Exception:
        config = {}
    if not isinstance(config, dict):
        return False
    runtime_cfg = config.get("runtime_deploy_health")
    if not isinstance(runtime_cfg, dict):
        return False
    return bool(runtime_cfg.get("required"))


def _project_runtime_deploy_target(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
) -> tuple[str, int | None, str, bool]:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return "constructos-ws-default", None, "/health", False
    row = db.execute(
        select(ProjectPluginConfig.compiled_policy_json, ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "docker_compose",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        return "constructos-ws-default", None, "/health", False
    compiled_raw = str(row[0] or "").strip()
    config_raw = str(row[1] or "").strip()
    try:
        compiled = json.loads(compiled_raw or "{}")
    except Exception:
        compiled = {}
    try:
        config = json.loads(config_raw or "{}")
    except Exception:
        config = {}
    runtime_cfg: dict[str, object] = {}
    if isinstance(compiled, dict) and isinstance(compiled.get("runtime_deploy_health"), dict):
        runtime_cfg = dict(compiled.get("runtime_deploy_health") or {})
    elif isinstance(config, dict) and isinstance(config.get("runtime_deploy_health"), dict):
        runtime_cfg = dict(config.get("runtime_deploy_health") or {})
    stack = str(runtime_cfg.get("stack") or "constructos-ws-default").strip() or "constructos-ws-default"
    port_raw = runtime_cfg.get("port")
    try:
        port = int(port_raw) if port_raw is not None else None
    except Exception:
        port = None
    health_path = str(runtime_cfg.get("health_path") or "/health").strip() or "/health"
    if not health_path.startswith("/"):
        health_path = f"/{health_path}"
    required = bool(runtime_cfg.get("required"))
    return stack, port, health_path, required


def _project_has_compose_manifest(*, project_name: str | None, project_id: str | None) -> bool:
    manifest = find_project_compose_manifest(project_name=project_name, project_id=project_id)
    return manifest is not None


def _project_has_repo_context(*, db, workspace_id: str, project_id: str | None) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return False
    project = db.get(Project, normalized_project_id)
    if project is None or bool(getattr(project, "is_deleted", False)):
        return False
    project_rules = db.execute(
        select(ProjectRule).where(
            ProjectRule.workspace_id == workspace_id,
            ProjectRule.project_id == normalized_project_id,
            ProjectRule.is_deleted == False,  # noqa: E712
        )
    ).scalars().all()
    return AgentTaskService._project_has_repo_context(
        project_description=str(getattr(project, "description", "") or ""),
        project_external_refs=getattr(project, "external_refs", "[]"),
        project_rules=project_rules,
    )


def _resolve_task_actor_user_id(
    *,
    db,
    task_id: str,
    state: dict | None = None,
    fallback_actor_user_id: str | None = None,
) -> str:
    source_state = dict(state or {})
    assignee_id = str(source_state.get("assignee_id") or "").strip()
    workspace_id = str(source_state.get("workspace_id") or "").strip()
    project_id = str(source_state.get("project_id") or "").strip()
    if not assignee_id:
        task_row = db.get(Task, task_id)
        if task_row is not None:
            assignee_id = str(task_row.assignee_id or "").strip()
            if not workspace_id:
                workspace_id = str(task_row.workspace_id or "").strip()
            if not project_id:
                project_id = str(task_row.project_id or "").strip()
    if not assignee_id:
        return str(fallback_actor_user_id or "").strip() or AGENT_SYSTEM_USER_ID

    def _resolve_team_mode_executor_user_id() -> str | None:
        if not workspace_id or not project_id:
            return None
        config_row = db.execute(
            select(ProjectPluginConfig.config_json).where(
                ProjectPluginConfig.workspace_id == workspace_id,
                ProjectPluginConfig.project_id == project_id,
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
            return None
        if not isinstance(config_obj, dict):
            return None
        agents = normalize_team_agents(config_obj.get("team"))
        if not agents:
            return None
        membership_roles = {
            str(user_id): canonicalize_role(role)
            for user_id, role in db.execute(
                select(ProjectMember.user_id, ProjectMember.role).where(
                    ProjectMember.workspace_id == workspace_id,
                    ProjectMember.project_id == project_id,
                )
            ).all()
        }
        task_like = {
            "id": task_id,
            "assignee_id": assignee_id,
            "assigned_agent_code": str(source_state.get("assigned_agent_code") or "").strip(),
            "labels": source_state.get("labels"),
            "status": source_state.get("status"),
        }
        selected_agent = pick_agent_for_task(
            agents=agents,
            task_like=task_like,
            member_role_by_user_id=membership_roles,
        )
        if not selected_agent:
            return None
        executor_user_id = str(selected_agent.get("executor_user_id") or "").strip()
        if not executor_user_id:
            return None
        executor_user = db.get(UserModel, executor_user_id)
        if executor_user is None or not bool(executor_user.is_active):
            return None
        if str(executor_user.user_type or "").strip().lower() != "agent":
            return None
        return executor_user_id

    team_mode_executor_user_id = _resolve_team_mode_executor_user_id()
    if team_mode_executor_user_id:
        return team_mode_executor_user_id

    user_row = db.get(UserModel, assignee_id)
    if user_row is None or not bool(user_row.is_active):
        return str(fallback_actor_user_id or "").strip() or AGENT_SYSTEM_USER_ID
    if str(user_row.user_type or "").strip().lower() != "agent":
        return str(fallback_actor_user_id or "").strip() or AGENT_SYSTEM_USER_ID

    declared_task_role = derive_task_role(
        task_like={
            "assignee_id": assignee_id,
            "assigned_agent_code": str(source_state.get("assigned_agent_code") or "").strip(),
            "labels": source_state.get("labels"),
            "status": source_state.get("status"),
        },
        member_role_by_user_id={},
    )
    if project_id:
        membership = db.execute(
            select(ProjectMember).where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == assignee_id,
            )
        ).scalar_one_or_none()
        if membership is None and not is_agent_project_role(declared_task_role):
            return str(fallback_actor_user_id or "").strip() or AGENT_SYSTEM_USER_ID
        project_role = canonicalize_role(membership.role if membership is not None else "")
        effective_role = project_role if is_agent_project_role(project_role) else declared_task_role
        if not is_agent_project_role(effective_role):
            return str(fallback_actor_user_id or "").strip() or AGENT_SYSTEM_USER_ID
    return assignee_id


def _resolve_assignee_project_role(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    assignee_id: str,
    assigned_agent_code: str | None = None,
    task_labels: object | None = None,
    task_status: str | None = None,
) -> str:
    normalized_project_id = str(project_id or "").strip()
    normalized_assignee_id = str(assignee_id or "").strip()
    normalized_assigned_agent_code = str(assigned_agent_code or "").strip().lower()
    if not workspace_id or not normalized_project_id or not normalized_assignee_id:
        return ""
    if normalized_assigned_agent_code:
        plugin_row = db.execute(
            select(ProjectPluginConfig.config_json).where(
                ProjectPluginConfig.workspace_id == workspace_id,
                ProjectPluginConfig.project_id == normalized_project_id,
                ProjectPluginConfig.plugin_key == "team_mode",
                ProjectPluginConfig.is_deleted == False,  # noqa: E712
            )
        ).scalar_one_or_none()
        plugin_config: dict[str, object] = {}
        if isinstance(plugin_row, dict):
            plugin_config = dict(plugin_row)
        elif isinstance(plugin_row, str) and plugin_row.strip():
            try:
                parsed = json.loads(plugin_row)
            except Exception:
                parsed = {}
            if isinstance(parsed, dict):
                plugin_config = parsed
        team_agents = normalize_team_agents(plugin_config.get("team", {}))
        for agent in team_agents:
            if str(agent.get("id") or "").strip().lower() != normalized_assigned_agent_code:
                continue
            agent_role = canonicalize_role(agent.get("authority_role"))
            if agent_role:
                return agent_role
    declared = derive_task_role(
        task_like={
            "assignee_id": normalized_assignee_id,
            "assigned_agent_code": normalized_assigned_agent_code,
            "labels": task_labels,
            "status": str(task_status or "").strip(),
        },
        member_role_by_user_id={},
        allow_status_fallback=False,
    )
    if declared:
        return declared
    role = db.execute(
        select(ProjectMember.role).where(
            ProjectMember.workspace_id == workspace_id,
            ProjectMember.project_id == normalized_project_id,
            ProjectMember.user_id == normalized_assignee_id,
        )
    ).scalar_one_or_none()
    return canonicalize_role(role)


def _resolve_member_project_role(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    user_id: str | None,
) -> str:
    normalized_project_id = str(project_id or "").strip()
    normalized_user_id = str(user_id or "").strip()
    if not workspace_id or not normalized_project_id or not normalized_user_id:
        return ""
    role = db.execute(
        select(ProjectMember.role).where(
            ProjectMember.workspace_id == workspace_id,
            ProjectMember.project_id == normalized_project_id,
            ProjectMember.user_id == normalized_user_id,
        )
    ).scalar_one_or_none()
    return canonicalize_role(role)


def _task_uses_shared_project_workspace(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    task_status: str | None,
    task_assignee_id: str | None,
    task_assigned_agent_code: str | None,
    task_labels: object | None,
    actor_user_id: str | None,
) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return False
    git_delivery_enabled = _project_has_git_delivery_skill(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    if not git_delivery_enabled:
        return False
    team_mode_enabled = _project_has_team_mode_skill(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    assignee_role = _resolve_assignee_project_role(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        assignee_id=str(task_assignee_id or ""),
        assigned_agent_code=str(task_assigned_agent_code or ""),
        task_labels=task_labels,
        task_status=str(task_status or ""),
    )
    actor_role = _resolve_member_project_role(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        user_id=actor_user_id,
    )
    uses_isolated_worktree = plugin_executor_policy.should_prepare_task_worktree(
        plugin_enabled=team_mode_enabled,
        git_delivery_enabled=git_delivery_enabled,
        task_status=str(task_status or "").strip(),
        actor_project_role=actor_role,
        assignee_project_role=assignee_role,
    )
    return not bool(uses_isolated_worktree)


def _project_has_running_automation(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    exclude_task_id: str | None = None,
) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return False
    excluded = str(exclude_task_id or "").strip()
    task_ids = [
        str(item or "").strip()
        for item in db.execute(
            select(Task.id).where(
                Task.workspace_id == workspace_id,
                Task.project_id == normalized_project_id,
                Task.is_deleted == False,  # noqa: E712
                Task.archived == False,  # noqa: E712
            )
        ).scalars().all()
        if str(item or "").strip()
    ]
    for task_id in task_ids:
        if excluded and task_id == excluded:
            continue
        state, _ = rebuild_state(db, "Task", task_id)
        if str(state.get("automation_state") or "idle").strip().lower() == "running":
            return True
    return False


def _project_running_automation_count(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    exclude_task_id: str | None = None,
) -> int:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return 0
    excluded = str(exclude_task_id or "").strip()
    task_ids = [
        str(item or "").strip()
        for item in db.execute(
            select(Task.id).where(
                Task.workspace_id == workspace_id,
                Task.project_id == normalized_project_id,
                Task.is_deleted == False,  # noqa: E712
                Task.archived == False,  # noqa: E712
            )
        ).scalars().all()
        if str(item or "").strip()
    ]
    running = 0
    for task_id in task_ids:
        if excluded and task_id == excluded:
            continue
        state, _ = rebuild_state(db, "Task", task_id)
        if str(state.get("automation_state") or "idle").strip().lower() == "running":
            running += 1
    return running


def _project_automation_parallel_limit(
    *,
    db,
    project_id: str | None,
) -> int:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return 4
    project = db.get(Project, normalized_project_id)
    if project is None:
        return 4
    try:
        value = int(getattr(project, "automation_max_parallel_tasks", 4) or 4)
    except Exception:
        value = 4
    return max(1, value)


def _build_team_mode_dispatch_candidates(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    exclude_task_ids: set[str] | None = None,
) -> tuple[list[dict[str, object]], dict[str, tuple[Task, dict[str, object], str]]]:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return [], []
    excluded_task_ids = {str(item or "").strip() for item in (exclude_task_ids or set()) if str(item or "").strip()}

    membership_roles = {
        str(user_id): canonicalize_role(role)
        for user_id, role in db.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == normalized_project_id,
            )
        ).all()
    }
    team_mode_row = db.execute(
        select(ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    config_obj: dict[str, object] = {}
    if team_mode_row:
        try:
            parsed = json.loads(str(team_mode_row or "").strip() or "{}")
            if isinstance(parsed, dict):
                config_obj = parsed
        except Exception:
            config_obj = {}
    team_agents = normalize_team_agents(config_obj.get("team"))
    developer_slot_ids = [
        str(agent.get("id") or "").strip()
        for agent in team_agents
        if str(agent.get("authority_role") or "").strip() == "Developer"
        and str(agent.get("id") or "").strip()
    ]

    tasks = db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.project_id == normalized_project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        ).order_by(Task.created_at.asc())
    ).scalars().all()

    from features.tasks.application import TaskApplicationService
    from shared.core import TaskAutomationRun

    now_utc = datetime.now(timezone.utc)
    dispatch_candidates: list[dict[str, object]] = []
    candidate_map: dict[str, tuple[Task, dict[str, object], str]] = {}
    for task in tasks:
        task_id = str(task.id or "").strip()
        if not task_id or task_id in excluded_task_ids:
            continue
        state, _ = rebuild_state(db, "Task", task_id)
        status = str(state.get("status") or getattr(task, "status", "") or "").strip()
        role = _resolve_assignee_project_role(
            db=db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            assignee_id=str(state.get("assignee_id") or getattr(task, "assignee_id", "") or ""),
            assigned_agent_code=str(state.get("assigned_agent_code") or getattr(task, "assigned_agent_code", "") or ""),
            task_labels=state.get("labels") if state.get("labels") is not None else getattr(task, "labels", None),
            task_status=status,
        )
        assigned_slot = str(state.get("assigned_agent_code") or getattr(task, "assigned_agent_code", "") or "").strip()
        automation_state = str(state.get("automation_state") or "idle").strip().lower()
        instruction = (
            str(state.get("instruction") or "").strip()
            or str(state.get("scheduled_instruction") or "").strip()
        )
        target_slot = assigned_slot
        if not target_slot and developer_slot_ids:
            selected_agent = pick_agent_for_task(
                agents=team_agents,
                task_like={
                    "id": task_id,
                    "assignee_id": str(state.get("assignee_id") or getattr(task, "assignee_id", "") or ""),
                    "assigned_agent_code": assigned_slot,
                    "labels": state.get("labels") if state.get("labels") is not None else getattr(task, "labels", None),
                    "status": status,
                },
                member_role_by_user_id=membership_roles,
            )
            target_slot = str((selected_agent or {}).get("id") or "").strip()
        dependency_ready, dependency_reason = _team_mode_dispatch_dependency_ready(
            db=db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            task_id=task_id,
            state=state,
        )
        has_lead_handoff = bool(str(state.get("last_lead_handoff_token") or "").strip())
        qa_handoff_gate = _current_nonblocking_gate_key(
            db=db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            assignee_role=role,
            task_status=status,
            task_state=state,
        )
        dispatch_ready = bool(
            instruction
            and dependency_ready
            and (
                (is_developer_role(role) and status == "Dev")
                or (is_qa_role(role) and status == "QA" and has_lead_handoff and not qa_handoff_gate)
                or (
                    is_lead_role(role)
                    and status == "Lead"
                    and not is_recurring_oversight_task(state)
                )
            )
        )
        dispatch_candidates.append(
            {
                "id": task_id,
                "role": role,
                "status": status,
                "instruction": str(state.get("instruction") or "").strip(),
                "scheduled_instruction": str(state.get("scheduled_instruction") or "").strip(),
                "priority": getattr(task, "priority", None),
                "automation_state": automation_state,
                "assigned_agent_code": assigned_slot,
                "dispatch_slot": target_slot,
                "dispatch_ready": dispatch_ready,
                "dispatch_blocked_reason": dependency_reason,
            }
        )
        candidate_map[task_id] = (task, state, target_slot)
    return dispatch_candidates, candidate_map


def _queue_team_mode_dispatches(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    source: str,
    exclude_task_ids: set[str] | None = None,
    allowed_roles: set[str] | None = None,
) -> int:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return 0
    parallel_limit = _project_automation_parallel_limit(db=db, project_id=normalized_project_id)
    now_utc = datetime.now(timezone.utc)
    dispatch_candidates, candidate_map = _build_team_mode_dispatch_candidates(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        exclude_task_ids=exclude_task_ids,
    )
    normalized_allowed_roles = {
        str(item or "").strip()
        for item in (allowed_roles or set())
        if str(item or "").strip()
    }
    if normalized_allowed_roles:
        dispatch_candidates = [
            item
            for item in dispatch_candidates
            if str(item.get("role") or "").strip() in normalized_allowed_roles
        ]
    plan = plan_team_mode_dispatch(
        dispatch_candidates,
        max_parallel_dispatch=parallel_limit,
    )

    from features.tasks.application import TaskApplicationService
    from shared.core import TaskAutomationRun

    queued = 0
    requested_at_iso = to_iso_utc(now_utc)
    for task_id in list(plan.get("queue_task_ids") or []):
        candidate = candidate_map.get(task_id)
        if candidate is None:
            continue
        task, state, target_slot = candidate
        instruction = (
            str(state.get("instruction") or "").strip()
            or str(state.get("scheduled_instruction") or "").strip()
        )
        actor_user_id = _resolve_task_actor_user_id(db=db, task_id=task_id, state=state)
        actor = db.get(UserModel, actor_user_id)
        if actor is None or not bool(getattr(actor, "is_active", False)):
            continue
        command_id = f"tm-kickoff-dev-{normalized_project_id[:8]}-{task_id[:8]}-{int(now_utc.timestamp())}"
        try:
            TaskApplicationService(db, actor, command_id=command_id).request_automation_run(
                task_id,
                TaskAutomationRun(instruction=instruction, source=source),
                wake_runner=False,
            )
        except Exception:
            continue
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=task_id,
            event_type=TASK_EVENT_UPDATED,
            payload={
                "last_dispatch_decision": {
                    "source": source,
                    "mode": str(plan.get("mode") or "").strip() or None,
                    "role": _resolve_assignee_project_role(
                        db=db,
                        workspace_id=workspace_id,
                        project_id=normalized_project_id,
                        assignee_id=str(state.get("assignee_id") or getattr(task, "assignee_id", "") or ""),
                        assigned_agent_code=str(state.get("assigned_agent_code") or getattr(task, "assigned_agent_code", "") or ""),
                        task_labels=state.get("labels") if state.get("labels") is not None else getattr(task, "labels", None),
                        task_status=str(state.get("status") or getattr(task, "status", "") or ""),
                    ),
                    "priority": str(getattr(task, "priority", "") or "").strip() or None,
                    "slot": target_slot or None,
                    "selected_at": requested_at_iso,
                    "available_slots": int((plan.get("counts") or {}).get("available_slots") or 0),
                },
            },
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
                "workspace_id": workspace_id,
                "project_id": normalized_project_id,
                "task_id": task_id,
            },
        )
        queued += 1
    return queued


def _status_change_trigger_action_type(trigger: dict[str, object]) -> str:
    action = trigger.get("action")
    if isinstance(action, dict):
        return str(action.get("type") or action.get("action") or "").strip().lower()
    return str(action or "").strip().lower()


def _team_mode_dispatch_dependency_ready(
    *,
    db,
    workspace_id: str,
    project_id: str,
    task_id: str,
    state: dict[str, object],
) -> tuple[bool, str | None]:
    task_relationships = normalize_task_relationships(state.get("task_relationships"))
    if task_relationships:
        blocked_reasons: list[str] = []
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
                source_status = str(source_state.get("status") or "").strip()
                if source_status in statuses:
                    matched_sources += 1
            if total_sources <= 0:
                continue
            if match_mode == STATUS_MATCH_ALL:
                if matched_sources == total_sources:
                    continue
            elif matched_sources > 0:
                continue
            blocked_reasons.append(
                f"waiting for relationship dependency: {matched_sources}/{total_sources} source tasks reached {sorted(statuses)}"
            )
        if blocked_reasons:
            return False, blocked_reasons[0]
        return True, None

    triggers = normalize_execution_triggers(state.get("execution_triggers"))
    relevant_triggers: list[dict[str, object]] = []
    for trigger in triggers:
        if not isinstance(trigger, dict):
            continue
        if str(trigger.get("kind") or "").strip().lower() != TRIGGER_KIND_STATUS_CHANGE:
            continue
        if not bool(trigger.get("enabled", True)):
            continue
        if str(trigger.get("scope") or "").strip().lower() != STATUS_SCOPE_EXTERNAL:
            continue
        action_type = _status_change_trigger_action_type(trigger)
        if action_type and action_type not in _STATUS_CHANGE_AUTOMATION_ACTIONS:
            continue
        selector = trigger.get("selector") if isinstance(trigger.get("selector"), dict) else {}
        source_task_ids = [
            str(item or "").strip()
            for item in (selector.get("task_ids") or [])
            if str(item or "").strip() and str(item or "").strip() != task_id
        ]
        if not source_task_ids:
            continue
        relevant_triggers.append(trigger)

    if not relevant_triggers:
        return True, None

    blocked_reasons: list[str] = []
    for trigger in relevant_triggers:
        selector = trigger.get("selector") if isinstance(trigger.get("selector"), dict) else {}
        source_task_ids = [
            str(item or "").strip()
            for item in (selector.get("task_ids") or [])
            if str(item or "").strip() and str(item or "").strip() != task_id
        ]
        to_statuses = {
            str(item or "").strip()
            for item in (trigger.get("to_statuses") or [])
            if str(item or "").strip()
        }
        if not to_statuses:
            continue
        match_mode = str(trigger.get("match_mode") or STATUS_MATCH_ANY).strip().lower()
        matched_sources = 0
        total_sources = 0
        for source_task_id in source_task_ids:
            source_state, _ = rebuild_state(db, "Task", source_task_id)
            if str(source_state.get("workspace_id") or "").strip() != workspace_id:
                continue
            if str(source_state.get("project_id") or "").strip() != project_id:
                continue
            total_sources += 1
            source_status = str(source_state.get("status") or "").strip()
            if source_status in to_statuses:
                matched_sources += 1
        if total_sources <= 0:
            continue
        if match_mode == STATUS_MATCH_ALL:
            if matched_sources == total_sources:
                return True, None
        elif matched_sources > 0:
            return True, None
        blocked_reasons.append(
            f"waiting for dependency status: {matched_sources}/{total_sources} source tasks reached {sorted(to_statuses)}"
        )

    if blocked_reasons:
        return False, blocked_reasons[0]
    return True, None


def _queue_initial_team_mode_developer_tasks_after_kickoff(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    kickoff_task_id: str,
) -> int:
    return _queue_team_mode_dispatches(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
        source="lead_kickoff_dispatch",
        exclude_task_ids={kickoff_task_id},
        allowed_roles={"Developer"},
    )


def _project_has_lead_task_in_lead_status(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return False
    member_role_by_user_id = {
        str(user_id): str(role or "").strip()
        for user_id, role in db.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == normalized_project_id,
            )
        ).all()
    }
    rows = db.execute(
        select(Task.id, Task.assignee_id, Task.assigned_agent_code, Task.labels, Task.status).where(
            Task.workspace_id == workspace_id,
            Task.project_id == normalized_project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
            Task.status != "Done",
        )
    ).all()
    for task_id, assignee_id, assigned_agent_code, labels, status in rows:
        normalized_status = str(status or "").strip()
        if normalized_status != "Lead":
            continue
        role = derive_task_role(
            task_like={
                "id": str(task_id or "").strip(),
                "assignee_id": str(assignee_id or "").strip(),
                "assigned_agent_code": str(assigned_agent_code or "").strip(),
                "labels": labels,
                "status": normalized_status,
            },
            member_role_by_user_id=member_role_by_user_id,
        )
        if role == "Lead":
            return True
    return False


def _project_has_merge_to_main_evidence(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return False
    task_ids = [
        str(item or "").strip()
        for item in db.execute(
            select(Task.id).where(
                Task.workspace_id == workspace_id,
                Task.project_id == normalized_project_id,
                Task.is_deleted == False,  # noqa: E712
                Task.archived == False,  # noqa: E712
            )
        ).scalars().all()
        if str(item or "").strip()
    ]
    for task_id in task_ids:
        state, _ = rebuild_state(db, "Task", task_id)
        if _task_has_main_merge_marker(state.get("external_refs")):
            return True
    return False


def _current_nonblocking_gate_key(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    assignee_role: str | None,
    task_status: str | None,
    task_state: dict[str, object] | None = None,
) -> str | None:
    normalized_status = str(task_status or "").strip()
    if (
        is_lead_role(assignee_role)
        and normalized_status == "Lead"
        and _project_has_git_delivery_skill(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        and not _project_has_merge_to_main_evidence(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
    ):
        normalized_project_id = str(project_id or "").strip()
        if workspace_id and normalized_project_id:
            rows = db.execute(
                select(Task.id, Task.status).where(
                    Task.workspace_id == workspace_id,
                    Task.project_id == normalized_project_id,
                    Task.is_deleted == False,  # noqa: E712
                    Task.archived == False,  # noqa: E712
                )
            ).all()
            for developer_task_id, developer_status in rows:
                developer_state, _ = rebuild_state(db, "Task", str(developer_task_id or "").strip())
                role = _resolve_assignee_project_role(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=normalized_project_id,
                    assignee_id=str(developer_state.get("assignee_id") or ""),
                    assigned_agent_code=str(developer_state.get("assigned_agent_code") or ""),
                    task_labels=developer_state.get("labels"),
                    task_status=str(developer_status or ""),
                )
                if not is_developer_role(role):
                    continue
                if str(developer_status or "").strip() == "Dev":
                    return "lead_waiting_merge_ready_developer"
                if str(developer_state.get("automation_state") or "").strip().lower() in {"queued", "running"}:
                    return "lead_waiting_merge_ready_developer"
    if (
        is_qa_role(assignee_role)
        and normalized_status == "QA"
        and _project_has_lead_task_in_lead_status(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
    ):
        qa_state = dict(task_state or {})
        latest_lead_deploy_at = None
        normalized_project_id = str(project_id or "").strip()
        if workspace_id and normalized_project_id:
            rows = db.execute(
                select(Task.id, Task.status).where(
                    Task.workspace_id == workspace_id,
                    Task.project_id == normalized_project_id,
                    Task.is_deleted == False,  # noqa: E712
                    Task.archived == False,  # noqa: E712
                )
            ).all()
            for lead_task_id, lead_status in rows:
                lead_state, _ = rebuild_state(db, "Task", str(lead_task_id or "").strip())
                role = _resolve_assignee_project_role(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=normalized_project_id,
                    assignee_id=str(lead_state.get("assignee_id") or ""),
                    assigned_agent_code=str(lead_state.get("assigned_agent_code") or ""),
                    task_labels=lead_state.get("labels"),
                    task_status=str(lead_status or ""),
                )
                if not is_lead_role(role):
                    continue
                deploy_execution = (
                    lead_state.get("last_deploy_execution")
                    if isinstance(lead_state.get("last_deploy_execution"), dict)
                    else {}
                )
                executed_at = str(deploy_execution.get("executed_at") or "").strip()
                if executed_at and (latest_lead_deploy_at is None or executed_at > latest_lead_deploy_at):
                    latest_lead_deploy_at = executed_at
        qa_handoff_deploy = (
            qa_state.get("last_lead_handoff_deploy_execution")
            if isinstance(qa_state.get("last_lead_handoff_deploy_execution"), dict)
            else {}
        )
        qa_handoff_deploy_at = str(qa_handoff_deploy.get("executed_at") or "").strip()
        if latest_lead_deploy_at and qa_handoff_deploy_at != latest_lead_deploy_at:
            return "qa_waiting_current_deploy_cycle"
        return "qa_waiting_lead_handoff"
    return None


def _extract_commit_shas_from_refs(refs: object) -> set[str]:
    out: set[str] = set()
    if not isinstance(refs, list):
        return out
    for item in refs:
        if isinstance(item, dict):
            text = f"{item.get('url') or ''} {item.get('label') or ''}"
        else:
            text = str(item or "")
        for match in _COMMIT_SHA_EXPLICIT_RE.findall(text):
            out.add(str(match).lower())
    return out


def _extract_commit_shas_from_text(text: str | None) -> set[str]:
    raw = str(text or "")
    return {str(match).lower() for match in _COMMIT_SHA_EXPLICIT_RE.findall(raw)}


def _task_has_git_delivery_completion_evidence(
    *,
    state: dict | None,
    summary: str,
    comment: str | None,
) -> bool:
    source = dict(state or {})
    title = str(source.get("title") or "").strip()
    description = str(source.get("description") or "").strip()
    instruction = str(source.get("instruction") or "").strip()
    scheduled_instruction = str(source.get("scheduled_instruction") or "").strip()
    refs = source.get("external_refs")
    refs_corpus_parts: list[str] = []
    if isinstance(refs, list):
        for item in refs:
            if isinstance(item, dict):
                refs_corpus_parts.append(str(item.get("url") or ""))
                refs_corpus_parts.append(str(item.get("label") or ""))
            else:
                refs_corpus_parts.append(str(item or ""))
    corpus = "\n".join(
        [
            title,
            description,
            instruction,
            scheduled_instruction,
            "\n".join(refs_corpus_parts),
            str(summary or ""),
            str(comment or ""),
        ]
    )
    commit_refs = _extract_commit_shas_from_refs(refs)
    commit_text = _extract_commit_shas_from_text(corpus)
    has_commit_evidence = bool(commit_refs or commit_text)
    has_branch_evidence = bool(_TASK_BRANCH_RE.search(corpus))
    if not (has_commit_evidence and has_branch_evidence):
        return False
    is_deploy_task = "deploy" in title.lower() or "docker compose" in title.lower()
    if not is_deploy_task:
        return True
    deploy_markers = ("docker compose", "/health", "http 200", "up (healthy)", "healthcheck")
    deploy_corpus = corpus.lower()
    return any(marker in deploy_corpus for marker in deploy_markers)


def _collect_git_evidence_from_outcome(outcome: AutomationOutcome) -> dict[str, object]:
    usage = outcome.usage if isinstance(outcome.usage, dict) else {}
    raw = usage.get("git_evidence")
    if not isinstance(raw, dict):
        return {}
    before = raw.get("before") if isinstance(raw.get("before"), dict) else {}
    after = raw.get("after") if isinstance(raw.get("after"), dict) else {}
    return {
        "task_workdir": str(raw.get("task_workdir") or "").strip(),
        "repo_root": str(raw.get("repo_root") or "").strip(),
        "task_branch": str(raw.get("task_branch") or "").strip(),
        "before_head_sha": str(before.get("head_sha") or "").strip().lower(),
        "after_head_sha": str(after.get("head_sha") or "").strip().lower(),
        "after_on_task_branch": bool(after.get("on_task_branch")),
        "after_is_dirty": bool(after.get("is_dirty")),
    }


def _collect_git_evidence_from_repo_state(
    *,
    project_name: str | None,
    project_id: str | None,
    task_id: str,
    title: str | None,
) -> dict[str, object]:
    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    if not repo_root.exists() or not repo_root.is_dir():
        return {}
    task_workdir = resolve_task_worktree_path(
        project_name=project_name,
        project_id=project_id,
        task_id=task_id,
    )
    branch_name = resolve_task_branch_name(task_id=task_id, title=title)

    code_branch, out_branch = _run_git_command(cwd=repo_root, args=["rev-parse", "--verify", f"refs/heads/{branch_name}"])
    if code_branch != 0 or not str(out_branch or "").strip():
        return {
            "repo_root": str(repo_root),
            "task_workdir": str(task_workdir) if task_workdir.exists() else "",
            "task_branch": branch_name,
        }

    after_head_sha = str(out_branch or "").strip().lower()
    after_on_task_branch = False
    after_is_dirty = False
    if task_workdir.exists() and task_workdir.is_dir():
        code_current, out_current = _run_git_command(cwd=task_workdir, args=["branch", "--show-current"])
        if code_current == 0:
            after_on_task_branch = str(out_current or "").strip() == branch_name
        code_status, out_status = _run_git_command(cwd=task_workdir, args=["status", "--porcelain"])
        if code_status == 0:
            after_is_dirty = bool(str(out_status or "").strip())
    return {
        "task_workdir": str(task_workdir) if task_workdir.exists() else "",
        "repo_root": str(repo_root),
        "task_branch": branch_name,
        "before_head_sha": "",
        "after_head_sha": after_head_sha,
        "after_on_task_branch": after_on_task_branch,
        "after_is_dirty": after_is_dirty,
    }


def _merge_git_evidence(primary: dict[str, object], fallback: dict[str, object]) -> dict[str, object]:
    merged = dict(fallback or {})
    for key, value in dict(primary or {}).items():
        if value not in (None, "", False):
            merged[key] = value
        elif key not in merged:
            merged[key] = value
    return merged


def _run_git_command(*, cwd: Path, args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    output = str(proc.stdout or "").strip()
    return int(proc.returncode), output


def _derive_files_changed_from_git_evidence(git_evidence: dict[str, object]) -> list[str]:
    repo_path = str(git_evidence.get("repo_root") or git_evidence.get("task_workdir") or "").strip()
    if not repo_path:
        return []
    cwd = Path(repo_path)
    if not cwd.exists() or not cwd.is_dir():
        return []
    before_head_sha = str(git_evidence.get("before_head_sha") or "").strip().lower()
    after_head_sha = str(git_evidence.get("after_head_sha") or "").strip().lower()
    files: list[str] = []
    seen: set[str] = set()

    def _append_from_output(output: str) -> None:
        for line in str(output or "").splitlines():
            path = str(line or "").strip()
            if not path or path in seen:
                continue
            seen.add(path)
            files.append(path)

    if before_head_sha and after_head_sha and before_head_sha != after_head_sha:
        code, out = _run_git_command(cwd=cwd, args=["diff", "--name-only", before_head_sha, after_head_sha])
        if code == 0:
            _append_from_output(out)
    if (not files) and after_head_sha:
        code, out = _run_git_command(cwd=cwd, args=["show", "--pretty=format:", "--name-only", after_head_sha])
        if code == 0:
            _append_from_output(out)
    return files


def _is_nontrivial_dev_path(path: str) -> bool:
    normalized = str(path or "").strip().replace("\\", "/").casefold()
    if not normalized:
        return False
    trivial_exact = {
        "readme.md",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        ".gitignore",
    }
    if normalized in trivial_exact:
        return False
    if normalized.startswith(".constructos/"):
        return False
    return True


def _validate_execution_outcome_contract(
    *,
    outcome: AutomationOutcome,
    assignee_role: str | None,
    task_status: str,
    git_delivery_enabled: bool,
    require_dev_tests: bool = False,
    require_nontrivial_dev_changes: bool = False,
    git_evidence: dict[str, object],
) -> str | None:
    developer_git_delivery_run = (
        git_delivery_enabled
        and is_developer_role(assignee_role)
        and str(task_status or "").strip() == "Dev"
    )
    contract = (
        dict(outcome.execution_outcome_contract)
        if isinstance(outcome.execution_outcome_contract, dict)
        else None
    )
    if contract is None:
        if not developer_git_delivery_run:
            return None
        return "Runner error: execution outcome contract is missing."
    if int(contract.get("contract_version") or 0) != 1:
        return "Runner error: execution outcome contract version is invalid."

    files_changed_raw = contract.get("files_changed")
    if not isinstance(files_changed_raw, list):
        return "Runner error: execution outcome contract files_changed must be an array."
    files_changed = [str(item or "").strip() for item in files_changed_raw if str(item or "").strip()]

    tests_run = contract.get("tests_run")
    tests_passed = contract.get("tests_passed")
    if not isinstance(tests_run, bool) or not isinstance(tests_passed, bool):
        return "Runner error: execution outcome contract tests_run/tests_passed must be booleans."
    if tests_passed and not tests_run:
        return "Runner error: execution outcome contract is inconsistent (tests_passed=true while tests_run=false)."
    if developer_git_delivery_run and tests_run and not tests_passed:
        return (
            "Runner error: Developer automation reported failing tests "
            "(tests_run=true, tests_passed=false); do not finalize implementation with known failing validation."
        )

    artifacts_raw = contract.get("artifacts")
    if not isinstance(artifacts_raw, list):
        return "Runner error: execution outcome contract artifacts must be an array."
    normalized_artifacts: list[dict[str, str | None]] = []
    for item in artifacts_raw:
        if not isinstance(item, dict):
            return "Runner error: execution outcome contract artifacts must contain only objects."
        kind = str(item.get("kind") or "").strip()
        ref = str(item.get("ref") or "").strip()
        if not kind or not ref:
            return "Runner error: execution outcome contract artifacts require non-empty kind/ref."
        normalized_artifacts.append(
            {
                "kind": kind,
                "ref": ref,
                "description": str(item.get("description") or "").strip() or None,
            }
        )

    commit_sha = str(contract.get("commit_sha") or "").strip().lower()
    branch = str(contract.get("branch") or "").strip()
    after_head_sha = str(git_evidence.get("after_head_sha") or "").strip().lower()
    task_branch = str(git_evidence.get("task_branch") or "").strip()
    if developer_git_delivery_run and not commit_sha and after_head_sha:
        commit_sha = after_head_sha
    if developer_git_delivery_run and not branch and task_branch:
        branch = task_branch
    if commit_sha and not bool(_COMMIT_SHA_RE.fullmatch(commit_sha)):
        return "Runner error: execution outcome contract commit_sha must be a valid git SHA."
    if branch and not bool(_TASK_BRANCH_RE.fullmatch(branch)):
        return "Runner error: execution outcome contract branch must use task/<...> format."

    if after_head_sha and commit_sha and after_head_sha != commit_sha:
        return "Runner error: execution outcome contract commit_sha mismatches git evidence."
    if task_branch and branch and task_branch != branch:
        return "Runner error: execution outcome contract branch mismatches task branch evidence."

    if developer_git_delivery_run and not files_changed:
        files_changed = _derive_files_changed_from_git_evidence(git_evidence)

    # Deterministic recovery path: if Dev+GitDelivery run omitted artifacts,
    # synthesize a minimal valid artifact set from concrete runtime evidence.
    if developer_git_delivery_run and not normalized_artifacts:
        if commit_sha:
            normalized_artifacts.append(
                {
                    "kind": "commit",
                    "ref": f"commit:{commit_sha}",
                    "description": "Derived from execution outcome contract/git evidence.",
                }
            )
        if branch:
            normalized_artifacts.append(
                {
                    "kind": "task_branch",
                    "ref": f"task-branch:{branch}",
                    "description": "Derived from execution outcome contract/git evidence.",
                }
            )
        if tests_run and tests_passed:
            normalized_artifacts.append(
                {
                    "kind": "tests",
                    "ref": "tests:passed",
                    "description": "Derived from execution_outcome_contract.tests_run/tests_passed.",
                }
            )

    if developer_git_delivery_run:
        if not files_changed:
            return "Runner error: Developer automation requires files_changed in execution outcome contract."
        if require_nontrivial_dev_changes and not any(_is_nontrivial_dev_path(item) for item in files_changed):
            return (
                "Runner error: Developer automation requires at least one non-trivial code/content change "
                "(README/compose-only updates are not sufficient for Dev completion)."
            )
        if not commit_sha:
            return "Runner error: Developer automation requires commit_sha in execution outcome contract."
        if not branch:
            return "Runner error: Developer automation requires branch in execution outcome contract."
        if require_dev_tests and (not tests_run or not tests_passed):
            return "Runner error: Developer automation requires tests_run=true and tests_passed=true."
        if not normalized_artifacts:
            return (
                "Runner error: Developer automation requires at least one execution artifact "
                "(object with non-empty kind/ref, e.g. kind='tests', ref='node --test: pass')."
            )

    return None


def _runner_can_apply_team_mode_transition(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    from_status: str,
    to_status: str,
    actor_role: str | None,
) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return True
    row = db.execute(
        select(ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == str(workspace_id),
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        return True
    try:
        config = json.loads(str(row[0] or "").strip() or "{}")
    except Exception:
        config = {}
    workflow = config.get("workflow") if isinstance(config, dict) else {}
    if not isinstance(workflow, dict):
        workflow = {}
    allowed, _reason = evaluate_team_mode_transition(
        workflow=workflow,
        from_status=str(from_status or "").strip(),
        to_status=str(to_status or "").strip(),
        actor_role=str(actor_role or "").strip() or None,
    )
    return bool(allowed)


def _append_task_status_transition_if_allowed(
    *,
    db,
    task_id: str,
    workspace_id: str,
    project_id: str | None,
    actor_user_id: str,
    actor_role: str | None,
    from_status: str,
    to_status: str,
) -> bool:
    if str(from_status or "").strip() == str(to_status or "").strip():
        return True
    allowed = _runner_can_apply_team_mode_transition(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
        from_status=from_status,
        to_status=to_status,
        actor_role=actor_role,
    )
    if not allowed:
        return False
    payload: dict[str, object] = {
        "status": to_status,
        **_team_mode_progress_payload(
            phase=_derive_team_mode_phase(
                assignee_role=actor_role,
                status=to_status,
            )
        ),
    }
    if canonicalize_role(actor_role) == "Lead" and str(to_status or "").strip() == "QA":
        payload["last_lead_handoff_token"] = (
            f"lead:{task_id}:{to_iso_utc(datetime.now(timezone.utc))}"
        )
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=task_id,
        event_type=TASK_EVENT_UPDATED,
        payload=payload,
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": task_id,
        },
    )
    return True


def _ensure_git_delivery_external_refs(
    *,
    refs: object,
    commit_sha: str,
    task_branch: str,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    if isinstance(refs, list):
        for item in refs:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            title = str(item.get("title") or "").strip()
            key = (url.casefold(), title.casefold())
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            entry: dict[str, str] = {"url": url}
            if title:
                entry["title"] = title
            normalized.append(entry)

    def _has_url(value: str) -> bool:
        needle = str(value or "").strip().casefold()
        if not needle:
            return False
        return any(str(item.get("url") or "").strip().casefold() == needle for item in normalized)

    commit_url = f"commit:{commit_sha}"
    branch_url = task_branch
    if not _has_url(commit_url):
        normalized.append({"url": commit_url, "title": "commit evidence"})
    if not _has_url(branch_url):
        normalized.append({"url": branch_url, "title": "task branch evidence"})
    return normalized


def _extract_task_branch_from_refs(refs: object) -> str | None:
    if not isinstance(refs, list):
        return None
    for item in refs:
        text = ""
        if isinstance(item, dict):
            text = f"{item.get('url') or ''} {item.get('title') or ''} {item.get('label') or ''}"
        else:
            text = str(item or "")
        matches = _TASK_BRANCH_RE.findall(text)
        if matches:
            return str(matches[0]).strip()
    return None


def _task_has_main_merge_marker(refs: object) -> bool:
    if not isinstance(refs, list):
        return False
    for item in refs:
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip().casefold()
        else:
            url = str(item or "").strip().casefold()
        if url.startswith(_MERGE_TO_MAIN_REF_PREFIX):
            return True
    return False


def _append_merge_to_main_ref(*, refs: object, merge_sha: str) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    if isinstance(refs, list):
        for item in refs:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            title = str(item.get("title") or "").strip()
            key = (url.casefold(), title.casefold())
            if key in seen:
                continue
            seen.add(key)
            entry: dict[str, str] = {"url": url}
            if title:
                entry["title"] = title
            normalized.append(entry)
    merge_url = f"{_MERGE_TO_MAIN_REF_PREFIX}{str(merge_sha or '').strip().lower()}"
    merge_key = (merge_url.casefold(), "merged to main".casefold())
    if merge_key not in seen:
        normalized.append({"url": merge_url, "title": "merged to main"})
    return normalized


def _derive_team_mode_phase(*, assignee_role: str | None, status: str | None) -> str:
    normalized_role = canonicalize_role(assignee_role)
    normalized_status = str(status or "").strip()
    if normalized_status == "Done":
        return "done"
    if normalized_status == "Blocked":
        return "blocked"
    if normalized_role == "Developer":
        if normalized_status == "Dev":
            return "dev_execution"
        if normalized_status == "Lead":
            return "ready_for_merge"
    if normalized_role == "Lead" and normalized_status == "Lead":
        return "triage"
    if normalized_role == "QA" and normalized_status == "QA":
        return "qa_validation"
    return "active"


def _team_mode_progress_payload(
    *,
    phase: str,
    blocking_gate: str | None = None,
    blocked_reason: str | None = None,
    blocked_at: str | None = None,
) -> dict[str, object]:
    return {
        "team_mode_phase": str(phase or "").strip() or "active",
        "team_mode_blocking_gate": str(blocking_gate or "").strip() or None,
        "team_mode_blocked_reason": str(blocked_reason or "").strip() or None,
        "team_mode_blocked_at": str(blocked_at or "").strip() or None,
        "runner_gate_defer_key": None,
        "runner_gate_defer_reason": None,
        "runner_gate_defer_at": None,
    }


def _append_lead_deploy_external_refs(
    *,
    refs: object,
    stack: str,
    port: int | None,
    health_path: str,
    runtime_ok: bool,
    http_url: str | None,
    http_status: int | None,
    project_name: str | None,
    project_id: str | None,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    if isinstance(refs, list):
        for item in refs:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            title = str(item.get("title") or "").strip()
            key = (url.casefold(), title.casefold())
            if key in seen:
                continue
            seen.add(key)
            entry: dict[str, str] = {"url": url}
            if title:
                entry["title"] = title
            normalized.append(entry)

    def _has_url(url_value: str) -> bool:
        needle = str(url_value or "").strip().casefold()
        if not needle:
            return False
        return any(str(item.get("url") or "").strip().casefold() == needle for item in normalized)

    stack_ref = f"{_DEPLOY_STACK_REF_PREFIX}{str(stack or '').strip()}"
    command_ref = f"{_DEPLOY_COMMAND_REF_PREFIX}docker compose -p {str(stack or '').strip()} up -d"
    if not _has_url(stack_ref):
        normalized.append({"url": stack_ref, "title": "deploy stack"})
    if not _has_url(command_ref):
        normalized.append({"url": command_ref, "title": "deploy command"})

    runtime_type, compose_marker = _derive_runtime_deploy_markers(
        project_name=project_name,
        project_id=project_id,
    )
    if compose_marker:
        compose_ref = f"{_DEPLOY_COMPOSE_REF_PREFIX}{compose_marker}"
        if not _has_url(compose_ref):
            normalized.append({"url": compose_ref, "title": "deploy compose manifest"})
    if runtime_type:
        runtime_ref = f"{_DEPLOY_RUNTIME_REF_PREFIX}{runtime_type}"
        if not _has_url(runtime_ref):
            normalized.append({"url": runtime_ref, "title": "deploy runtime decision"})

    health_ref = (
        str(http_url or "").strip()
        or f"http://gateway:{int(port)}{str(health_path or '/health').strip()}"
        if port is not None
        else f"{_DEPLOY_HEALTH_REF_PREFIX}{str(health_path or '/health').strip()}"
    )
    health_title = "deploy health: pass" if runtime_ok else f"deploy health: fail ({int(http_status or 0)})"
    if not _has_url(health_ref):
        normalized.append({"url": health_ref, "title": health_title})
    return normalized


def _derive_runtime_deploy_markers(
    *,
    project_name: str | None,
    project_id: str | None,
) -> tuple[str | None, str | None]:
    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    if not repo_root.exists():
        return None, None
    manifest = find_project_compose_manifest(project_name=project_name, project_id=project_id)
    compose_marker = None
    if manifest is not None:
        try:
            compose_marker = str(manifest.relative_to(repo_root))
        except Exception:
            compose_marker = str(manifest)
    dockerfile = repo_root / "Dockerfile"
    package_json = repo_root / "package.json"
    pyproject = repo_root / "pyproject.toml"
    requirements = repo_root / "requirements.txt"
    index_html = repo_root / "index.html"
    if dockerfile.exists():
        return "dockerfile_build", compose_marker
    if package_json.exists():
        return "node_web", compose_marker
    if pyproject.exists() or requirements.exists():
        return "python_web", compose_marker
    if index_html.exists():
        return "static_web", compose_marker
    return "unknown", compose_marker


def _write_file_if_changed(*, path: Path, content: str) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _ensure_git_identity(*, cwd: Path) -> None:
    code_user_name, _out_user_name, _err_user_name = _run_git_command_with_error(cwd=cwd, args=["config", "user.name"])
    if code_user_name != 0:
        _run_git_command_with_error(cwd=cwd, args=["config", "user.name", "Constructos Automation"])
    code_user_email, _out_user_email, _err_user_email = _run_git_command_with_error(cwd=cwd, args=["config", "user.email"])
    if code_user_email != 0:
        _run_git_command_with_error(cwd=cwd, args=["config", "user.email", "automation@constructos.local"])


def _commit_repo_changes_if_any(*, cwd: Path, message: str) -> str | None:
    _ensure_git_identity(cwd=cwd)
    code_add, _out_add, err_add = _run_git_command_with_error(cwd=cwd, args=["add", "-A"])
    if code_add != 0:
        raise RuntimeError(f"failed to stage synthesized deploy assets: {err_add[:220]}")
    code_status, out_status, err_status = _run_git_command_with_error(cwd=cwd, args=["status", "--porcelain"])
    if code_status != 0:
        raise RuntimeError(f"failed to inspect synthesized deploy assets: {err_status[:220]}")
    if not str(out_status or "").strip():
        return None
    code_commit, _out_commit, err_commit = _run_git_command_with_error(cwd=cwd, args=["commit", "-m", message])
    if code_commit != 0:
        raise RuntimeError(f"failed to commit synthesized deploy assets: {err_commit[:220]}")
    code_head, out_head, err_head = _run_git_command_with_error(cwd=cwd, args=["rev-parse", "HEAD"])
    if code_head != 0 or not out_head:
        raise RuntimeError(f"failed to resolve synthesized deploy commit sha: {err_head[:220]}")
    return str(out_head or "").strip().lower()


def _python_runtime_entrypoint(*, repo_root: Path) -> list[str] | None:
    main_py = repo_root / "main.py"
    app_py = repo_root / "app.py"
    if main_py.exists():
        return ["python", "main.py"]
    if app_py.exists():
        return ["python", "app.py"]
    return None


def _build_compose_manifest_for_build_runtime(*, port: int) -> str:
    return (
        "services:\n"
        "  app:\n"
        "    build:\n"
        "      context: .\n"
        f"    ports:\n"
        f"      - \"{int(port)}:{int(port)}\"\n"
        "    environment:\n"
        f"      PORT: \"{int(port)}\"\n"
        "    restart: unless-stopped\n"
    )


def _build_node_dockerfile(*, port: int) -> str:
    return (
        "FROM node:20-alpine\n"
        "WORKDIR /app\n"
        "COPY package*.json ./\n"
        "RUN if [ -f package-lock.json ] || [ -f npm-shrinkwrap.json ]; then npm ci; else npm install; fi\n"
        "COPY . .\n"
        f"ENV PORT={int(port)}\n"
        f"EXPOSE {int(port)}\n"
        "CMD [\"npm\", \"run\", \"start\"]\n"
    )


def _build_python_dockerfile(*, port: int, command: list[str]) -> str:
    command_json = json.dumps(command)
    install_line = (
        "RUN pip install --no-cache-dir -r requirements.txt\n"
        if (Path("requirements.txt")).name == "requirements.txt"
        else ""
    )
    return (
        "FROM python:3.12-slim\n"
        "WORKDIR /app\n"
        "ENV PYTHONDONTWRITEBYTECODE=1\n"
        "ENV PYTHONUNBUFFERED=1\n"
        "COPY . .\n"
        "RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; "
        "elif [ -f pyproject.toml ]; then pip install --no-cache-dir .; fi\n"
        f"ENV PORT={int(port)}\n"
        f"EXPOSE {int(port)}\n"
        f"CMD {command_json}\n"
    )


def _build_static_nginx_conf(*, health_path: str) -> str:
    normalized_health_path = str(health_path or "/health").strip() or "/health"
    return (
        "server {\n"
        "  listen 80;\n"
        "  server_name _;\n"
        f"  location = {normalized_health_path} {{\n"
        "    return 200 'ok';\n"
        "    add_header Content-Type text/plain;\n"
        "  }\n"
        "  location / {\n"
        "    root /usr/share/nginx/html;\n"
        "    try_files $uri $uri/ /index.html;\n"
        "  }\n"
        "}\n"
    )


def _build_static_compose_manifest(*, port: int) -> str:
    return (
        "services:\n"
        "  app:\n"
        "    image: nginx:1.27-alpine\n"
        f"    ports:\n"
        f"      - \"{int(port)}:80\"\n"
        "    volumes:\n"
        "      - ./:/usr/share/nginx/html:ro\n"
        "      - ./nginx.constructos.conf:/etc/nginx/conf.d/default.conf:ro\n"
        "    restart: unless-stopped\n"
    )


def _synthesize_runtime_deploy_assets(
    *,
    project_name: str | None,
    project_id: str | None,
    port: int,
    health_path: str,
) -> dict[str, object]:
    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    if not repo_root.exists() or not repo_root.is_dir():
        return {"ok": False, "error": f"repository root is missing: {repo_root}"}
    manifest_path = find_project_compose_manifest(project_name=project_name, project_id=project_id)
    if manifest_path is not None:
        return {"ok": True, "manifest_path": str(manifest_path), "created_files": [], "runtime_type": _derive_runtime_deploy_markers(project_name=project_name, project_id=project_id)[0]}

    dockerfile = repo_root / "Dockerfile"
    package_json = repo_root / "package.json"
    pyproject = repo_root / "pyproject.toml"
    requirements = repo_root / "requirements.txt"
    index_html = repo_root / "index.html"
    created_files: list[str] = []

    try:
        if dockerfile.exists():
            runtime_type = "dockerfile_build"
            compose_content = _build_compose_manifest_for_build_runtime(port=port)
        elif package_json.exists():
            package_data = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = package_data.get("scripts") if isinstance(package_data, dict) else {}
            start_script = str((scripts or {}).get("start") or "").strip() if isinstance(scripts, dict) else ""
            if not start_script:
                return {"ok": False, "error": "unsupported Node runtime: package.json is missing a non-empty scripts.start entry"}
            runtime_type = "node_web"
            if _write_file_if_changed(path=dockerfile, content=_build_node_dockerfile(port=port)):
                created_files.append("Dockerfile")
            compose_content = _build_compose_manifest_for_build_runtime(port=port)
        elif pyproject.exists() or requirements.exists():
            command = _python_runtime_entrypoint(repo_root=repo_root)
            if not command:
                return {"ok": False, "error": "unsupported Python runtime: expected main.py or app.py in repository root"}
            runtime_type = "python_web"
            if _write_file_if_changed(path=dockerfile, content=_build_python_dockerfile(port=port, command=command)):
                created_files.append("Dockerfile")
            compose_content = _build_compose_manifest_for_build_runtime(port=port)
        elif index_html.exists():
            runtime_type = "static_web"
            nginx_conf = repo_root / "nginx.constructos.conf"
            if _write_file_if_changed(path=nginx_conf, content=_build_static_nginx_conf(health_path=health_path)):
                created_files.append("nginx.constructos.conf")
            compose_content = _build_static_compose_manifest(port=port)
        else:
            return {"ok": False, "error": "unsupported runtime: repository does not contain Dockerfile, package.json, pyproject.toml, requirements.txt, or index.html"}

        manifest_path = repo_root / "docker-compose.yml"
        if _write_file_if_changed(path=manifest_path, content=compose_content):
            created_files.append("docker-compose.yml")
        commit_sha = _commit_repo_changes_if_any(
            cwd=repo_root,
            message="chore: synthesize deploy assets",
        )
        return {
            "ok": True,
            "manifest_path": str(manifest_path),
            "created_files": created_files,
            "commit_sha": commit_sha,
            "runtime_type": runtime_type,
        }
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"failed to parse package.json for deterministic deploy synthesis: {exc}"}
    except tomllib.TOMLDecodeError as exc:
        return {"ok": False, "error": f"failed to parse pyproject.toml for deterministic deploy synthesis: {exc}"}
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}


def _run_docker_compose_up_with_error(*, cwd: Path, stack: str) -> tuple[int, str, str]:
    wrapper = Path(__file__).resolve().parents[2] / "scripts" / "docker_wrapper.sh"
    env = dict(os.environ)
    env["AGENT_DOCKER_PROJECT_NAME"] = str(stack or "").strip()
    proc = subprocess.run(
        ["sh", str(wrapper), "compose", "-p", str(stack or "").strip(), "up", "-d"],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    return int(proc.returncode), str(proc.stdout or "").strip(), str(proc.stderr or "").strip()


def _collect_handoff_refs_from_tasks(*, db, task_ids: list[str]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    normalized_ids = [str(item or "").strip() for item in task_ids if str(item or "").strip()]
    if not normalized_ids:
        return refs
    for task_id in normalized_ids:
        state, _ = rebuild_state(db, "Task", task_id)
        external_refs = state.get("external_refs")
        if not isinstance(external_refs, list):
            continue
        for item in external_refs:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            title = str(item.get("title") or "").strip()
            key = (url.casefold(), title.casefold())
            if key in seen:
                continue
            seen.add(key)
            entry: dict[str, str] = {"url": url}
            if title:
                entry["title"] = title
            refs.append(entry)
    return refs


def _queue_qa_handoff_requests(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    lead_task_id: str,
    actor_user_id: str,
    lead_handoff_token: str,
    lead_handoff_at: str,
    lead_handoff_refs: list[dict[str, str]],
) -> int:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return 0
    lead_state, _ = rebuild_state(db, "Task", lead_task_id)
    member_role_by_user_id = {
        str(user_id): str(role or "").strip()
        for user_id, role in db.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == normalized_project_id,
            )
        ).all()
    }
    team_mode_row = db.execute(
        select(ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).first()
    config_obj: dict[str, object] = {}
    if team_mode_row is not None:
        try:
            parsed_cfg = json.loads(str(team_mode_row[0] or "").strip() or "{}")
            if isinstance(parsed_cfg, dict):
                config_obj = parsed_cfg
        except Exception:
            config_obj = {}
    team_agents = normalize_team_agents(config_obj.get("team"))
    agent_role_by_code = {
        str(agent.get("id") or "").strip(): str(agent.get("authority_role") or "").strip()
        for agent in team_agents
        if str(agent.get("id") or "").strip()
    }

    tasks = db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.project_id == normalized_project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
            Task.status == "QA",
        )
        .order_by(Task.created_at.asc())
    ).scalars().all()

    queued = 0
    for task in tasks:
        task_state, _ = rebuild_state(db, "Task", task.id)
        task_role = derive_task_role(
            task_like={
                "assignee_id": str(task.assignee_id or "").strip(),
                "assigned_agent_code": str(task.assigned_agent_code or "").strip(),
                "labels": task.labels,
                "status": str(task.status or "").strip(),
            },
            member_role_by_user_id=member_role_by_user_id,
            agent_role_by_code=agent_role_by_code,
        )
        if task_role != "QA":
            continue
        if str(task_state.get("automation_state") or "").strip() in {"queued", "running"}:
            continue
        instruction = (
            str(task_state.get("instruction") or "").strip()
            or str(task_state.get("scheduled_instruction") or "").strip()
        )
        if not instruction:
            continue
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=str(task.id),
            event_type=EVENT_AUTOMATION_REQUESTED,
            payload={
                "requested_at": lead_handoff_at,
                "instruction": instruction,
                "source": "lead_handoff",
                "source_task_id": lead_task_id,
                "reason": "lead_handoff",
                "trigger_link": f"{lead_task_id}->{str(task.id)}:QA",
                "correlation_id": lead_handoff_token,
                "trigger_task_id": lead_task_id,
                "from_status": "Lead",
                "to_status": "QA",
                "triggered_at": lead_handoff_at,
                "lead_handoff_token": lead_handoff_token,
                "lead_handoff_at": lead_handoff_at,
                "lead_handoff_refs": lead_handoff_refs,
                "lead_handoff_deploy_execution": (
                    lead_state.get("last_deploy_execution")
                    if isinstance(lead_state.get("last_deploy_execution"), dict)
                    else None
                ),
            },
            metadata={
                "actor_id": actor_user_id,
                "workspace_id": workspace_id,
                "project_id": normalized_project_id,
                "task_id": str(task.id),
                "trigger_task_id": lead_task_id,
                "trigger_from_status": "Lead",
                "trigger_to_status": "QA",
                "triggered_at": lead_handoff_at,
            },
        )
        queued += 1
    return queued


def _run_git_command_with_error(*, cwd: Path, args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    return int(proc.returncode), str(proc.stdout or "").strip(), str(proc.stderr or "").strip()


def _merge_ready_developer_branches_to_main(
    *,
    db,
    workspace_id: str,
    project_id: str,
    actor_user_id: str,
) -> dict[str, object]:
    project_row = db.get(Project, project_id)
    if project_row is None:
        return {"ok": True, "merged_task_ids": []}
    repo_root = resolve_project_repository_path(
        project_name=str(getattr(project_row, "name", "") or "").strip(),
        project_id=project_id,
    )
    if not repo_root.exists():
        return {"ok": True, "merged_task_ids": []}

    code_head, _out_head, _err_head = _run_git_command_with_error(cwd=repo_root, args=["rev-parse", "--verify", "HEAD"])
    if code_head != 0:
        return {"ok": True, "merged_task_ids": []}

    code_user_name, _out_user_name, _err_user_name = _run_git_command_with_error(cwd=repo_root, args=["config", "user.name"])
    if code_user_name != 0:
        _run_git_command_with_error(cwd=repo_root, args=["config", "user.name", "Constructos Automation"])
    code_user_email, _out_user_email, _err_user_email = _run_git_command_with_error(cwd=repo_root, args=["config", "user.email"])
    if code_user_email != 0:
        _run_git_command_with_error(cwd=repo_root, args=["config", "user.email", "automation@constructos.local"])

    code_checkout, _out_checkout, err_checkout = _run_git_command_with_error(cwd=repo_root, args=["checkout", "main"])
    if code_checkout != 0:
        return {"ok": False, "error": f"Runner error: failed to checkout main for merge: {err_checkout[:220]}"}

    member_role_by_user_id = {
        str(user_id): str(role or "").strip()
        for user_id, role in db.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == project_id,
            )
        ).all()
    }
    team_mode_row = db.execute(
        select(ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == project_id,
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).first()
    config_obj: dict[str, object] = {}
    if team_mode_row is not None:
        try:
            parsed_cfg = json.loads(str(team_mode_row[0] or "").strip() or "{}")
            if isinstance(parsed_cfg, dict):
                config_obj = parsed_cfg
        except Exception:
            config_obj = {}
    team_agents = normalize_team_agents(config_obj.get("team"))
    agent_role_by_code = {
        str(agent.get("id") or "").strip(): str(agent.get("authority_role") or "").strip()
        for agent in team_agents
        if str(agent.get("id") or "").strip()
    }

    candidates = db.execute(
        select(Task.id, Task.assignee_id, Task.assigned_agent_code, Task.labels, Task.status, Task.external_refs).where(
            Task.workspace_id == workspace_id,
            Task.project_id == project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
            Task.status == "Lead",
        )
    ).all()

    merged_task_ids: list[str] = []
    for task_id, assignee_id, assigned_agent_code, labels, status, external_refs_raw in candidates:
        task_id_text = str(task_id or "").strip()
        task_state = {
            "assignee_id": str(assignee_id or "").strip(),
            "assigned_agent_code": str(assigned_agent_code or "").strip(),
            "labels": labels,
            "status": str(status or "").strip(),
            "external_refs": json.loads(str(external_refs_raw or "[]")),
        }
        role = derive_task_role(
            task_like=task_state,
            member_role_by_user_id=member_role_by_user_id,
            agent_role_by_code=agent_role_by_code,
        )
        if role != "Developer":
            continue
        refs = task_state.get("external_refs")
        if _task_has_main_merge_marker(refs):
            continue
        if not _task_has_git_delivery_completion_evidence(state=task_state, summary="", comment=None):
            continue
        branch = _extract_task_branch_from_refs(refs)
        if not branch:
            continue

        code_branch, _out_branch, _err_branch = _run_git_command_with_error(cwd=repo_root, args=["rev-parse", "--verify", f"refs/heads/{branch}"])
        if code_branch != 0:
            continue
        code_ancestor, _out_ancestor, _err_ancestor = _run_git_command_with_error(cwd=repo_root, args=["merge-base", "--is-ancestor", branch, "main"])
        if code_ancestor == 0:
            # Already merged: just mark merge evidence once.
            code_main_sha, out_main_sha, _err_main_sha = _run_git_command_with_error(cwd=repo_root, args=["rev-parse", "main"])
            if code_main_sha == 0 and out_main_sha:
                merged_refs = _append_merge_to_main_ref(refs=refs, merge_sha=out_main_sha)
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=task_id_text,
                    event_type=TASK_EVENT_UPDATED,
                    payload={"external_refs": merged_refs, **_team_mode_progress_payload(phase="merge")},
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": task_id_text,
                    },
                )
                merged_task_ids.append(task_id_text)
            continue

        code_merge, _out_merge, err_merge = _run_git_command_with_error(
            cwd=repo_root,
            args=["merge", "--no-ff", "--no-edit", branch],
        )
        if code_merge != 0:
            _run_git_command_with_error(cwd=repo_root, args=["merge", "--abort"])
            return {"ok": False, "error": f"Runner error: deterministic merge to main failed for {branch}: {err_merge[:240]}"}

        code_main_sha, out_main_sha, err_main_sha = _run_git_command_with_error(cwd=repo_root, args=["rev-parse", "HEAD"])
        if code_main_sha != 0 or not out_main_sha:
            return {"ok": False, "error": f"Runner error: merged branch {branch} but could not resolve main HEAD: {err_main_sha[:220]}"}
        merged_refs = _append_merge_to_main_ref(refs=refs, merge_sha=out_main_sha)
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=task_id_text,
            event_type=TASK_EVENT_UPDATED,
            payload={"external_refs": merged_refs, **_team_mode_progress_payload(phase="merge")},
            metadata={
                "actor_id": actor_user_id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": task_id_text,
            },
        )
        merged_task_ids.append(task_id_text)

    return {"ok": True, "merged_task_ids": merged_task_ids}


def _normalize_string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = str(item or "").strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _parse_task_labels(raw_labels: str | None) -> list[str]:
    return parse_labels(raw_labels)


def _task_state_for_selector(task: Task) -> dict[str, object]:
    return {
        "id": str(task.id or "").strip(),
        "workspace_id": str(task.workspace_id or "").strip(),
        "project_id": str(task.project_id or "").strip(),
        "specification_id": str(task.specification_id or "").strip(),
        "assignee_id": str(task.assignee_id or "").strip(),
        "labels": _parse_task_labels(task.labels),
        "status": str(task.status or "").strip(),
        "updated_at": to_iso_utc(task.updated_at) if getattr(task, "updated_at", None) else None,
    }


def _normalize_status_change_action(raw: object) -> str | None:
    if isinstance(raw, dict):
        return str(raw.get("type") or raw.get("action") or "").strip().lower() or None
    return str(raw or "").strip().lower() or None


def _is_cross_task_automation_action(action: str | None) -> bool:
    if not action:
        return True
    return action in _STATUS_CHANGE_AUTOMATION_ACTIONS


def _task_has_execution_evidence(*, db, task_id: str, state: dict | None) -> bool:
    source = dict(state or {})
    external_refs = source.get("external_refs")
    if isinstance(external_refs, list):
        for item in external_refs:
            if isinstance(item, dict) and str(item.get("url") or "").strip():
                return True
            if isinstance(item, str) and str(item).strip():
                return True
    attachment_refs = source.get("attachment_refs")
    if isinstance(attachment_refs, list):
        for item in attachment_refs:
            if isinstance(item, dict) and str(item.get("path") or "").strip():
                return True
    note_row = db.execute(
        select(Note.id).where(
            Note.task_id == task_id,
            Note.is_deleted == False,  # noqa: E712
        ).limit(1)
    ).scalar_one_or_none()
    return note_row is not None


def _is_noop_ack_comment(comment: str | None) -> bool:
    normalized = str(comment or "").strip().casefold()
    if not normalized:
        return False
    return normalized.startswith("codex runner: request accepted, leaving progress note.")


def _is_transient_runner_interruption(error: Exception | str | None) -> bool:
    text = str(error or "").strip()
    if not text:
        return False
    return bool(_TRANSIENT_INTERRUPT_RE.search(text))


def _is_recoverable_failure(error: Exception | str | None) -> bool:
    text = str(error or "").strip()
    if not text:
        return False
    return bool(_RECOVERABLE_FAILURE_RE.search(text))


def _is_non_blocking_team_mode_gate_error(error: Exception | str | None) -> bool:
    text = str(error or "").strip().casefold()
    if not text:
        return False
    return (
        _TEAM_MODE_QA_LEAD_HANDOFF_GATED_FRAGMENT in text
        or _TEAM_MODE_QA_CURRENT_DEPLOY_CYCLE_GATED_FRAGMENT in text
        or _TEAM_MODE_LEAD_MERGE_READY_GATED_FRAGMENT in text
    )


def _resolve_project_human_member_user_ids(*, db, workspace_id: str, project_id: str | None) -> list[str]:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return []
    rows = db.execute(
        select(ProjectMember.user_id)
        .join(UserModel, UserModel.id == ProjectMember.user_id)
        .where(
            ProjectMember.workspace_id == workspace_id,
            ProjectMember.project_id == normalized_project_id,
            UserModel.is_active == True,  # noqa: E712
            UserModel.user_type != "agent",
        )
    ).scalars().all()
    out: list[str] = []
    seen: set[str] = set()
    for item in rows:
        user_id = str(item or "").strip()
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        out.append(user_id)
    return out


def _handoff_failed_task_to_human(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    state: dict[str, object] | None,
    actor_user_id: str,
    failed_at_iso: str,
    failure_reason: str,
) -> str | None:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return None
    source = dict(state or {})
    current_assignee_id = str(source.get("assignee_id") or "").strip()
    current_assigned_agent_code = str(source.get("assigned_agent_code") or "").strip()
    if not current_assignee_id:
        return None
    current_user_row = db.get(UserModel, current_assignee_id)
    current_user_type = str(getattr(current_user_row, "user_type", "") or "").strip().lower()
    # Only handoff when task is currently routed to an agent assignee.
    if current_user_type != "agent":
        return None

    human_member_ids = _resolve_project_human_member_user_ids(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    if not human_member_ids:
        return None
    target_human_id = actor_user_id if actor_user_id in human_member_ids else human_member_ids[0]
    if not target_human_id or target_human_id == current_assignee_id:
        return None

    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "assignee_id": target_human_id,
            "assigned_agent_code": None,
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": normalized_project_id,
            "task_id": task_id,
        },
    )

    notification_message = (
        "Automation could not recover and this task was handed off to a human project member.\n\n"
        f"- Previous assignee: `{current_assignee_id}`\n"
        f"- Previous team agent: `{current_assigned_agent_code or 'none'}`\n"
        f"- New assignee: `{target_human_id}`\n"
        f"- Reason: {str(failure_reason or '').strip()[:400]}"
    )
    append_notification_created_event(
        db,
        append_event_fn=append_event,
        user_id=target_human_id,
        message=notification_message,
        actor_id=actor_user_id,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        task_id=task_id,
        notification_type="ManualMessage",
        severity="warning",
        dedupe_key=f"runner-human-handoff:{task_id}:{failed_at_iso[:19]}",
        payload={
            "kind": "automation_human_handoff",
            "task_id": task_id,
            "from_assignee_id": current_assignee_id,
            "from_assigned_agent_code": current_assigned_agent_code or None,
            "to_assignee_id": target_human_id,
            "reason": str(failure_reason or "").strip(),
        },
        source_event="agents.runner.human_handoff",
    )
    return target_human_id


def _is_blocked_outcome(*, summary: str | None, comment: str | None) -> bool:
    summary_head = str(summary or "").strip().splitlines()[0:1]
    comment_head = str(comment or "").strip().splitlines()[0:1]
    summary_first = summary_head[0].strip().upper() if summary_head else ""
    comment_first = comment_head[0].strip().upper() if comment_head else ""
    return summary_first == _AUTOMATION_BLOCKED_MARKER or comment_first == _AUTOMATION_BLOCKED_MARKER


def _project_completion_snapshot(*, db, workspace_id: str, project_id: str | None) -> dict[str, object]:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return {"all_done": False, "total": 0, "done": 0, "task_ids": []}
    task_ids = [
        str(item or "").strip()
        for item in db.execute(
            select(Task.id).where(
                Task.workspace_id == workspace_id,
                Task.project_id == normalized_project_id,
                Task.is_deleted == False,  # noqa: E712
                Task.archived == False,  # noqa: E712
            )
        ).scalars().all()
        if str(item or "").strip()
    ]
    done = 0
    for task_id in task_ids:
        state, _ = rebuild_state(db, "Task", task_id)
        if str(state.get("status") or "").strip() == "Done":
            done += 1
    total = len(task_ids)
    return {
        "all_done": bool(total > 0 and done == total),
        "total": total,
        "done": done,
        "task_ids": sorted(task_ids),
    }


def _notify_humans_blocked(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    actor_user_id: str,
    task_id: str,
    task_title: str,
    task_status: str,
    summary: str,
    comment: str | None,
) -> None:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return
    human_ids = _resolve_project_human_member_user_ids(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    if not human_ids:
        return
    text = str(comment or "").strip() or str(summary or "").strip()
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12] if text else "none"
    for human_id in human_ids:
        append_notification_created_event(
            db,
            append_event_fn=append_event,
            user_id=human_id,
            message=(
                f"Task automation is blocked for **{task_title or task_id}** (`{task_status or 'Unknown'}`).\n\n"
                "Open the task to review blocker details and continue the workflow."
            ),
            actor_id=actor_user_id,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            task_id=task_id,
            notification_type="ManualMessage",
            severity="warning",
            dedupe_key=f"automation-blocked:{task_id}:{digest}",
            payload={
                "kind": "automation_blocked",
                "task_id": task_id,
                "summary": str(summary or "").strip(),
                "comment": str(comment or "").strip() or None,
            },
            source_event="agents.runner.automation_blocked",
        )


def _notify_humans_project_completed(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    actor_user_id: str,
) -> None:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return
    snapshot = _project_completion_snapshot(db=db, workspace_id=workspace_id, project_id=normalized_project_id)
    if not bool(snapshot.get("all_done")):
        return
    task_ids = list(snapshot.get("task_ids") or [])
    digest = hashlib.sha1(",".join(task_ids).encode("utf-8")).hexdigest()[:12] if task_ids else "none"
    human_ids = _resolve_project_human_member_user_ids(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    for human_id in human_ids:
        append_notification_created_event(
            db,
            append_event_fn=append_event,
            user_id=human_id,
            message="Project workflow reached completion: all active tasks are now **Done**.",
            actor_id=actor_user_id,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            notification_type="ManualMessage",
            severity="info",
            dedupe_key=f"project-completed:{normalized_project_id}:{digest}",
            payload={
                "kind": "project_completed",
                "project_id": normalized_project_id,
                "done_tasks": int(snapshot.get("done") or 0),
                "total_tasks": int(snapshot.get("total") or 0),
            },
            source_event="agents.runner.project_completed",
        )


def _enqueue_team_lead_blocker_escalation(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    blocked_task_id: str,
    blocked_title: str,
    blocked_role: str,
    blocked_status: str,
    blocked_error: str | None,
) -> int:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return 0
    lead_role = lead_role_for_escalation(db=db, workspace_id=workspace_id, project_id=normalized_project_id)
    if not str(lead_role or "").strip():
        return 0
    member_role_by_user_id = {
        str(user_id): str(role or "").strip()
        for user_id, role in db.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == normalized_project_id,
            )
        ).all()
    }
    all_tasks = db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.project_id == normalized_project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
            Task.status != "Done",
        )
        .order_by(Task.created_at.asc())
    ).scalars().all()
    lead_tasks = [
        task
        for task in all_tasks
        if derive_task_role(
            task_like={
                "assignee_id": str(task.assignee_id or "").strip(),
                "assigned_agent_code": str(task.assigned_agent_code or "").strip(),
                "labels": task.labels,
                "status": str(task.status or "").strip(),
            },
            member_role_by_user_id=member_role_by_user_id,
        )
        == str(lead_role)
    ]
    queued = 0
    for lead_task in lead_tasks:
        lead_state, _ = rebuild_state(db, "Task", lead_task.id)
        if str(lead_state.get("automation_state") or "").strip() in {"queued", "running"}:
            continue
        instruction = (
            str(lead_state.get("instruction") or "").strip()
            or str(lead_state.get("scheduled_instruction") or "").strip()
            or "Handle blocker escalation and coordinate next actions."
        )
        requested_at = to_iso_utc(datetime.now(timezone.utc))
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=lead_task.id,
            event_type=EVENT_AUTOMATION_REQUESTED,
            payload={
                "requested_at": requested_at,
                "instruction": instruction,
                "source": "blocker_escalation",
                "trigger_task_id": blocked_task_id,
                "to_status": blocked_status or "Blocked",
                "from_status": None,
                "triggered_at": requested_at,
            },
            metadata={
                "actor_id": str(lead_task.assignee_id or AGENT_SYSTEM_USER_ID),
                "workspace_id": workspace_id,
                "project_id": normalized_project_id,
                "task_id": lead_task.id,
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=lead_task.id,
            event_type=TASK_EVENT_UPDATED,
            payload={
                "last_dispatch_decision": {
                    "source": "blocker_escalation",
                    "mode": "lead_dispatch",
                    "role": str(lead_role or "").strip() or "Lead",
                    "priority": None,
                    "slot": str(lead_state.get("assigned_agent_code") or getattr(lead_task, "assigned_agent_code", "") or "").strip() or None,
                    "selected_at": requested_at,
                    "available_slots": None,
                    "blocked_task_id": blocked_task_id,
                    "blocked_status": blocked_status or "Blocked",
                },
            },
            metadata={
                "actor_id": str(lead_task.assignee_id or AGENT_SYSTEM_USER_ID),
                "workspace_id": workspace_id,
                "project_id": normalized_project_id,
                "task_id": lead_task.id,
            },
        )
        queued += 1

    lead_assignee = str(lead_tasks[0].assignee_id or "").strip() if lead_tasks else AGENT_SYSTEM_USER_ID
    if not lead_assignee:
        lead_assignee = AGENT_SYSTEM_USER_ID
    blocked_summary = str(blocked_error or "").strip()[:300]
    dedupe_hash = hashlib.sha1(blocked_summary.encode("utf-8")).hexdigest()[:12] if blocked_summary else "none"
    human_ids = _resolve_project_human_member_user_ids(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    for human_id in human_ids:
        notification_cfg = blocker_escalation_notification(
            blocked_task_id=blocked_task_id,
            blocked_title=blocked_title,
            blocked_role=blocked_role,
            blocked_status=blocked_status,
            blocked_error=blocked_error,
            queued_lead_tasks=queued,
        )
        message = str(notification_cfg.get("message") or "").strip() or (
            f"Workflow blocker detected: {blocked_title or blocked_task_id} "
            f"({blocked_role or 'agent'}, status={blocked_status or 'Blocked'}). "
            "Lead escalation run was queued."
        )
        kind = str(notification_cfg.get("kind") or "").strip() or "workflow_blocker_escalation"
        dedupe_prefix = str(notification_cfg.get("dedupe_prefix") or "").strip() or "workflow-blocker"
        source_event = str(notification_cfg.get("source_event") or "").strip() or "agents.runner.blocker_escalation"
        append_notification_created_event(
            db,
            append_event_fn=append_event,
            user_id=human_id,
            message=message,
            actor_id=lead_assignee,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            task_id=blocked_task_id,
            notification_type="ManualMessage",
            severity="warning",
            dedupe_key=f"{dedupe_prefix}:{blocked_task_id}:{blocked_status or 'Blocked'}:{dedupe_hash}",
            payload={
                "kind": kind,
                "blocked_task_id": blocked_task_id,
                "blocked_role": blocked_role,
                "blocked_status": blocked_status,
                "queued_lead_tasks": queued,
                "error": blocked_summary,
            },
            source_event=source_event,
        )
    return queued


def _append_schedule_rearm_update(
    *,
    db,
    task_id: str,
    workspace_id: str,
    project_id: str | None,
    actor_user_id: str,
    execution_triggers,
    now_utc: datetime,
) -> None:
    updated_triggers, next_due = rearm_first_schedule_trigger(
        execution_triggers=execution_triggers,
        now_utc=now_utc,
    )
    if not next_due:
        return
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "execution_triggers": updated_triggers,
            "scheduled_at_utc": next_due,
            "schedule_state": "idle",
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": task_id,
        },
    )


def _requeue_pending_status_change_request(
    *,
    db,
    run: QueuedAutomationRun,
    state: dict,
    workspace_id: str,
    project_id: str | None,
    actor_user_id: str,
    requested_at_iso: str,
) -> None:
    pending_requests = _normalize_nonnegative_int(state.get("automation_pending_requests"))
    if pending_requests <= 0:
        return
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=run.task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={"automation_pending_requests": pending_requests - 1},
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": run.task_id,
        },
    )
    instruction = run.instruction or str(state.get("instruction") or state.get("scheduled_instruction") or "").strip()
    if not instruction:
        return
    trigger_task_id = str(state.get("last_requested_trigger_task_id") or run.trigger_task_id or "").strip() or None
    trigger_from_status = str(state.get("last_requested_from_status") or run.trigger_from_status or "").strip() or None
    trigger_to_status = str(state.get("last_requested_to_status") or run.trigger_to_status or "").strip() or None
    triggered_at = str(state.get("last_requested_triggered_at") or run.triggered_at or "").strip() or requested_at_iso
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=run.task_id,
        event_type=EVENT_AUTOMATION_REQUESTED,
        payload={
            "requested_at": requested_at_iso,
            "instruction": instruction,
            "source": "status_change",
            "trigger_task_id": trigger_task_id,
            "from_status": trigger_from_status,
            "to_status": trigger_to_status,
            "triggered_at": triggered_at,
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": run.task_id,
            "trigger_task_id": trigger_task_id,
            "trigger_from_status": trigger_from_status,
            "trigger_to_status": trigger_to_status,
            "triggered_at": triggered_at,
        },
    )


def _claim_queued_task(task_id: str, *, allow_fresh_kickoff: bool = False) -> QueuedAutomationRun | None:
    with SessionLocal() as db:
        state, version = rebuild_state(db, "Task", task_id)
        if state.get("automation_state", "idle") != "queued":
            return None
        workspace_id = str(state.get("workspace_id") or "").strip()
        if not workspace_id:
            return None
        project_id = str(state.get("project_id") or "").strip() or None
        request_source = str(state.get("last_requested_source") or "").strip().lower()
        requested_instruction = str(state.get("last_requested_instruction") or "").strip()
        if (not allow_fresh_kickoff) and _is_classified_team_mode_kickoff(state=state):
            requested_at_dt = _parse_iso_utc(str(state.get("last_requested_at") or "").strip())
            if requested_at_dt is not None:
                age_seconds = (datetime.now(timezone.utc) - requested_at_dt).total_seconds()
                if age_seconds < float(_KICKOFF_EXECUTION_HOLDOFF_SECONDS):
                    return None
        trigger_task_id = str(state.get("last_requested_trigger_task_id") or "").strip() or None
        trigger_from_status = str(state.get("last_requested_from_status") or "").strip() or None
        trigger_to_status = str(state.get("last_requested_to_status") or "").strip() or None
        triggered_at = str(state.get("last_requested_triggered_at") or "").strip() or None
        is_scheduled_run = request_source == "schedule"
        schedule_state = str(state.get("schedule_state", "idle")).strip().lower()
        actor_user_id = _resolve_task_actor_user_id(db=db, task_id=task_id, state=state)
        if _task_uses_shared_project_workspace(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            task_status=str(state.get("status") or "").strip(),
            task_assignee_id=str(state.get("assignee_id") or "").strip(),
            task_assigned_agent_code=str(state.get("assigned_agent_code") or "").strip(),
            task_labels=state.get("labels"),
            actor_user_id=actor_user_id,
        ) and _project_has_running_automation(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            exclude_task_id=task_id,
        ):
            return None
        project_parallel_limit = _project_automation_parallel_limit(db=db, project_id=project_id)
        project_running_count = _project_running_automation_count(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            exclude_task_id=task_id,
        )
        if project_running_count >= project_parallel_limit:
            return None
        claim_assignee_role = _resolve_assignee_project_role(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            assignee_id=str(state.get("assignee_id") or ""),
            assigned_agent_code=str(state.get("assigned_agent_code") or ""),
            task_labels=state.get("labels"),
            task_status=str(state.get("status") or ""),
        )
        claim_phase = _derive_team_mode_phase(
            assignee_role=claim_assignee_role,
            status=str(state.get("status") or ""),
        )
        now_iso = to_iso_utc(datetime.now(timezone.utc))
        try:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=task_id,
                event_type=EVENT_AUTOMATION_STARTED,
                payload={
                    "started_at": now_iso,
                    "last_agent_progress": "Automation run started.",
                    "last_agent_stream_status": "Automation run started.",
                    "last_agent_stream_updated_at": now_iso,
                    **_team_mode_progress_payload(phase=claim_phase),
                },
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": task_id,
                },
                expected_version=version,
            )
            if is_scheduled_run and schedule_state in {"queued", "idle"}:
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=task_id,
                    event_type=EVENT_SCHEDULE_STARTED,
                    payload={"started_at": now_iso},
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": task_id,
                    },
                )
            db.commit()
        except ConcurrencyConflictError:
            db.rollback()
            return None
    requested_instruction = str(state.get("last_requested_instruction") or "").strip()
    task_instruction = (
        str(state.get("instruction") or "").strip()
        or str(state.get("scheduled_instruction") or "").strip()
    )
    assignee_role = _resolve_assignee_project_role(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
        assignee_id=str(state.get("assignee_id") or ""),
        assigned_agent_code=str(state.get("assigned_agent_code") or ""),
        task_labels=state.get("labels"),
        task_status=str(state.get("status") or ""),
    )
    # Kickoff instructions are dispatch-only and must not override role-specific task instructions
    # for Developer/QA execution runs.
    if requested_instruction and _is_classified_team_mode_kickoff(state=state) and not is_lead_role(assignee_role):
        instruction = task_instruction
    else:
        instruction = requested_instruction or task_instruction
    if (
        is_lead_role(assignee_role)
        and str(state.get("status") or "").strip() == "Lead"
        and _project_has_git_delivery_skill(db=db, workspace_id=workspace_id, project_id=project_id)
    ):
        stack, port, health_path, runtime_required = _project_runtime_deploy_target(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if runtime_required:
            port_text = str(port) if port is not None else "UNSET"
            has_merge_to_main = _project_has_merge_to_main_evidence(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            if not has_merge_to_main:
                deploy_steps = (
                    "Lead deployment execution contract:\n"
                    f"1) Probe runtime health at `http://gateway:{port_text}{health_path}` for observability only.\n"
                    "2) No merge-to-main evidence exists yet: do NOT create compose and do NOT deploy.\n"
                    "3) Coordinate Developer completion and deterministic merge-to-main first.\n"
                    "4) Record deferred state evidence in external_refs and keep Lead task active."
                )
            else:
                deploy_steps = (
                    "Lead deployment execution contract:\n"
                    f"1) Probe runtime health at `http://gateway:{port_text}{health_path}`.\n"
                    "2) If health is failing OR there is new merge-to-main evidence since last deploy evidence, prepare deployment assets before deploy:\n"
                    "   - Ensure repository contains one compose manifest (`docker-compose.yml|docker-compose.yaml|compose.yml|compose.yaml`).\n"
                    "   - If manifest is missing, Lead must create it from concrete repository evidence (no guessing):\n"
                    "     a) If `Dockerfile` exists, compose must use `build: .` and expose configured runtime port.\n"
                    "     b) Else if Node runtime files exist (`package.json` with a valid start script), create deterministic Dockerfile + compose for Node.\n"
                    "     c) Else if Python runtime files exist (`pyproject.toml` or `requirements.txt` with runnable entrypoint), create deterministic Dockerfile + compose for Python.\n"
                    "     d) Else if only static web assets exist (`index.html`), create deterministic nginx-based compose.\n"
                    "     e) If none of the supported deterministic runtime signals exist, set task to Blocked with exact missing prerequisites (do not invent runtime).\n"
                    f"3) Execute deploy for stack `{stack}` (`docker compose -p {stack} up -d`).\n"
                    "4) Re-probe health endpoint and require HTTP 200 before QA handoff.\n"
                    "5) Record full evidence in external_refs: compose manifest path, deploy command result, health probe result, and runtime decision basis.\n"
                    "6) If final health is OK after required actions, move Lead task to QA; if not, set Blocked with exact failure evidence."
                )
            instruction = f"{str(instruction or '').strip()}\n\n{deploy_steps}".strip()
    if not instruction:
        return None
    return QueuedAutomationRun(
        task_id=task_id,
        workspace_id=workspace_id,
        project_id=project_id,
        title=str(state.get("title") or ""),
        description=str(state.get("description") or ""),
        status=str(state.get("status") or "To do"),
        instruction=instruction,
        request_source=request_source,
        is_scheduled_run=is_scheduled_run,
        trigger_task_id=trigger_task_id,
        trigger_from_status=trigger_from_status,
        trigger_to_status=trigger_to_status,
        triggered_at=triggered_at,
        actor_user_id=actor_user_id,
        execution_kickoff_intent=bool(state.get("last_requested_execution_kickoff_intent")),
        workflow_scope=str(state.get("last_requested_workflow_scope") or "").strip() or None,
        execution_mode=str(state.get("last_requested_execution_mode") or "").strip() or None,
        task_completion_requested=bool(state.get("last_requested_task_completion_requested")),
    )


def _record_automation_success(run: QueuedAutomationRun, *, outcome: AutomationOutcome) -> None:
    action = str(outcome.action or "").strip()
    summary = str(outcome.summary or "").strip()
    comment = str(outcome.comment or "").strip() or None
    usage_metadata = build_automation_usage_metadata(outcome)
    usage_payload = usage_metadata.get("last_agent_usage")
    completed_at = to_iso_utc(datetime.now(timezone.utc))
    now_utc = datetime.now(timezone.utc)
    queued_followup_developer_dispatches = 0
    with SessionLocal() as db:
        state, _ = rebuild_state(db, "Task", run.task_id)
        workspace_id = str(state.get("workspace_id") or run.workspace_id or "").strip()
        if not workspace_id:
            return
        project_id = str(state.get("project_id") or run.project_id or "").strip() or None
        project_name = None
        if project_id:
            project_row = db.get(Project, str(project_id))
            if project_row is not None:
                project_name = str(getattr(project_row, "name", "") or "").strip() or None
        actor_user_id = _resolve_task_actor_user_id(
            db=db,
            task_id=run.task_id,
            state=state,
            fallback_actor_user_id=run.actor_user_id,
        )
        assignee_role = _resolve_assignee_project_role(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            assignee_id=str(state.get("assignee_id") or ""),
            assigned_agent_code=str(state.get("assigned_agent_code") or ""),
            task_labels=state.get("labels"),
            task_status=str(state.get("status") or ""),
        )
        git_delivery_enabled = _project_has_git_delivery_skill(db=db, workspace_id=workspace_id, project_id=project_id)
        require_dev_tests = _project_git_delivery_require_dev_tests(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        require_nontrivial_dev_changes = _project_git_delivery_require_nontrivial_dev_changes(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        team_mode_enabled = _project_has_team_mode_skill(db=db, workspace_id=workspace_id, project_id=project_id)
        if (
            git_delivery_enabled
            and is_developer_role(assignee_role)
            and str(state.get("status") or "").strip() == "Dev"
        ):
            git_evidence = _merge_git_evidence(
                _collect_git_evidence_from_outcome(outcome),
                _collect_git_evidence_from_repo_state(
                    project_name=project_name,
                    project_id=project_id,
                    task_id=run.task_id,
                    title=str(state.get("title") or run.title or ""),
                ),
            )
            contract = (
                dict(outcome.execution_outcome_contract)
                if isinstance(outcome.execution_outcome_contract, dict)
                else {}
            )
            task_branch = str(git_evidence.get("task_branch") or "").strip()
            before_head_sha = str(git_evidence.get("before_head_sha") or "").strip().lower()
            after_head_sha = str(git_evidence.get("after_head_sha") or "").strip().lower()
            after_on_task_branch = bool(git_evidence.get("after_on_task_branch"))
            after_is_dirty = bool(git_evidence.get("after_is_dirty"))
            evidence_missing = not _task_has_git_delivery_completion_evidence(
                state=state,
                summary="",
                comment=None,
            )
            # Deterministic evidence promotion:
            # only promote when executor confirms a new commit on the expected task branch.
            if (
                evidence_missing
                and task_branch
                and after_head_sha
                and before_head_sha
                and after_head_sha != before_head_sha
                and after_on_task_branch
                and not after_is_dirty
            ):
                promoted_refs = _ensure_git_delivery_external_refs(
                    refs=state.get("external_refs"),
                    commit_sha=after_head_sha,
                    task_branch=task_branch,
                )
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=TASK_EVENT_UPDATED,
                    payload={"external_refs": promoted_refs},
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": run.task_id,
                    },
                )
                state = dict(state)
                state["external_refs"] = promoted_refs

            # Deterministic fallback: if contract already provides valid commit/branch
            # evidence, persist it into external_refs before success validation.
            commit_from_contract = str(contract.get("commit_sha") or "").strip().lower()
            branch_from_contract = str(contract.get("branch") or "").strip()
            commit_candidate = (
                commit_from_contract
                if commit_from_contract and bool(_COMMIT_SHA_RE.fullmatch(commit_from_contract))
                else after_head_sha
            )
            branch_candidate = (
                branch_from_contract
                if branch_from_contract and bool(_TASK_BRANCH_RE.fullmatch(branch_from_contract))
                else task_branch
            )
            if commit_candidate and branch_candidate:
                refs = state.get("external_refs")
                has_commit = commit_candidate in _extract_commit_shas_from_refs(refs)
                extracted_branch = _extract_task_branch_from_refs(refs)
                has_branch = bool(extracted_branch and extracted_branch == branch_candidate)
                if not (has_commit and has_branch):
                    promoted_refs = _ensure_git_delivery_external_refs(
                        refs=refs,
                        commit_sha=commit_candidate,
                        task_branch=branch_candidate,
                    )
                    append_event(
                        db,
                        aggregate_type="Task",
                        aggregate_id=run.task_id,
                        event_type=TASK_EVENT_UPDATED,
                        payload={"external_refs": promoted_refs},
                        metadata={
                            "actor_id": actor_user_id,
                            "workspace_id": workspace_id,
                            "project_id": project_id,
                            "task_id": run.task_id,
                        },
                    )
                    state = dict(state)
                    state["external_refs"] = promoted_refs

        contract_error = _validate_execution_outcome_contract(
            outcome=outcome,
            assignee_role=assignee_role,
            task_status=str(state.get("status") or "").strip(),
            git_delivery_enabled=git_delivery_enabled,
            require_dev_tests=require_dev_tests,
            require_nontrivial_dev_changes=require_nontrivial_dev_changes,
            git_evidence=_merge_git_evidence(
                _collect_git_evidence_from_outcome(outcome),
                _collect_git_evidence_from_repo_state(
                    project_name=project_name,
                    project_id=project_id,
                    task_id=run.task_id,
                    title=str(state.get("title") or run.title or ""),
                ),
            ),
        )
        if contract_error:
            raise RuntimeError(contract_error)

        validation_error = success_validation_error(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=run.task_id,
            task_state=state,
            assignee_role=assignee_role,
            action=action,
            summary=summary,
            comment=comment,
            has_git_delivery_skill=git_delivery_enabled,
        )
        if validation_error:
            raise RuntimeError(validation_error)

        queued_blocker_escalations = 0
        queued_qa_handoffs = 0
        queued_initial_developer_dispatches = 0
        action, summary, comment = normalize_success_outcome(
            action=action,
            summary=summary,
            comment=comment,
            instruction=str(run.instruction or "").strip(),
            assignee_role=assignee_role,
            task_state=state,
        )
        if (
            action != "complete"
            and git_delivery_enabled
            and not team_mode_enabled
            and str(state.get("status") or "").strip() != "Done"
            and _task_has_git_delivery_completion_evidence(state=state, summary=summary, comment=comment)
        ):
            action = "complete"

        if _normalize_nonnegative_int(state.get("runner_recover_retry_count")) > 0:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=TASK_EVENT_UPDATED,
                payload={"runner_recover_retry_count": 0},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
            )

        if AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS:
            if action == "complete" and state.get("status") != "Done":
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=TASK_EVENT_COMPLETED,
                    payload={"completed_at": completed_at},
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": run.task_id,
                    },
                )
            if comment:
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=EVENT_COMMENT_ADDED,
                    payload={"task_id": run.task_id, "user_id": actor_user_id, "body": comment},
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": run.task_id,
                    },
                )

        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=run.task_id,
            event_type=EVENT_AUTOMATION_COMPLETED,
            payload={
                "completed_at": completed_at,
                "summary": summary,
                "source_event": EVENT_AUTOMATION_REQUESTED,
                "comment": comment,
                "usage": usage_payload if isinstance(usage_payload, dict) else None,
                "prompt_mode": usage_metadata.get("last_agent_prompt_mode"),
                "prompt_segment_chars": usage_metadata.get("last_agent_prompt_segment_chars"),
                "codex_session_id": usage_metadata.get("last_agent_codex_session_id"),
                "resume_attempted": usage_metadata.get("last_agent_codex_resume_attempted"),
                "resume_succeeded": usage_metadata.get("last_agent_codex_resume_succeeded"),
                "resume_fallback_used": usage_metadata.get("last_agent_codex_resume_fallback_used"),
            },
            metadata={
                "actor_id": actor_user_id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": run.task_id,
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=run.task_id,
            event_type=TASK_EVENT_UPDATED,
            payload={
                "last_agent_stream_status": "Automation run completed.",
                "last_agent_stream_updated_at": completed_at,
                **_team_mode_progress_payload(
                    phase=str(state.get("team_mode_phase") or "").strip()
                    or _derive_team_mode_phase(
                        assignee_role=assignee_role,
                        status=str(state.get("status") or ""),
                    )
                ),
                **usage_metadata,
            },
            metadata={
                "actor_id": actor_user_id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": run.task_id,
            },
        )
        if run.is_scheduled_run:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=EVENT_SCHEDULE_COMPLETED,
                payload={"completed_at": completed_at, "summary": summary},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
            )
            _append_schedule_rearm_update(
                db=db,
                task_id=run.task_id,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                execution_triggers=state.get("execution_triggers"),
                now_utc=now_utc,
            )
        # Smooth execution: for kickoff-dispatched Dev/QA tasks, auto-requeue once if no concrete progress evidence is present.
        current_status = str(state.get("status") or "").strip()
        commit_shas = _extract_commit_shas_from_refs(state.get("external_refs"))
        should_auto_retry = (
            run.request_source == "manual"
            and action == "comment"
            and not _is_noop_ack_comment(comment)
            and (
                (is_developer_role(assignee_role) and current_status == "Dev" and not commit_shas)
                or (
                    is_qa_role(assignee_role)
                    and current_status == "QA"
                    and not bool(state.get("external_refs"))
                )
            )
        )
        if should_auto_retry:
            retry_instruction = str(run.instruction or "").strip()
            if retry_instruction:
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=EVENT_AUTOMATION_REQUESTED,
                    payload={
                        "requested_at": completed_at,
                        "instruction": retry_instruction,
                        "source": "auto_retry",
                    },
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": run.task_id,
                        },
                    )
        is_team_mode_kickoff_run = bool(
            team_mode_enabled
            and is_lead_role(assignee_role)
            and _is_classified_team_mode_kickoff(state=state, run=run)
        )
        if is_team_mode_kickoff_run:
            queued_initial_developer_dispatches = _queue_initial_team_mode_developer_tasks_after_kickoff(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                kickoff_task_id=run.task_id,
            )
        if (
            team_mode_enabled
            and is_developer_role(assignee_role)
            and str(state.get("status") or "").strip() == "Dev"
            and _task_has_git_delivery_completion_evidence(state=state, summary=summary, comment=comment)
        ):
            transitioned = _append_task_status_transition_if_allowed(
                db=db,
                task_id=run.task_id,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                actor_role=assignee_role,
                from_status="Dev",
                to_status="Lead",
            )
            if transitioned:
                state = dict(state)
                state["status"] = "Lead"
                queued_followup_developer_dispatches = _queue_team_mode_dispatches(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    source="runner_orchestrator",
                    exclude_task_ids={run.task_id},
                    allowed_roles={"Developer"},
                )
        if (
            team_mode_enabled
            and git_delivery_enabled
            and canonicalize_role(assignee_role) == "Lead"
            and str(state.get("status") or "").strip() == "Lead"
            and not is_team_mode_kickoff_run
        ):
            merge_result = _merge_ready_developer_branches_to_main(
                db=db,
                workspace_id=workspace_id,
                project_id=str(project_id or "").strip(),
                actor_user_id=actor_user_id,
            )
            if not bool(merge_result.get("ok")):
                raise RuntimeError(str(merge_result.get("error") or "Runner error: deterministic merge to main failed."))
            if not _project_has_merge_to_main_evidence(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            ):
                raise RuntimeError(
                    "Lead handoff is blocked: merge-to-main evidence is missing after deterministic merge cycle."
                )
            stack, port, health_path, runtime_required = _project_runtime_deploy_target(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            runtime_check_ok = True
            if runtime_required and port is None:
                raise RuntimeError(
                    "Lead deploy gate failed: runtime_deploy_health.port is required but missing."
                )
            manifest_path = find_project_compose_manifest(
                project_name=project_name,
                project_id=str(project_id or "").strip() or None,
            )
            if runtime_required and manifest_path is None:
                synthesis = _synthesize_runtime_deploy_assets(
                    project_name=project_name,
                    project_id=str(project_id or "").strip() or None,
                    port=int(port),
                    health_path=health_path,
                )
                if not bool(synthesis.get("ok")):
                    raise RuntimeError(
                        "Lead deploy gate failed: compose manifest is missing and deterministic synthesis failed. "
                        + str(synthesis.get("error") or "").strip()
                    )
                manifest_path_raw = str(synthesis.get("manifest_path") or "").strip()
                if not manifest_path_raw:
                    raise RuntimeError(
                        "Lead deploy gate failed: deterministic synthesis did not return a compose manifest path."
                    )
                manifest_path = Path(manifest_path_raw)
                state = dict(state)
                state["last_deploy_execution"] = {
                    "manifest_path": manifest_path_raw,
                    "runtime_type": str(synthesis.get("runtime_type") or "").strip() or None,
                    "synthesized": True,
                    "synthesized_files": list(synthesis.get("created_files") or []),
                    "synthesis_commit_sha": str(synthesis.get("commit_sha") or "").strip() or None,
                }
            if runtime_required and manifest_path is not None:
                repo_root = resolve_project_repository_path(
                    project_name=str(project_name or "").strip() or None,
                    project_id=str(project_id or "").strip() or None,
                )
                code_deploy, _out_deploy, err_deploy = _run_docker_compose_up_with_error(
                    cwd=repo_root,
                    stack=stack,
                )
                if code_deploy != 0:
                    raise RuntimeError(
                        "Lead deploy execution failed: docker compose up -d did not succeed. "
                        + str(err_deploy or "")[:240]
                    )
            if runtime_required and port is not None:
                runtime_check = run_runtime_deploy_health_check(
                    stack=stack,
                    port=port,
                    health_path=health_path,
                    require_http_200=True,
                    host=None,
                )
                deploy_refs = _append_lead_deploy_external_refs(
                    refs=state.get("external_refs"),
                    stack=stack,
                    port=port,
                    health_path=health_path,
                    runtime_ok=bool(runtime_check.get("ok")),
                    http_url=str(runtime_check.get("http_url") or "").strip() or None,
                    http_status=int(runtime_check.get("http_status") or 0) if runtime_check.get("http_status") is not None else None,
                    project_name=str(project_name or "").strip() or None,
                    project_id=str(project_id or "").strip() or None,
                )
                deploy_snapshot = dict(state.get("last_deploy_execution") or {})
                deploy_snapshot.update(
                    {
                        "executed_at": completed_at,
                        "stack": stack,
                        "port": int(port),
                        "health_path": health_path,
                        "command": f"docker compose -p {stack} up -d",
                        "manifest_path": str(manifest_path),
                        "runtime_type": deploy_snapshot.get("runtime_type")
                        or _derive_runtime_deploy_markers(
                            project_name=str(project_name or "").strip() or None,
                            project_id=str(project_id or "").strip() or None,
                        )[0],
                        "runtime_ok": bool(runtime_check.get("ok")),
                        "http_url": str(runtime_check.get("http_url") or "").strip() or None,
                        "http_status": int(runtime_check.get("http_status") or 0) if runtime_check.get("http_status") is not None else None,
                        "synthesized": bool(deploy_snapshot.get("synthesized")),
                        "synthesized_files": list(deploy_snapshot.get("synthesized_files") or []),
                        "synthesis_commit_sha": str(deploy_snapshot.get("synthesis_commit_sha") or "").strip() or None,
                    }
                )
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=TASK_EVENT_UPDATED,
                    payload={"external_refs": deploy_refs, "last_deploy_execution": deploy_snapshot},
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": run.task_id,
                    },
                )
                state = dict(state)
                state["external_refs"] = deploy_refs
                state["last_deploy_execution"] = deploy_snapshot
                state["team_mode_phase"] = "deploy"
                runtime_check_ok = bool(runtime_check.get("ok"))
                if not runtime_check_ok:
                    runtime_error = str(runtime_check.get("error") or "").strip()
                    raise RuntimeError(
                        "Lead deploy gate failed: runtime health check did not pass "
                        f"(stack={stack}, port={int(port)}, path={health_path})"
                        + (f"; error={runtime_error}" if runtime_error else "")
                    )

            lead_handoff_at = completed_at
            lead_handoff_token = f"lead:{run.task_id}:{lead_handoff_at}"
            handoff_refs = _collect_handoff_refs_from_tasks(
                db=db,
                task_ids=[run.task_id, *[str(item or "").strip() for item in (merge_result.get("merged_task_ids") or [])]],
            )
            queued_qa_handoffs = _queue_qa_handoff_requests(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                lead_task_id=run.task_id,
                actor_user_id=actor_user_id,
                lead_handoff_token=lead_handoff_token,
                lead_handoff_at=lead_handoff_at,
                lead_handoff_refs=handoff_refs,
            )
            if queued_qa_handoffs <= 0:
                raise RuntimeError(
                    "Lead handoff failed: no runnable QA task was queued after merge/deploy cycle."
                )
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=TASK_EVENT_UPDATED,
                payload={
                    **_team_mode_progress_payload(phase="handoff_qa"),
                    "last_deploy_execution": state.get("last_deploy_execution"),
                    "last_lead_handoff_token": lead_handoff_token,
                    "last_lead_handoff_at": lead_handoff_at,
                    "last_lead_handoff_refs_json": handoff_refs,
                    "last_lead_handoff_deploy_execution": state.get("last_deploy_execution"),
                },
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
            )
            state = dict(state)
            state["team_mode_phase"] = "handoff_qa"
            state["last_lead_handoff_token"] = lead_handoff_token
            state["last_lead_handoff_at"] = lead_handoff_at
            state["last_lead_handoff_refs_json"] = handoff_refs
            state["last_lead_handoff_deploy_execution"] = state.get("last_deploy_execution")

        if is_blocker_source_role(assignee_role) and str(
            state.get("status") or ""
        ).strip() == "Blocked":
            queued_blocker_escalations = _enqueue_team_lead_blocker_escalation(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                blocked_task_id=run.task_id,
                blocked_title=str(state.get("title") or ""),
                blocked_role=assignee_role,
                blocked_status="Blocked",
                blocked_error=str(comment or summary or "").strip() or None,
            )
        _requeue_pending_status_change_request(
            db=db,
            run=run,
            state=state,
            workspace_id=workspace_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            requested_at_iso=completed_at,
        )
        if _is_blocked_outcome(summary=summary, comment=comment):
            _notify_humans_blocked(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                task_id=run.task_id,
                task_title=str(state.get("title") or run.title or ""),
                task_status=str(state.get("status") or run.status or ""),
                summary=summary,
                comment=comment,
            )
        if action == "complete":
            _notify_humans_project_completed(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
            )
        db.commit()
    if (
        queued_blocker_escalations > 0
        or queued_qa_handoffs > 0
        or queued_initial_developer_dispatches > 0
        or queued_followup_developer_dispatches > 0
    ):
        wake_automation_runner()


def _record_automation_failure(run: QueuedAutomationRun, error: Exception) -> None:
    failed_at = to_iso_utc(datetime.now(timezone.utc))
    now_utc = datetime.now(timezone.utc)
    transient_interruption = _is_transient_runner_interruption(error)
    recoverable_failure = _is_recoverable_failure(error)
    with SessionLocal() as db:
        state, _ = rebuild_state(db, "Task", run.task_id)
        workspace_id = str(state.get("workspace_id") or run.workspace_id or "").strip()
        if not workspace_id:
            return
        project_id = str(state.get("project_id") or run.project_id or "").strip() or None
        actor_user_id = _resolve_task_actor_user_id(
            db=db,
            task_id=run.task_id,
            state=state,
            fallback_actor_user_id=run.actor_user_id,
        )
        assignee_role = _resolve_assignee_project_role(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            assignee_id=str(state.get("assignee_id") or ""),
            assigned_agent_code=str(state.get("assigned_agent_code") or ""),
            task_labels=state.get("labels"),
            task_status=str(state.get("status") or ""),
        )
        retry_count = _normalize_nonnegative_int(state.get("runner_recover_retry_count"))
        should_retry = transient_interruption or (recoverable_failure and retry_count < _MAX_RECOVERABLE_RETRIES)
        non_blocking_gate_failure = _is_non_blocking_team_mode_gate_error(error)
        if non_blocking_gate_failure:
            gate_key = _current_nonblocking_gate_key(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                assignee_role=assignee_role,
                task_status=str(state.get("status") or run.status or ""),
                task_state=state,
            )
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=EVENT_AUTOMATION_COMPLETED,
                payload={"completed_at": failed_at, "summary": "Automation deferred by workflow gate."},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
            )
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=TASK_EVENT_UPDATED,
                payload={
                    "last_agent_stream_status": "Automation deferred: waiting for workflow handoff.",
                    "last_agent_stream_updated_at": failed_at,
                    **_team_mode_progress_payload(
                        phase=_derive_team_mode_phase(
                            assignee_role=assignee_role,
                            status=str(state.get("status") or run.status or ""),
                        ),
                        blocking_gate=gate_key,
                        blocked_reason=str(error),
                        blocked_at=failed_at,
                    ),
                },
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
            )
            db.commit()
            return
        handoff_assignee_id: str | None = None
        if (
            AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS
            and is_blocker_source_role(assignee_role)
            and str(state.get("status") or "").strip() != "Blocked"
            and not should_retry
            and not non_blocking_gate_failure
        ):
            transitioned = _append_task_status_transition_if_allowed(
                db=db,
                task_id=run.task_id,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                actor_role=assignee_role,
                from_status=str(state.get("status") or "").strip(),
                to_status="Blocked",
            )
            if transitioned:
                state = dict(state)
                state["status"] = "Blocked"
        queued_blocker_escalations = 0
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=run.task_id,
            event_type=EVENT_AUTOMATION_FAILED,
            payload={"failed_at": failed_at, "error": str(error), "summary": "Automation runner failed."},
            metadata={
                "actor_id": actor_user_id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": run.task_id,
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=run.task_id,
            event_type=TASK_EVENT_UPDATED,
            payload={
                "last_agent_stream_status": "Automation run failed.",
                "last_agent_stream_updated_at": failed_at,
                **_team_mode_progress_payload(
                    phase=str(state.get("team_mode_phase") or "").strip()
                    or _derive_team_mode_phase(
                        assignee_role=assignee_role,
                        status=str(state.get("status") or run.status or ""),
                    )
                ),
            },
            metadata={
                "actor_id": actor_user_id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": run.task_id,
            },
        )
        schedule_state = str(state.get("schedule_state") or "").strip().lower()
        if run.is_scheduled_run or schedule_state in {"queued", "running"}:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=EVENT_SCHEDULE_FAILED,
                payload={"failed_at": failed_at, "error": str(error)},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
            )
            _append_schedule_rearm_update(
                db=db,
                task_id=run.task_id,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                execution_triggers=state.get("execution_triggers"),
                now_utc=now_utc,
            )
        if should_retry:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=TASK_EVENT_UPDATED,
                payload={"runner_recover_retry_count": retry_count + 1},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
            )
            retry_instruction = (
                str(run.instruction or "").strip()
                or str(state.get("instruction") or "").strip()
                or str(state.get("scheduled_instruction") or "").strip()
            )
            if retry_instruction:
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=EVENT_AUTOMATION_REQUESTED,
                    payload={
                        "requested_at": failed_at,
                        "instruction": retry_instruction,
                        "source": (
                            "runner_recover_after_interrupt"
                            if transient_interruption
                            else "runner_recover_after_failure"
                        ),
                    },
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": run.task_id,
                    },
                )
        if (
            not should_retry
            and not non_blocking_gate_failure
            and is_blocker_source_role(assignee_role)
        ):
            handoff_assignee_id = _handoff_failed_task_to_human(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=run.task_id,
                state=state,
                actor_user_id=actor_user_id,
                failed_at_iso=failed_at,
                failure_reason=str(error),
            )
        _requeue_pending_status_change_request(
            db=db,
            run=run,
            state=state,
            workspace_id=workspace_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            requested_at_iso=failed_at,
        )
        if is_blocker_source_role(assignee_role) and not non_blocking_gate_failure:
            if not should_retry:
                queued_blocker_escalations = _enqueue_team_lead_blocker_escalation(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    blocked_task_id=run.task_id,
                    blocked_title=str(state.get("title") or ""),
                    blocked_role=assignee_role,
                    blocked_status=str(state.get("status") or "").strip() or "Blocked",
                    blocked_error=str(error),
                )
        if not should_retry and not non_blocking_gate_failure:
            handoff_suffix = (
                f"\nHuman handoff assigned to: {handoff_assignee_id}."
                if str(handoff_assignee_id or "").strip()
                else ""
            )
            _notify_humans_blocked(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                task_id=run.task_id,
                task_title=str(state.get("title") or run.title or ""),
                task_status=str(state.get("status") or run.status or ""),
                summary="Automation runner failed.",
                comment=f"{str(error)}{handoff_suffix}",
            )
        db.commit()
    if queued_blocker_escalations > 0:
        wake_automation_runner()


def _preflight_automation_error(run: QueuedAutomationRun) -> str | None:
    with SessionLocal() as db:
        state, _ = rebuild_state(db, "Task", run.task_id)
        workspace_id = str(state.get("workspace_id") or run.workspace_id or "").strip()
        if not workspace_id:
            return None
        project_id = str(state.get("project_id") or run.project_id or "").strip() or None
        if _is_classified_team_mode_kickoff(state=state, run=run):
            return None
        assignee_role = _resolve_assignee_project_role(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            assignee_id=str(state.get("assignee_id") or ""),
            assigned_agent_code=str(state.get("assigned_agent_code") or ""),
            task_labels=state.get("labels"),
            task_status=str(state.get("status") or ""),
        )
        if (
            is_qa_role(assignee_role)
            and str(state.get("status") or "").strip() == "QA"
        ):
            gate_key = _current_nonblocking_gate_key(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                assignee_role=assignee_role,
                task_status=str(state.get("status") or "").strip(),
                task_state=state,
            )
            if gate_key == "qa_waiting_current_deploy_cycle":
                return (
                    "QA automation is gated until Lead handoff is complete for the current deploy cycle; "
                    "at least one Lead task has a newer deploy execution than the last QA handoff."
                )
            if gate_key == "qa_waiting_lead_handoff":
                return (
                    "QA automation is gated until Lead handoff is complete; "
                    "at least one Lead task is still in Lead status."
                )
        if (
            is_lead_role(assignee_role)
            and str(state.get("status") or "").strip() == "Lead"
        ):
            gate_key = _current_nonblocking_gate_key(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                assignee_role=assignee_role,
                task_status=str(state.get("status") or "").strip(),
                task_state=state,
            )
            if gate_key == "lead_waiting_merge_ready_developer":
                return (
                    "Lead automation is gated until merge-ready Developer output exists; "
                    "do not evaluate compose/deploy gates before a Developer handoff produces merge-to-main evidence."
                )
        if (
            is_lead_role(assignee_role)
            and str(state.get("status") or "").strip() == "Lead"
            and _project_requires_runtime_deploy_health(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
        ):
            _stack, runtime_port, _health_path, _required = _project_runtime_deploy_target(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            if runtime_port is None:
                return (
                    "Lead deployment preflight failed: docker_compose.runtime_deploy_health.port is not configured. "
                    "Set an explicit port before running Lead deploy automation."
                )
        return plugin_preflight_error(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            task_status=str(state.get("status") or "").strip() or None,
            assignee_role=assignee_role,
            has_git_delivery_skill=_project_has_git_delivery_skill(db=db, workspace_id=workspace_id, project_id=project_id),
            has_repo_context=_project_has_repo_context(db=db, workspace_id=workspace_id, project_id=project_id),
        )


def _execute_claimed_automation(run: QueuedAutomationRun) -> None:
    preflight_error = _preflight_automation_error(run)
    if preflight_error:
        _record_automation_failure(run, RuntimeError(preflight_error))
        return
    resume_codex_session_id: str | None = None
    with SessionLocal() as db:
        state, _ = rebuild_state(db, "Task", run.task_id)
        existing_codex_session_id = str(state.get("last_agent_codex_session_id") or "").strip()
        resume_attempted = _coerce_bool(state.get("last_agent_codex_resume_attempted"))
        resume_last_succeeded = _coerce_bool(state.get("last_agent_codex_resume_succeeded"))
        resume_blocked = resume_attempted is True and resume_last_succeeded is False
        if existing_codex_session_id and not resume_blocked:
            resume_codex_session_id = existing_codex_session_id
    stream_lock = threading.Lock()
    stream_text = ""
    stream_status = ""
    last_flush_at = 0.0

    def _persist_stream_progress(*, force: bool = False) -> None:
        nonlocal last_flush_at, stream_text, stream_status
        now_monotonic = time.monotonic()
        if not force and (now_monotonic - last_flush_at) < _AUTOMATION_STREAM_FLUSH_INTERVAL_SECONDS:
            return
        last_flush_at = now_monotonic
        with stream_lock:
            progress = stream_text[-_AUTOMATION_STREAM_PROGRESS_MAX_CHARS:]
            status_text = stream_status
        now_iso = to_iso_utc(datetime.now(timezone.utc))
        with SessionLocal() as db:
            state, _ = rebuild_state(db, "Task", run.task_id)
            workspace_id = str(state.get("workspace_id") or run.workspace_id or "").strip()
            if not workspace_id:
                return
            project_id = str(state.get("project_id") or run.project_id or "").strip() or None
            actor_user_id = _resolve_task_actor_user_id(
                db=db,
                task_id=run.task_id,
                state=state,
                fallback_actor_user_id=run.actor_user_id,
            )
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=TASK_EVENT_UPDATED,
                payload={
                    "last_agent_progress": progress,
                    "last_agent_stream_status": status_text or None,
                    "last_agent_stream_updated_at": now_iso,
                },
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
            )
            db.commit()

    def _on_stream_event(event: dict[str, object]) -> None:
        nonlocal stream_text, stream_status
        event_type = str(event.get("type") or "").strip()
        if event_type == "assistant_text":
            delta = str(event.get("delta") or "")
            if not delta:
                return
            with stream_lock:
                stream_text = (stream_text + delta)[-_AUTOMATION_STREAM_PROGRESS_MAX_CHARS:]
            _persist_stream_progress(force=False)
            return
        if event_type == "status":
            message = str(event.get("message") or "").strip()
            if not message:
                return
            if message in _AUTOMATION_STREAM_NOISY_STATUS_MESSAGES:
                return
            with stream_lock:
                stream_status = message
                stream_text = (f"{stream_text}\n\n{message}".strip())[-_AUTOMATION_STREAM_PROGRESS_MAX_CHARS:]
            _persist_stream_progress(force=True)

    try:
        if not run.instruction:
            raise RuntimeError("instruction is empty")
        outcome = execute_task_automation(
            task_id=run.task_id,
            title=run.title,
            description=run.description,
            status=run.status,
            instruction=run.instruction,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            actor_user_id=run.actor_user_id,
            trigger_task_id=run.trigger_task_id,
            trigger_from_status=run.trigger_from_status,
            trigger_to_status=run.trigger_to_status,
            trigger_timestamp=run.triggered_at,
            execution_kickoff_intent=run.execution_kickoff_intent,
            workflow_scope=run.workflow_scope,
            execution_mode=run.execution_mode,
            task_completion_requested=run.task_completion_requested,
            codex_session_id=resume_codex_session_id,
            allow_mutations=True,
            prompt_instruction_segments={"user_instruction": len(run.instruction)},
            on_event=_on_stream_event,
            stream_plain_text=True,
        )
        _persist_stream_progress(force=True)
    except Exception as exc:
        _persist_stream_progress(force=True)
        _record_automation_failure(run, exc)
        return

    try:
        _record_automation_success(
            run,
            outcome=outcome,
        )
    except Exception as exc:
        _record_automation_failure(run, exc)


def run_queued_automation_once(limit: int = 10, *, allow_fresh_kickoff: bool = False) -> int:
    normalized_limit = max(1, int(limit))
    scan_limit = max(normalized_limit * 50, normalized_limit, AGENT_RUNNER_MAX_CONCURRENCY * 20)
    queued_event_task_ids: list[str] = []
    with SessionLocal() as db:
        try:
            from shared.models import StoredEvent

            queued_event_task_ids = db.execute(
                select(StoredEvent.aggregate_id)
                .where(
                    StoredEvent.aggregate_type == "Task",
                    StoredEvent.event_type == EVENT_AUTOMATION_REQUESTED,
                )
                .order_by(StoredEvent.occurred_at.desc())
                .limit(scan_limit)
            ).scalars().all()
        except Exception:
            queued_event_task_ids = []
        candidate_ids = db.execute(
            select(Task.id).where(Task.is_deleted == False).order_by(Task.updated_at.desc()).limit(scan_limit)
        ).scalars().all()
    ordered_ids: list[str] = []
    seen_ids: set[str] = set()
    for task_id in [*queued_event_task_ids, *candidate_ids]:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id or normalized_task_id in seen_ids:
            continue
        seen_ids.add(normalized_task_id)
        ordered_ids.append(normalized_task_id)

    claimed_runs: list[QueuedAutomationRun] = []
    for task_id in ordered_ids:
        claimed = _claim_queued_task(task_id, allow_fresh_kickoff=allow_fresh_kickoff)
        if claimed is None:
            continue
        claimed_runs.append(claimed)
        if len(claimed_runs) >= normalized_limit:
            break
    if not claimed_runs:
        return 0

    max_workers = max(1, min(int(AGENT_RUNNER_MAX_CONCURRENCY), normalized_limit, len(claimed_runs)))
    if max_workers == 1:
        for run in claimed_runs:
            _execute_claimed_automation(run)
        return len(claimed_runs)

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="automation-runner") as pool:
        futures = [pool.submit(_execute_claimed_automation, run) for run in claimed_runs]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                # Individual worker errors are handled inside _execute_claimed_automation.
                continue
    return len(claimed_runs)


def queue_satisfied_external_status_triggers_once(limit: int = 20) -> int:
    queued = 0
    now_iso = to_iso_utc(datetime.now(timezone.utc))
    with SessionLocal() as db:
        candidate_tasks = db.execute(
            select(Task)
            .where(
                Task.is_deleted == False,  # noqa: E712
                Task.archived == False,  # noqa: E712
                Task.execution_triggers.ilike("%status_change%"),
            )
            .order_by(Task.updated_at.asc())
            .limit(max(limit * 20, limit))
        ).scalars().all()
        workspace_cache: dict[str, list[dict[str, object]]] = {}

        def _workspace_states(workspace_id: str) -> list[dict[str, object]]:
            if workspace_id not in workspace_cache:
                rows = db.execute(
                    select(Task).where(
                        Task.workspace_id == workspace_id,
                        Task.is_deleted == False,  # noqa: E712
                        Task.archived == False,  # noqa: E712
                    )
                ).scalars().all()
                workspace_cache[workspace_id] = [_task_state_for_selector(row) for row in rows]
            return workspace_cache[workspace_id]

        for task in candidate_tasks:
            if queued >= limit:
                break
            task_id = str(task.id or "").strip()
            if not task_id:
                continue
            workspace_id = str(task.workspace_id or "").strip()
            project_id = str(task.project_id or "").strip() or None
            if not workspace_id or not project_id:
                continue
            if not _project_has_team_mode_skill(db=db, workspace_id=workspace_id, project_id=project_id):
                continue
            if not _project_team_mode_execution_enabled(db=db, workspace_id=workspace_id, project_id=project_id):
                continue

            state, _ = rebuild_state(db, "Task", task_id)
            if str(state.get("automation_state") or "idle").strip() in {"queued", "running"}:
                continue
            instruction = (
                str(state.get("instruction") or "").strip()
                or str(state.get("scheduled_instruction") or "").strip()
            )
            if not instruction:
                continue

            triggers = normalize_execution_triggers(state.get("execution_triggers"))
            if not triggers:
                continue
            task_states = _workspace_states(workspace_id)
            for trigger in triggers:
                if str(trigger.get("kind") or "") != TRIGGER_KIND_STATUS_CHANGE:
                    continue
                if not bool(trigger.get("enabled", True)):
                    continue
                if str(trigger.get("scope") or "").strip().lower() != STATUS_SCOPE_EXTERNAL:
                    continue
                action = _normalize_status_change_action(trigger.get("action"))
                if not _is_cross_task_automation_action(action):
                    continue
                # Reconcile only triggers defined by destination status. Transition-source constraints
                # cannot be safely inferred without a concrete status-change event.
                if _normalize_string_list(trigger.get("from_statuses")):
                    continue
                to_statuses = _normalize_string_list(trigger.get("to_statuses"))
                if not to_statuses:
                    continue
                allowed_statuses = {value.casefold() for value in to_statuses}

                selector = trigger.get("selector")
                selected_sources = [
                    item
                    for item in task_states
                    if str(item.get("id") or "").strip() != task_id and selector_matches_task(task_state=item, selector=selector)
                ]
                if not selected_sources:
                    continue
                satisfied_sources = [
                    item
                    for item in selected_sources
                    if str(item.get("status") or "").strip().casefold() in allowed_statuses
                ]
                match_mode = str(trigger.get("match_mode") or "").strip().lower()
                if match_mode == STATUS_MATCH_ALL:
                    if len(satisfied_sources) != len(selected_sources):
                        continue
                    trigger_source = satisfied_sources[0]
                else:
                    if not satisfied_sources:
                        continue
                    trigger_source = satisfied_sources[0]

                trigger_task_id = str(trigger_source.get("id") or "").strip() or None
                trigger_to_status = str(trigger_source.get("status") or "").strip() or None
                last_source = str(state.get("last_requested_source") or "").strip().lower()
                last_trigger_task_id = str(state.get("last_requested_trigger_task_id") or "").strip()
                last_to_status = str(state.get("last_requested_to_status") or "").strip()
                if (
                    last_source in {"status_change", "trigger_reconcile"}
                    and last_trigger_task_id
                    and trigger_task_id
                    and last_trigger_task_id == trigger_task_id
                    and (not trigger_to_status or last_to_status.casefold() == trigger_to_status.casefold())
                ):
                    continue

                actor_user_id = _resolve_task_actor_user_id(db=db, task_id=task_id, state=state)
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=task_id,
                    event_type=EVENT_AUTOMATION_REQUESTED,
                    payload={
                        "requested_at": now_iso,
                        "instruction": instruction,
                        "source": "trigger_reconcile",
                        "trigger_task_id": trigger_task_id,
                        "from_status": None,
                        "to_status": trigger_to_status,
                        "triggered_at": str(trigger_source.get("updated_at") or now_iso),
                    },
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": task_id,
                        "trigger_task_id": trigger_task_id,
                        "trigger_to_status": trigger_to_status,
                    },
                )
                db.commit()
                queued += 1
                break
    return queued


def _eligible_for_team_mode_auto_queue(
    state: dict[str, object],
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    assignee_role: str | None,
    now_utc: datetime,
    cooldown_seconds: int = 45,
) -> bool:
    automation_state = str(state.get("automation_state") or "idle").strip().lower()
    if automation_state in {"queued", "running"}:
        return False
    if automation_state not in {"idle", "failed", "completed"}:
        return False
    previous_blocking_gate = str(state.get("team_mode_blocking_gate") or state.get("runner_gate_defer_key") or "").strip()
    if previous_blocking_gate:
        current_defer_key = _current_nonblocking_gate_key(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            assignee_role=assignee_role,
            task_status=str(state.get("status") or ""),
            task_state=state,
        )
        if current_defer_key and current_defer_key == previous_blocking_gate:
            return False
    # Require an explicit kickoff/manual automation signal before background happy-path
    # queueing is allowed. Fresh setup-only projects should stay idle until user starts execution.
    if not str(state.get("last_requested_at") or "").strip() and not str(state.get("last_agent_run_at") or "").strip():
        return False
    last_requested = _parse_iso_timestamp(state.get("last_requested_at"))
    if last_requested is None:
        return True
    return (now_utc - last_requested).total_seconds() >= float(max(5, cooldown_seconds))


def queue_team_mode_happy_path_once(limit: int = 20) -> int:
    queued = 0
    now_utc = datetime.now(timezone.utc)
    with SessionLocal() as db:
        team_mode_projects = db.execute(
            select(ProjectPluginConfig.project_id)
            .where(
                ProjectPluginConfig.plugin_key == "team_mode",
                ProjectPluginConfig.enabled == True,  # noqa: E712
                ProjectPluginConfig.is_deleted == False,  # noqa: E712
            )
            .distinct()
        ).scalars().all()
        for project_id in [str(item or "").strip() for item in team_mode_projects if str(item or "").strip()]:
            if queued >= limit:
                break
            project = db.get(Project, project_id)
            if project is None or bool(getattr(project, "is_deleted", False)):
                continue
            workspace_id = str(project.workspace_id or "").strip()
            if not workspace_id:
                continue
            if not _project_team_mode_execution_enabled(db=db, workspace_id=workspace_id, project_id=project_id):
                continue

            member_role_by_user_id = {
                str(user_id): str(role or "").strip()
                for user_id, role in db.execute(
                    select(ProjectMember.user_id, ProjectMember.role).where(
                        ProjectMember.workspace_id == workspace_id,
                        ProjectMember.project_id == project_id,
                    )
                ).all()
            }
            rows = db.execute(
                select(Task)
                .where(
                    Task.workspace_id == workspace_id,
                    Task.project_id == project_id,
                    Task.is_deleted == False,  # noqa: E712
                    Task.archived == False,  # noqa: E712
                    Task.status != "Done",
                )
                .order_by(Task.created_at.asc())
            ).scalars().all()
            if not rows:
                continue

            runnable_by_id: dict[str, tuple[Task, dict[str, object]]] = {}
            orchestrator_rows: list[dict[str, str]] = []

            for task in rows:
                state, _ = rebuild_state(db, "Task", str(task.id))
                normalized_role = derive_task_role(
                    task_like={
                        "assignee_id": str(task.assignee_id or "").strip(),
                        "assigned_agent_code": str(task.assigned_agent_code or "").strip(),
                        "labels": state.get("labels", task.labels),
                        "status": str(state.get("status") or task.status or "").strip(),
                    },
                    member_role_by_user_id=member_role_by_user_id,
                )
                normalized_status = str(state.get("status") or task.status or "").strip()
                if normalized_role not in TEAM_MODE_WORKFLOW_ROLES:
                    continue

                if not _eligible_for_team_mode_auto_queue(
                    state,
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    assignee_role=normalized_role,
                    now_utc=now_utc,
                ):
                    continue
                instruction = (
                    str(state.get("instruction") or "").strip()
                    or str(state.get("scheduled_instruction") or "").strip()
                )
                if not instruction:
                    continue
                task_id = str(task.id or "").strip()
                if not task_id:
                    continue
                runnable_by_id[task_id] = (task, state)
                orchestrator_rows.append(
                    {
                        "id": task_id,
                        "role": normalized_role,
                        "status": normalized_status,
                        "instruction": str(state.get("instruction") or "").strip(),
                        "scheduled_instruction": str(state.get("scheduled_instruction") or "").strip(),
                    }
                )

            plan = plan_next_runnable_tasks(orchestrator_rows)
            to_queue: list[tuple[Task, dict[str, object]]] = [
                runnable_by_id[task_id]
                for task_id in list(plan.get("queue_task_ids") or [])
                if task_id in runnable_by_id
            ]

            from features.tasks.application import TaskApplicationService
            from shared.core import TaskAutomationRun

            for task, state in to_queue:
                if queued >= limit:
                    break
                task_id = str(task.id or "").strip()
                if not task_id:
                    continue
                actor_user_id = _resolve_task_actor_user_id(db=db, task_id=task_id, state=state)
                actor = db.get(UserModel, actor_user_id)
                if actor is None or not bool(getattr(actor, "is_active", False)):
                    continue
                instruction = (
                    str(state.get("instruction") or "").strip()
                    or str(state.get("scheduled_instruction") or "").strip()
                )
                if not instruction:
                    continue
                command_id = f"tm-orch-{project_id[:8]}-{task_id[:8]}-{int(now_utc.timestamp())}"
                try:
                    TaskApplicationService(db, actor, command_id=command_id).request_automation_run(
                        task_id,
                        TaskAutomationRun(instruction=instruction, source="runner_orchestrator"),
                        wake_runner=False,
                    )
                except Exception:
                    continue
                queued += 1
            db.commit()
    return queued


def closeout_team_mode_tasks_once(limit: int = 20) -> int:
    completed = 0
    now_utc = datetime.now(timezone.utc)
    with SessionLocal() as db:
        team_mode_projects = db.execute(
            select(ProjectPluginConfig.project_id)
            .where(
                ProjectPluginConfig.plugin_key == "team_mode",
                ProjectPluginConfig.enabled == True,  # noqa: E712
                ProjectPluginConfig.is_deleted == False,  # noqa: E712
            )
            .distinct()
        ).scalars().all()
        from features.agents.service import AgentTaskService

        for project_id in [str(item or "").strip() for item in team_mode_projects if str(item or "").strip()]:
            if completed >= limit:
                break
            project = db.get(Project, project_id)
            if project is None or bool(getattr(project, "is_deleted", False)):
                continue
            workspace_id = str(project.workspace_id or "").strip()
            if not workspace_id:
                continue
            if not _project_team_mode_execution_enabled(db=db, workspace_id=workspace_id, project_id=project_id):
                continue

            try:
                verification = AgentTaskService(
                    require_token=False,
                    actor_user_id=AGENT_SYSTEM_USER_ID,
                ).verify_delivery_workflow(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    auth_token=MCP_AUTH_TOKEN or None,
                )
            except Exception:
                continue
            if not bool((verification or {}).get("ok")):
                continue

            member_role_by_user_id = {
                str(user_id): str(role or "").strip()
                for user_id, role in db.execute(
                    select(ProjectMember.user_id, ProjectMember.role).where(
                        ProjectMember.workspace_id == workspace_id,
                        ProjectMember.project_id == project_id,
                    )
                ).all()
            }
            rows = db.execute(
                select(Task)
                .where(
                    Task.workspace_id == workspace_id,
                    Task.project_id == project_id,
                    Task.is_deleted == False,  # noqa: E712
                    Task.archived == False,  # noqa: E712
                    Task.status != "Done",
                )
                .order_by(Task.created_at.asc())
            ).scalars().all()
            if not rows:
                continue

            lead_rows_count = 0
            ordered_candidates: list[tuple[Task, str, dict[str, object]]] = []
            priority = {"Developer": 0, "QA": 1, "Lead": 2}
            for task in rows:
                state, _ = rebuild_state(db, "Task", str(task.id))
                normalized_role = derive_task_role(
                    task_like={
                        "assignee_id": str(task.assignee_id or "").strip(),
                        "assigned_agent_code": str(task.assigned_agent_code or "").strip(),
                        "labels": state.get("labels", task.labels),
                        "status": str(state.get("status") or task.status or "").strip(),
                    },
                    member_role_by_user_id=member_role_by_user_id,
                )
                if normalized_role not in TEAM_MODE_WORKFLOW_ROLES:
                    continue
                if normalized_role == "Lead":
                    lead_rows_count += 1
                ordered_candidates.append((task, normalized_role, state))
            ordered_candidates.sort(key=lambda item: priority.get(item[1], 99))

            for task, role, state in ordered_candidates:
                if completed >= limit:
                    break
                task_id = str(task.id or "").strip()
                if not task_id:
                    continue
                automation_state = str(state.get("automation_state") or "idle").strip().lower()
                if automation_state in {"queued", "running"}:
                    continue
                if role == "Lead" and lead_rows_count > 1 and is_recurring_oversight_task(state):
                    # Keep long-running oversight tasks active when there is a dedicated deploy Lead task.
                    continue
                actor_user_id = _resolve_task_actor_user_id(
                    db=db,
                    task_id=task_id,
                    state=state,
                    fallback_actor_user_id=AGENT_SYSTEM_USER_ID,
                )
                actor = db.get(UserModel, actor_user_id)
                if actor is None or not bool(getattr(actor, "is_active", False)):
                    continue
                command_id = f"tm-close-{project_id[:8]}-{task_id[:8]}-{int(now_utc.timestamp())}"
                try:
                    AgentTaskService(
                        require_token=False,
                        actor_user_id=actor_user_id,
                        allowed_workspace_ids={workspace_id},
                        allowed_project_ids={project_id},
                        default_workspace_id=workspace_id,
                    ).complete_task(
                        task_id=task_id,
                        auth_token=MCP_AUTH_TOKEN or None,
                        command_id=command_id,
                    )
                except Exception:
                    continue
                completed += 1
            db.commit()
    return completed


def _runner_loop():
    while not _runner_stop_event.is_set():
        try:
            recover_stale_running_automation_once(limit=20)
            queue_team_mode_happy_path_once(limit=20)
            queue_satisfied_external_status_triggers_once(limit=20)
            queue_due_scheduled_tasks_once(limit=20)
            run_queued_automation_once(limit=20)
            closeout_team_mode_tasks_once(limit=20)
        except Exception:
            # Keep worker alive, but do not swallow diagnostics.
            logger.exception("Automation runner tick failed.")
        woke = _runner_wakeup_event.wait(AGENT_RUNNER_INTERVAL_SECONDS)
        if woke:
            _runner_wakeup_event.clear()


def recover_stale_running_automation_once(limit: int = 20, stale_after_seconds_override: float | None = None) -> int:
    recovered = 0
    now = datetime.now(timezone.utc)
    default_stale_after_seconds = (
        max(float(stale_after_seconds_override), 0.0)
        if stale_after_seconds_override is not None
        else max(min(float(AGENT_EXECUTOR_TIMEOUT_SECONDS) * 0.5, 120.0), 45.0)
    )
    kickoff_stale_after_seconds = min(default_stale_after_seconds, 45.0)

    def _latest_progress_timestamp(state: dict) -> datetime | None:
        for key in ("last_agent_stream_updated_at", "last_agent_run_at", "last_requested_at"):
            dt = _parse_iso_utc(str(state.get(key) or "").strip())
            if dt is not None:
                return dt
        return None

    with SessionLocal() as db:
        candidate_ids = db.execute(
            select(Task.id).where(Task.is_deleted == False).order_by(Task.updated_at.asc()).limit(max(limit * 10, limit))
        ).scalars().all()

        for task_id in candidate_ids:
            state, _ = rebuild_state(db, "Task", task_id)
            if state.get("automation_state") != "running":
                continue
            latest_signal = _latest_progress_timestamp(state)
            if latest_signal is None:
                continue
            last_requested_instruction = str(state.get("last_requested_instruction") or "").strip()
            stale_after_seconds = (
                kickoff_stale_after_seconds
                if _is_classified_team_mode_kickoff(state=state)
                else default_stale_after_seconds
            )
            age_seconds = (now - latest_signal.astimezone(timezone.utc)).total_seconds()
            if age_seconds < stale_after_seconds:
                continue

            workspace_id = state.get("workspace_id")
            if not workspace_id:
                continue
            project_id = state.get("project_id")
            actor_user_id = _resolve_task_actor_user_id(db=db, task_id=task_id, state=state)
            failed_at = to_iso_utc(now)
            error = f"Automation run exceeded stale threshold ({int(stale_after_seconds)}s) and was recovered."
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=task_id,
                event_type=EVENT_AUTOMATION_FAILED,
                payload={"failed_at": failed_at, "error": error, "summary": "Automation runner recovered stale running task."},
                metadata={"actor_id": actor_user_id, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id},
            )
            request_source = str(state.get("last_requested_source") or "").strip().lower()
            schedule_state = str(state.get("schedule_state") or "").strip().lower()
            if request_source == "schedule" or schedule_state in {"queued", "running"}:
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=task_id,
                    event_type=EVENT_SCHEDULE_FAILED,
                    payload={"failed_at": failed_at, "error": error},
                        metadata={"actor_id": actor_user_id, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id},
                )
                updated_triggers, next_due = rearm_first_schedule_trigger(
                    execution_triggers=state.get("execution_triggers"),
                    now_utc=now,
                )
                if next_due:
                    append_event(
                        db,
                        aggregate_type="Task",
                        aggregate_id=task_id,
                        event_type=TASK_EVENT_UPDATED,
                        payload={
                            "execution_triggers": updated_triggers,
                            "scheduled_at_utc": next_due,
                            "schedule_state": "idle",
                        },
                        metadata={
                            "actor_id": actor_user_id,
                            "workspace_id": workspace_id,
                            "project_id": project_id,
                            "task_id": task_id,
                        },
                    )
            db.commit()
            recovered += 1
            if recovered >= limit:
                break
    return recovered


def queue_due_scheduled_tasks_once(limit: int = 20) -> int:
    queued = 0
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        candidate_tasks = db.execute(
            select(Task)
            .where(
                Task.is_deleted == False,
                Task.task_type == "scheduled_instruction",
                Task.schedule_state == "idle",
            )
            .order_by(Task.scheduled_at_utc.asc())
            .limit(max(limit * 10, limit))
        ).scalars().all()

        for task in candidate_tasks:
            state, _ = rebuild_state(db, "Task", task.id)
            if state.get("schedule_state", "idle") != "idle":
                continue
            if state.get("automation_state", "idle") in {"queued", "running"}:
                continue
            _idx, schedule_trigger = first_enabled_schedule_trigger(state.get("execution_triggers"))
            if schedule_trigger is None:
                continue
            if not schedule_trigger_matches_status(trigger=schedule_trigger, status=state.get("status")):
                continue
            due_at = parse_schedule_due_at(schedule_trigger)
            if due_at is None or due_at > now:
                continue
            workspace_id = state.get("workspace_id")
            if not workspace_id:
                continue
            project_id = state.get("project_id")
            # Kickoff guard applies only to recurring oversight schedules.
            # Generic scheduled tasks should run normally.
            if is_recurring_oversight_task(state):
                last_requested_source = str(state.get("last_requested_source") or "").strip()
                last_agent_run_at = str(state.get("last_agent_run_at") or "").strip()
                if not last_requested_source and not last_agent_run_at:
                    continue
            actor_user_id = _resolve_task_actor_user_id(db=db, task_id=task.id, state=state)
            instruction = (
                (state.get("instruction") or "").strip()
                or (state.get("scheduled_instruction") or "").strip()
            )
            if not instruction:
                continue
            now_iso = to_iso_utc(datetime.now(timezone.utc))
            # Guard in-memory record so the same task is not re-queued while handling this batch.
            task.schedule_state = "queued"
            db.flush()
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=task.id,
                event_type=EVENT_SCHEDULE_QUEUED,
                payload={"queued_at": now_iso},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": task.id,
                },
            )
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=task.id,
                event_type=EVENT_AUTOMATION_REQUESTED,
                payload={"requested_at": now_iso, "instruction": instruction, "source": "schedule"},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": task.id,
                },
            )
            db.commit()
            queued += 1
            if queued >= limit:
                break
    return queued


def start_automation_runner():
    global _runner_thread
    if not AGENT_RUNNER_ENABLED:
        return
    if _runner_thread and _runner_thread.is_alive():
        return
    _runner_stop_event.clear()
    _runner_wakeup_event.clear()
    try:
        # On process restart/deploy, immediately recover orphaned "running" tasks.
        recovered = recover_stale_running_automation_once(limit=200, stale_after_seconds_override=0.0)
        if recovered > 0:
            logger.info("Automation runner startup recovered %s stale running task(s).", recovered)
    except Exception:
        logger.exception("Automation runner startup recovery failed.")
    _runner_thread = threading.Thread(target=_runner_loop, name="automation-runner", daemon=True)
    _runner_thread.start()


def stop_automation_runner():
    global _runner_thread
    _runner_stop_event.set()
    _runner_wakeup_event.set()
    if _runner_thread and _runner_thread.is_alive():
        _runner_thread.join(timeout=3)
    _runner_thread = None


def wake_automation_runner():
    _runner_wakeup_event.set()
