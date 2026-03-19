from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid
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
    plan_team_mode_dispatch,
)
from plugins.team_mode.semantics import (
    REQUIRED_SEMANTIC_STATUSES,
    derive_phase_from_status_and_role,
    normalize_review_policy,
    semantic_status_key,
)
from .executor import AutomationOutcome, build_automation_usage_metadata, execute_task_automation_stream
from .service import AgentTaskService
from .gates import run_runtime_deploy_health_check
from features.notes.domain import EVENT_CREATED as NOTE_EVENT_CREATED
from features.projects.domain import EVENT_UPDATED as PROJECT_EVENT_UPDATED
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
from shared.models import Note, Project, ProjectMember, ProjectPluginConfig, ProjectRule, SessionLocal, Task, User as UserModel, WorkspaceMember
from shared.serializers import to_iso_utc
from shared.typed_notifications import append_notification_created_event
from shared.project_repository import (
    branch_is_merged_to_main,
    find_project_compose_manifest,
    resolve_project_repository_host_path,
    resolve_project_repository_path,
    resolve_task_branch_name,
    resolve_task_worktree_path,
)
from shared.delivery_evidence import (
    derive_deploy_execution_snapshot,
    extract_task_branches_from_refs,
    has_merge_to_main_ref,
    is_strict_deploy_success_snapshot,
)
from shared.settings import (
    AGENT_EXECUTOR_TIMEOUT_SECONDS,
    AGENT_RUNNER_ENABLED,
    AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS,
    AGENT_RUNNER_INTERVAL_SECONDS,
    AGENT_RUNNER_MAX_CONCURRENCY,
    AGENT_SYSTEM_USER_ID,
    DEFAULT_USER_ID,
    MCP_AUTH_TOKEN,
    logger,
)
from shared.core import TaskAutomationRun, TaskCreate
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
from shared.task_delivery import (
    DELIVERY_MODE_MERGED_INCREMENT,
    normalize_delivery_mode,
    task_matches_dependency_requirement,
    task_requires_deploy,
)
from shared.team_mode_lifecycle import (
    developer_success_transition,
    lead_deploy_success_transition,
    qa_success_transition,
)

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
_PROJECT_DEPLOY_LOCK_LEASE_SECONDS = 600
_POST_DEPLOY_HEALTH_RETRY_ATTEMPTS = 8
_POST_DEPLOY_HEALTH_RETRY_DELAY_SECONDS = 2.0
_AUTOMATION_STREAM_NOISY_STATUS_MESSAGES = {
    "Agent started processing the request.",
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
_TEAM_MODE_LEAD_COMMITTED_HANDOFF_GATED_FRAGMENT = "lead automation is gated until the developer handoff is committed on a task branch"
_MERGE_TO_MAIN_REF_PREFIX = "merge:main:"
_DEPLOY_STACK_REF_PREFIX = "deploy:stack:"
_DEPLOY_COMMAND_REF_PREFIX = "deploy:command:"
_DEPLOY_HEALTH_REF_PREFIX = "deploy:health:"
_DEPLOY_COMPOSE_REF_PREFIX = "deploy:compose:"
_DEPLOY_RUNTIME_REF_PREFIX = "deploy:runtime:"
_PATCH_MARKER_LINES = {
    "*** Begin Patch",
    "*** End Patch",
    "*** End of File",
}


def _probe_runtime_health_with_retry(
    *,
    stack: str,
    port: int | None,
    health_path: str,
    require_http_200: bool,
    host: str | None,
    attempts: int = _POST_DEPLOY_HEALTH_RETRY_ATTEMPTS,
    delay_seconds: float = _POST_DEPLOY_HEALTH_RETRY_DELAY_SECONDS,
) -> dict[str, object]:
    last_result: dict[str, object] = {}
    total_attempts = max(1, int(attempts or 1))
    for attempt in range(total_attempts):
        last_result = run_runtime_deploy_health_check(
            stack=stack,
            port=port,
            health_path=health_path,
            require_http_200=require_http_200,
            host=host,
        )
        if bool(last_result.get("ok")) and bool(last_result.get("serves_application_root")):
            return last_result
        if attempt < (total_attempts - 1):
            time.sleep(max(0.0, float(delay_seconds or 0.0)))
    return last_result


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


def _project_has_docker_compose_skill(*, db, workspace_id: str, project_id: str | None) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return False
    row = db.execute(
        select(ProjectPluginConfig.id).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "docker_compose",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    return row is not None


def _project_runtime_deploy_target(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
) -> tuple[str, str, int | None, str, bool]:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return "constructos-ws-default", "gateway", None, "/health", False
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
        return "constructos-ws-default", "gateway", None, "/health", False
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
    host = str(runtime_cfg.get("host") or "gateway").strip() or "gateway"
    port_raw = runtime_cfg.get("port")
    try:
        port = int(port_raw) if port_raw is not None else None
    except Exception:
        port = None
    health_path = str(runtime_cfg.get("health_path") or "/health").strip() or "/health"
    if not health_path.startswith("/"):
        health_path = f"/{health_path}"
    required = bool(runtime_cfg.get("required"))
    return stack, host, port, health_path, required


def _effective_runtime_deploy_target_for_task(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    delivery_mode: str | None,
) -> tuple[str, str, int | None, str, bool]:
    stack, host, port, health_path, runtime_required = _project_runtime_deploy_target(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    if (
        task_requires_deploy(delivery_mode)
        and _project_has_docker_compose_skill(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
    ):
        runtime_required = True
    return stack, host, port, health_path, runtime_required


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
    if not workspace_id or not normalized_project_id:
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
    if not normalized_assignee_id:
        return ""
    role = db.execute(
        select(ProjectMember.role).where(
            ProjectMember.workspace_id == workspace_id,
            ProjectMember.project_id == normalized_project_id,
            ProjectMember.user_id == normalized_assignee_id,
        )
    ).scalar_one_or_none()
    return canonicalize_role(role)


def _resolve_team_agent_assignment_by_role(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    authority_role: str,
) -> tuple[str | None, str | None]:
    normalized_project_id = str(project_id or "").strip()
    normalized_role = canonicalize_role(authority_role)
    if not workspace_id or not normalized_project_id or not normalized_role:
        return None, None
    plugin_row = db.execute(
        select(ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    config_obj: dict[str, object] = {}
    if isinstance(plugin_row, str) and plugin_row.strip():
        try:
            parsed = json.loads(plugin_row)
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            config_obj = parsed
    team_agents = normalize_team_agents(config_obj.get("team"))
    matching_agent = next(
        (
            agent
            for agent in team_agents
            if canonicalize_role(agent.get("authority_role")) == normalized_role
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
        .join(UserModel, UserModel.id == ProjectMember.user_id)
        .where(
            ProjectMember.workspace_id == workspace_id,
            ProjectMember.project_id == normalized_project_id,
            ProjectMember.role == normalized_role,
            UserModel.user_type == "agent",
            UserModel.is_active == True,  # noqa: E712
        )
        .order_by(ProjectMember.id.asc())
    ).first()
    if member_row is None:
        return None, assigned_agent_code
    return str(member_row[0] or "").strip() or None, assigned_agent_code


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
    lead_task_count = 0
    task_contexts: list[tuple[Task, dict[str, object], str, str, str, str, str, str]] = []
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
        if is_lead_role(role):
            lead_task_count += 1
        task_contexts.append((task, state, status, role, assigned_slot, target_slot, instruction, automation_state))

    for task, state, status, role, assigned_slot, target_slot, instruction, automation_state in task_contexts:
        task_id = str(task.id or "").strip()
        dependency_ready, dependency_reason = _team_mode_dispatch_dependency_ready(
            db=db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            task_id=task_id,
            state=state,
        )
        has_lead_handoff = bool(str(state.get("last_lead_handoff_token") or "").strip())
        recurring_oversight = is_recurring_oversight_task(state)
        qa_handoff_gate = _current_nonblocking_gate_key(
            db=db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            assignee_role=role,
            task_status=status,
            task_state=state,
        )
        semantic_status = semantic_status_key(status=status)
        dispatch_ready = bool(
            instruction
            and dependency_ready
            and (
                (is_developer_role(role) and semantic_status in {"todo", "active", "blocked"})
                or (is_qa_role(role) and semantic_status in {"active", "blocked"} and has_lead_handoff and not qa_handoff_gate)
                or (
                    is_lead_role(role)
                    and semantic_status in {"todo", "active", "blocked", "awaiting_decision"}
                    and (not recurring_oversight or lead_task_count <= 1)
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
    source_task_id: str | None = None,
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
        current_automation_state = str(state.get("automation_state") or "idle").strip().lower()
        last_requested_source = str(state.get("last_requested_source") or "").strip()
        last_requested_source_task_id = str(state.get("last_requested_source_task_id") or "").strip()
        normalized_source_task_id = str(source_task_id or "").strip()
        if not normalized_source_task_id and str(source or "").strip() == "runner_orchestrator":
            normalized_source_task_id = str(
                _infer_team_mode_dispatch_source_task_id(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=normalized_project_id,
                    task_id=task_id,
                    assignee_role=_resolve_assignee_project_role(
                        db=db,
                        workspace_id=workspace_id,
                        project_id=normalized_project_id,
                        assignee_id=str(state.get("assignee_id") or getattr(task, "assignee_id", "") or ""),
                        assigned_agent_code=str(state.get("assigned_agent_code") or getattr(task, "assigned_agent_code", "") or ""),
                        task_labels=state.get("labels") if state.get("labels") is not None else getattr(task, "labels", None),
                        task_status=str(state.get("status") or getattr(task, "status", "") or ""),
                    ),
                )
                or ""
            ).strip()
        active_same_request = (
            current_automation_state in {"queued", "running"}
            and last_requested_source == str(source or "").strip()
            and last_requested_source_task_id == normalized_source_task_id
        )
        if active_same_request:
            continue
        if current_automation_state in {"queued", "running"} and str(source or "").strip() not in {
            "runner_orchestrator",
            "developer_handoff",
            "lead_kickoff_dispatch",
            "lead_handoff",
            "blocker_escalation",
        }:
            continue
        if (
            source in {"runner_orchestrator", "developer_handoff", "lead_kickoff_dispatch"}
            and current_automation_state == "completed"
            and last_requested_source == str(source or "").strip()
            and last_requested_source_task_id == normalized_source_task_id
        ):
            continue
        actor_user_id = _resolve_task_actor_user_id(db=db, task_id=task_id, state=state)
        actor = db.get(UserModel, actor_user_id)
        if actor is None or not bool(getattr(actor, "is_active", False)):
            continue
        command_id = f"tm-kickoff-dev-{normalized_project_id[:8]}-{task_id[:8]}-{int(now_utc.timestamp())}"
        try:
            TaskApplicationService(db, actor, command_id=command_id).request_automation_run(
                task_id,
                TaskAutomationRun(
                    instruction=instruction,
                    source=source,
                    source_task_id=normalized_source_task_id or None,
                ),
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
                    "source_task_id": normalized_source_task_id or None,
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


def _rearm_blocked_team_mode_lead_tasks(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
) -> int:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return 0

    tasks = db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.project_id == normalized_project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        )
    ).scalars().all()

    rearmed = 0
    for task in tasks:
        task_id = str(task.id or "").strip()
        if not task_id:
            continue
        task_state, _ = rebuild_state(db, "Task", task_id)
        task_status = str(task_state.get("status") or getattr(task, "status", "") or "").strip()
        if semantic_status_key(status=task_status) != "blocked":
            continue
        task_role = _resolve_assignee_project_role(
            db=db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            assignee_id=str(task_state.get("assignee_id") or getattr(task, "assignee_id", "") or ""),
            assigned_agent_code=str(task_state.get("assigned_agent_code") or getattr(task, "assigned_agent_code", "") or ""),
            task_labels=task_state.get("labels") if task_state.get("labels") is not None else getattr(task, "labels", None),
            task_status=task_status,
        )
        if not is_lead_role(task_role):
            continue
        deploy_snapshot = derive_deploy_execution_snapshot(
            refs=task_state.get("external_refs"),
            current_snapshot=(
                task_state.get("last_deploy_execution")
                if isinstance(task_state.get("last_deploy_execution"), dict)
                else {}
            ),
        )
        if (
            str(deploy_snapshot.get("command") or "").strip()
            and deploy_snapshot.get("runtime_ok") is False
        ):
            continue
        dispatch_ready, _dispatch_reason = _team_mode_dispatch_dependency_ready(
            db=db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            task_id=task_id,
            state=task_state,
        )
        if not dispatch_ready:
            continue
        actor_user_id = _resolve_task_actor_user_id(db=db, task_id=task_id, state=task_state)
        transitioned = _append_task_status_transition_if_allowed(
            db=db,
            task_id=task_id,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            actor_user_id=actor_user_id,
            actor_role="Lead",
            from_status=task_status,
            to_status=REQUIRED_SEMANTIC_STATUSES["active"],
        )
        if not transitioned:
            continue
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=task_id,
            event_type=TASK_EVENT_UPDATED,
            payload={"last_agent_error": None},
            metadata={
                "actor_id": actor_user_id,
                "workspace_id": workspace_id,
                "project_id": normalized_project_id,
                "task_id": task_id,
            },
        )
        rearmed += 1
    return rearmed


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
                    f"waiting for relationship dependency: {matched_sources}/{total_sources} source tasks reached {sorted(statuses)}",
                )
            )
        if dependency_clauses:
            for satisfied, _reason in dependency_clauses:
                if satisfied:
                    return True, None
            return False, dependency_clauses[0][1]
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
        source_task_id=kickoff_task_id,
        exclude_task_ids={kickoff_task_id},
        allowed_roles={"Developer"},
    )


def _infer_team_mode_dispatch_source_task_id(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    assignee_role: str | None,
) -> str | None:
    normalized_project_id = str(project_id or "").strip()
    normalized_task_id = str(task_id or "").strip()
    normalized_role = canonicalize_role(assignee_role)
    if (
        not workspace_id
        or not normalized_project_id
        or not normalized_task_id
        or normalized_role not in TEAM_MODE_WORKFLOW_ROLES
    ):
        return None

    def _candidate_timestamp(task_row: Task, state: dict[str, object]) -> float:
        for value in (
            state.get("last_requested_triggered_at"),
            state.get("last_activity_at"),
            state.get("last_requested_at"),
            state.get("last_agent_run_at"),
            getattr(task_row, "updated_at", None),
            getattr(task_row, "created_at", None),
        ):
            parsed = _parse_iso_timestamp(value)
            if parsed is not None:
                return parsed.timestamp()
            if isinstance(value, datetime):
                dt_value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
                return dt_value.astimezone(timezone.utc).timestamp()
        return 0.0

    candidates: list[tuple[int, float, str]] = []
    tasks = db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.project_id == normalized_project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        )
    ).scalars().all()
    for task in tasks:
        candidate_task_id = str(task.id or "").strip()
        if not candidate_task_id or candidate_task_id == normalized_task_id:
            continue
        candidate_state, _ = rebuild_state(db, "Task", candidate_task_id)
        candidate_status = str(candidate_state.get("status") or getattr(task, "status", "") or "").strip()
        candidate_role = _resolve_assignee_project_role(
            db=db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            assignee_id=str(candidate_state.get("assignee_id") or getattr(task, "assignee_id", "") or ""),
            assigned_agent_code=str(candidate_state.get("assigned_agent_code") or getattr(task, "assigned_agent_code", "") or ""),
            task_labels=candidate_state.get("labels") if candidate_state.get("labels") is not None else getattr(task, "labels", None),
            task_status=candidate_status,
        )
        candidate_automation_state = str(candidate_state.get("automation_state") or "idle").strip().lower()
        candidate_semantic_status = semantic_status_key(status=candidate_status)
        candidate_rank: int | None = None
        if normalized_role == "Developer":
            if is_lead_role(candidate_role) and candidate_semantic_status in {"todo", "active", "blocked", "awaiting_decision"}:
                candidate_rank = 0
        elif normalized_role == "Lead":
            candidate_has_merge_evidence = has_merge_to_main_ref(candidate_state.get("external_refs"))
            if (
                is_developer_role(candidate_role)
                and candidate_semantic_status in {"active", "completed"}
                and (candidate_automation_state == "completed" or candidate_has_merge_evidence)
            ):
                candidate_rank = 0
            elif is_developer_role(candidate_role) and candidate_semantic_status == "blocked":
                candidate_rank = 1
            elif is_qa_role(candidate_role) and candidate_semantic_status == "blocked":
                candidate_rank = 2
        elif normalized_role == "QA":
            if is_lead_role(candidate_role) and str(candidate_state.get("last_lead_handoff_token") or "").strip():
                candidate_rank = 0
            elif is_lead_role(candidate_role) and candidate_semantic_status in {"todo", "active", "blocked", "awaiting_decision"}:
                candidate_rank = 1
        if candidate_rank is None:
            continue
        candidates.append((candidate_rank, -_candidate_timestamp(task, candidate_state), candidate_task_id))

    candidates.sort()
    return candidates[0][2] if candidates else None


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
        )
    ).all()
    for task_id, assignee_id, assigned_agent_code, labels, status in rows:
        normalized_status = str(status or "").strip()
        if semantic_status_key(status=normalized_status) == "completed":
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
    project_row = db.get(Project, normalized_project_id)
    project_name = str(getattr(project_row, "name", "") or "").strip() or None
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
        external_refs = state.get("external_refs")
        if has_merge_to_main_ref(external_refs):
            return True
        for branch_name in extract_task_branches_from_refs(external_refs):
            if branch_is_merged_to_main(
                project_name=project_name,
                project_id=normalized_project_id,
                branch_name=branch_name,
            ):
                return True
    return False


def _task_state_has_merge_to_main_evidence(
    *,
    project_name: str | None,
    project_id: str | None,
    state: dict[str, object] | None,
) -> bool:
    refs = state.get("external_refs") if isinstance(state, dict) else None
    if has_merge_to_main_ref(refs):
        return True
    normalized_project_id = str(project_id or "").strip()
    for branch_name in extract_task_branches_from_refs(refs):
        if branch_is_merged_to_main(
            project_name=str(project_name or "").strip(),
            project_id=normalized_project_id or None,
            branch_name=branch_name,
        ):
            return True
    return False


def _prepare_repo_root_for_main_integration(*, repo_root: Path) -> tuple[bool, str | None]:
    code_reset, _out_reset, err_reset = _run_git_command_with_error(cwd=repo_root, args=["reset", "--hard", "HEAD"])
    if code_reset != 0:
        return False, f"Runner error: failed to reset integration repository: {err_reset[:220]}"
    code_clean, _out_clean, err_clean = _run_git_command_with_error(
        cwd=repo_root,
        args=["clean", "-fd", "-e", ".constructos/"],
    )
    if code_clean != 0:
        return False, f"Runner error: failed to clean integration repository: {err_clean[:220]}"
    code_checkout, _out_checkout, err_checkout = _run_git_command_with_error(cwd=repo_root, args=["checkout", "main"])
    if code_checkout != 0:
        return False, f"Runner error: failed to checkout main for integration: {err_checkout[:220]}"
    return True, None


def _parse_iso_utc_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _project_active_deploy_lock(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    now_utc: datetime | None = None,
) -> dict[str, object] | None:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return None
    reference_now = now_utc or datetime.now(timezone.utc)
    candidate_ids = [
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
    active_lock: dict[str, object] | None = None
    for task_id in candidate_ids:
        state, _ = rebuild_state(db, "Task", task_id)
        lock_id = str(state.get("deploy_lock_id") or "").strip()
        acquired_at = _parse_iso_utc_datetime(state.get("deploy_lock_acquired_at"))
        released_at = _parse_iso_utc_datetime(state.get("deploy_lock_released_at"))
        if not lock_id or acquired_at is None or released_at is not None:
            continue
        if (reference_now - acquired_at).total_seconds() > _PROJECT_DEPLOY_LOCK_LEASE_SECONDS:
            continue
        snapshot = {
            "task_id": task_id,
            "lock_id": lock_id,
            "deploy_cycle_id": str(state.get("last_deploy_cycle_id") or "").strip() or None,
            "acquired_at": acquired_at.isoformat(),
        }
        if active_lock is None or str(snapshot["acquired_at"]) > str(active_lock.get("acquired_at") or ""):
            active_lock = snapshot
    return active_lock


def _acquire_project_deploy_lock(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    actor_user_id: str,
    acquired_at_iso: str,
) -> dict[str, object]:
    active_lock = _project_active_deploy_lock(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
        now_utc=_parse_iso_utc_datetime(acquired_at_iso) or datetime.now(timezone.utc),
    )
    if active_lock and str(active_lock.get("task_id") or "").strip() != task_id:
        return {
            "ok": False,
            "error": (
                "Runner error: deployment is in progress for this project. "
                f"Active deploy lock `{str(active_lock.get('lock_id') or '').strip()}` "
                f"is held by task `{str(active_lock.get('task_id') or '').strip()}`."
            ),
        }
    if active_lock and str(active_lock.get("task_id") or "").strip() == task_id:
        return {
            "ok": True,
            "lock_id": str(active_lock.get("lock_id") or "").strip(),
            "deploy_cycle_id": str(active_lock.get("deploy_cycle_id") or "").strip() or None,
            "reused": True,
        }
    lock_id = f"deploy-lock:{uuid.uuid4()}"
    deploy_cycle_id = f"deploy-cycle:{task_id[:8]}:{uuid.uuid4().hex[:10]}"
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "deploy_lock_id": lock_id,
            "deploy_lock_acquired_at": acquired_at_iso,
            "deploy_lock_released_at": None,
            "last_deploy_cycle_id": deploy_cycle_id,
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": str(project_id or "").strip() or None,
            "task_id": task_id,
        },
    )
    return {
        "ok": True,
        "lock_id": lock_id,
        "deploy_cycle_id": deploy_cycle_id,
        "reused": False,
    }


def _release_project_deploy_lock(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    actor_user_id: str,
    released_at_iso: str,
    lock_id: str | None,
) -> None:
    normalized_lock_id = str(lock_id or "").strip()
    if not normalized_lock_id:
        return
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "deploy_lock_id": normalized_lock_id,
            "deploy_lock_released_at": released_at_iso,
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": str(project_id or "").strip() or None,
            "task_id": task_id,
        },
    )


def _merge_current_task_branch_to_main(
    *,
    db,
    workspace_id: str,
    project_id: str,
    task_id: str,
    actor_user_id: str,
) -> dict[str, object]:
    task_state, _ = rebuild_state(db, "Task", task_id)
    project_requires_review = _team_mode_review_required_for_project(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    if _team_mode_review_gate_pending(state=task_state, project_requires_review=project_requires_review):
        return {
            "ok": False,
            "error": "Runner error: merge to main requires an approved human review for this task.",
        }

    active_lock = _project_active_deploy_lock(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    if active_lock and str(active_lock.get("task_id") or "").strip() != task_id:
        return {
            "ok": False,
            "error": (
                "Runner error: deployment in progress; merge to main is temporarily frozen for this project. "
                f"Active deploy lock `{str(active_lock.get('lock_id') or '').strip()}` "
                f"is held by task `{str(active_lock.get('task_id') or '').strip()}`."
            ),
        }
    project_row = db.get(Project, project_id)
    if project_row is None:
        return {"ok": False, "error": "Runner error: project is missing during Developer merge handoff."}
    project_name = str(getattr(project_row, "name", "") or "").strip() or None
    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    if not repo_root.exists():
        return {"ok": False, "error": "Runner error: project repository path is missing during Developer merge handoff."}
    refs = task_state.get("external_refs")
    branch_name = _extract_task_branch_from_refs(refs)
    if not branch_name:
        return {"ok": False, "error": "Runner error: task branch evidence is missing during Developer merge handoff."}

    ok, prep_error = _prepare_repo_root_for_main_integration(repo_root=repo_root)
    if not ok:
        return {"ok": False, "error": prep_error or "Runner error: failed to prepare integration repository."}

    code_branch, _out_branch, err_branch = _run_git_command_with_error(
        cwd=repo_root,
        args=["rev-parse", "--verify", f"refs/heads/{branch_name}"],
    )
    if code_branch != 0:
        return {"ok": False, "error": f"Runner error: task branch {branch_name} does not exist for merge: {err_branch[:220]}"}

    patch_marker_error = _detect_patch_markers_on_task_branch(
        repo_root=repo_root,
        branch_name=branch_name,
    )
    if patch_marker_error:
        return {"ok": False, "error": patch_marker_error}

    code_ancestor, _out_ancestor, _err_ancestor = _run_git_command_with_error(
        cwd=repo_root,
        args=["merge-base", "--is-ancestor", branch_name, "main"],
    )
    if code_ancestor != 0:
        code_merge, _out_merge, err_merge = _run_git_command_with_error(
            cwd=repo_root,
            args=["merge", "--no-ff", "--no-edit", branch_name],
        )
        if code_merge != 0:
            _run_git_command_with_error(cwd=repo_root, args=["merge", "--abort"])
            return {"ok": False, "error": f"Runner error: Developer merge to main failed for {branch_name}: {err_merge[:240]}"}

    code_main_sha, out_main_sha, err_main_sha = _run_git_command_with_error(cwd=repo_root, args=["rev-parse", "HEAD"])
    if code_main_sha != 0 or not out_main_sha:
        return {"ok": False, "error": f"Runner error: merged {branch_name} but could not resolve main HEAD: {err_main_sha[:220]}"}

    merged_at = to_iso_utc(datetime.now(timezone.utc))
    merged_refs = _append_merge_to_main_ref(refs=refs, merge_sha=out_main_sha)
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "external_refs": merged_refs,
            "last_merged_at": merged_at,
            "last_merged_commit_sha": out_main_sha,
            **_team_mode_progress_payload(phase="deploy_ready"),
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": task_id,
        },
    )
    return {
        "ok": True,
        "merge_sha": str(out_main_sha).strip().lower(),
        "merged_at": merged_at,
        "external_refs": merged_refs,
    }


def _detect_patch_markers_on_task_branch(*, repo_root: Path, branch_name: str) -> str | None:
    code_diff, out_diff, err_diff = _run_git_command_with_error(
        cwd=repo_root,
        args=["diff", "--name-only", f"main...{branch_name}"],
    )
    if code_diff != 0:
        return f"Runner error: could not inspect changed files for {branch_name}: {err_diff[:220]}"
    changed_files = [str(item or "").strip() for item in str(out_diff or "").splitlines() if str(item or "").strip()]
    for rel_path in changed_files:
        code_show, out_show, _err_show = _run_git_command_with_error(
            cwd=repo_root,
            args=["show", f"{branch_name}:{rel_path}"],
        )
        if code_show != 0:
            continue
        for line in str(out_show or "").splitlines():
            if line.strip() in _PATCH_MARKER_LINES:
                return (
                    "Runner error: Developer handoff contains literal patch markers in "
                    f"`{rel_path}`. Remove patch markers like `*** End Patch` from task-branch files "
                    "before merge to main."
                )
    return None


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
    normalized_semantic = semantic_status_key(status=normalized_status)
    normalized_project_id = str(project_id or "").strip()
    project_name = None
    if workspace_id and normalized_project_id:
        project_row = db.get(Project, normalized_project_id)
        project_name = str(getattr(project_row, "name", "") or "").strip() or None
    if (
        is_lead_role(assignee_role)
        and normalized_semantic in {"todo", "active", "blocked", "awaiting_decision"}
        and _project_has_git_delivery_skill(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
    ):
        has_current_merge_evidence = _task_state_has_merge_to_main_evidence(
            project_name=project_name,
            project_id=normalized_project_id,
            state=task_state if isinstance(task_state, dict) else None,
        )
        if not has_current_merge_evidence and workspace_id and normalized_project_id:
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
                if semantic_status_key(status=developer_status) in {"todo", "active", "blocked"}:
                    return "lead_waiting_merge_ready_developer"
                if str(developer_state.get("automation_state") or "").strip().lower() in {"queued", "running"}:
                    return "lead_waiting_merge_ready_developer"
            if not _project_has_merge_to_main_evidence(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            ):
                return "lead_waiting_committed_developer_handoff"
    if (
        is_qa_role(assignee_role)
        and normalized_semantic in {"active", "blocked"}
    ):
        qa_state = dict(task_state or {})
        if not str(qa_state.get("last_lead_handoff_token") or "").strip():
            return "qa_waiting_lead_handoff"
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
                if executed_at and is_strict_deploy_success_snapshot(deploy_execution) and (latest_lead_deploy_at is None or executed_at > latest_lead_deploy_at):
                    latest_lead_deploy_at = executed_at
        qa_handoff_deploy = (
            qa_state.get("last_lead_handoff_deploy_execution")
            if isinstance(qa_state.get("last_lead_handoff_deploy_execution"), dict)
            else {}
        )
        qa_handoff_deploy_at = (
            str(qa_handoff_deploy.get("executed_at") or "").strip()
            if is_strict_deploy_success_snapshot(qa_handoff_deploy)
            else ""
        )
        if latest_lead_deploy_at and qa_handoff_deploy_at != latest_lead_deploy_at:
            return "qa_waiting_current_deploy_cycle"
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
    assignee_role: str | None = None,
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
    normalized_role = canonicalize_role(assignee_role)
    is_deploy_task = normalized_role == "Lead" and (
        "deploy" in title.lower() or "docker compose" in title.lower()
    )
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
    repo_authoritative_keys = {
        "repo_root",
        "task_workdir",
        "task_branch",
        "after_head_sha",
        "after_on_task_branch",
        "after_is_dirty",
    }
    for key, value in dict(primary or {}).items():
        if key in repo_authoritative_keys and key in merged and merged.get(key) not in (None, ""):
            continue
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
    # Preserve leading spaces because porcelain/status output encodes state in
    # fixed columns at the start of each line.
    output = str(proc.stdout or "").rstrip("\r\n")
    return int(proc.returncode), output


def _derive_files_changed_from_git_evidence(git_evidence: dict[str, object]) -> list[str]:
    repo_path = str(git_evidence.get("repo_root") or "").strip()
    task_workdir_path = str(git_evidence.get("task_workdir") or "").strip()
    if not repo_path and not task_workdir_path:
        return []
    repo_cwd = Path(repo_path) if repo_path else None
    task_cwd = Path(task_workdir_path) if task_workdir_path else None
    if repo_cwd is not None and (not repo_cwd.exists() or not repo_cwd.is_dir()):
        repo_cwd = None
    if task_cwd is not None and (not task_cwd.exists() or not task_cwd.is_dir()):
        task_cwd = None
    if repo_cwd is None and task_cwd is None:
        return []
    before_head_sha = str(git_evidence.get("before_head_sha") or "").strip().lower()
    after_head_sha = str(git_evidence.get("after_head_sha") or "").strip().lower()
    after_is_dirty = bool(git_evidence.get("after_is_dirty"))
    files: list[str] = []
    seen: set[str] = set()

    def _append_from_output(output: str) -> None:
        for line in str(output or "").splitlines():
            path = str(line or "").strip()
            if not path or path in seen:
                continue
            seen.add(path)
            files.append(path)

    if repo_cwd is not None and before_head_sha and after_head_sha and before_head_sha != after_head_sha:
        code, out = _run_git_command(cwd=repo_cwd, args=["diff", "--name-only", before_head_sha, after_head_sha])
        if code == 0:
            _append_from_output(out)
    if (not files) and task_cwd is not None:
        code, out = _run_git_command(cwd=task_cwd, args=["diff", "--name-only", "HEAD"])
        if code == 0:
            _append_from_output(out)
    if task_cwd is not None and (after_is_dirty or not files):
        code, out = _run_git_command(cwd=task_cwd, args=["status", "--porcelain"])
        if code == 0:
            for line in str(out or "").splitlines():
                raw = str(line or "").rstrip()
                if not raw:
                    continue
                path = raw[3:] if len(raw) > 3 else raw
                if path.startswith('"') and path.endswith('"'):
                    path = path[1:-1]
                if " -> " in path:
                    path = path.split(" -> ", 1)[1]
                normalized = path.strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                files.append(normalized)
    if (not files) and repo_cwd is not None and after_head_sha and not after_is_dirty:
        code, out = _run_git_command(cwd=repo_cwd, args=["show", "--pretty=format:", "--name-only", after_head_sha])
        if code == 0:
            _append_from_output(out)
    return files


def _inspect_committed_task_branch_handoff(git_evidence: dict[str, object]) -> dict[str, object]:
    repo_path = str(git_evidence.get("repo_root") or "").strip()
    task_workdir_path = str(git_evidence.get("task_workdir") or "").strip()
    branch_name = str(git_evidence.get("task_branch") or "").strip()
    after_head_sha = str(git_evidence.get("after_head_sha") or "").strip().lower()
    after_on_task_branch = bool(git_evidence.get("after_on_task_branch"))
    after_is_dirty = bool(git_evidence.get("after_is_dirty"))
    result: dict[str, object] = {
        "branch_name": branch_name,
        "branch_exists": False,
        "branch_head_sha": "",
        "main_head_sha": "",
        "branch_differs_from_main": False,
        "branch_ahead_of_main": False,
        "branch_reachable_from_main": False,
        "main_reachable_from_branch": False,
        "after_on_task_branch": after_on_task_branch,
        "after_is_dirty": after_is_dirty,
    }
    repo_cwd = Path(repo_path) if repo_path else None
    task_cwd = Path(task_workdir_path) if task_workdir_path else None
    if repo_cwd is not None and (not repo_cwd.exists() or not repo_cwd.is_dir()):
        repo_cwd = None
    if task_cwd is not None and (not task_cwd.exists() or not task_cwd.is_dir()):
        task_cwd = None
    if not branch_name or repo_cwd is None:
        return result
    code_branch, out_branch = _run_git_command(cwd=repo_cwd, args=["rev-parse", "--verify", f"refs/heads/{branch_name}"])
    if code_branch != 0 or not str(out_branch or "").strip():
        return result
    branch_head_sha = str(out_branch or "").strip().lower()
    result["branch_exists"] = True
    result["branch_head_sha"] = branch_head_sha
    code_main, out_main = _run_git_command(cwd=repo_cwd, args=["rev-parse", "--verify", "refs/heads/main"])
    if code_main == 0 and str(out_main or "").strip():
        main_head_sha = str(out_main or "").strip().lower()
        result["main_head_sha"] = main_head_sha
        result["branch_differs_from_main"] = bool(branch_head_sha and main_head_sha and branch_head_sha != main_head_sha)
        code_branch_in_main, _out_branch_in_main = _run_git_command(
            cwd=repo_cwd,
            args=["merge-base", "--is-ancestor", branch_name, "main"],
        )
        code_main_in_branch, _out_main_in_branch = _run_git_command(
            cwd=repo_cwd,
            args=["merge-base", "--is-ancestor", "main", branch_name],
        )
        branch_reachable_from_main = code_branch_in_main == 0
        main_reachable_from_branch = code_main_in_branch == 0
        result["branch_reachable_from_main"] = branch_reachable_from_main
        result["main_reachable_from_branch"] = main_reachable_from_branch
        result["branch_ahead_of_main"] = bool(
            branch_head_sha
            and main_head_sha
            and branch_head_sha != main_head_sha
            and main_reachable_from_branch
            and not branch_reachable_from_main
        )
    if task_cwd is not None:
        code_current, out_current = _run_git_command(cwd=task_cwd, args=["branch", "--show-current"])
        if code_current == 0:
            result["after_on_task_branch"] = str(out_current or "").strip() == branch_name
    if not after_head_sha:
        result["after_head_sha"] = branch_head_sha
    else:
        result["after_head_sha"] = after_head_sha
    return result


def _finalize_developer_handoff_commit_if_safe(
    *,
    project_name: str | None,
    project_id: str | None,
    task_id: str,
    title: str | None,
    git_evidence: dict[str, object],
    require_nontrivial_dev_changes: bool,
    tests_run: bool,
    tests_passed: bool,
) -> tuple[dict[str, object], dict[str, object] | None]:
    committed_handoff = _inspect_committed_task_branch_handoff(git_evidence)
    if not bool(committed_handoff.get("branch_exists")):
        return git_evidence, None
    if not bool(committed_handoff.get("after_on_task_branch")):
        return git_evidence, None
    if not bool(committed_handoff.get("after_is_dirty")):
        return git_evidence, None
    if tests_run and not tests_passed:
        return git_evidence, None

    task_workdir_raw = str(git_evidence.get("task_workdir") or "").strip()
    task_branch = str(git_evidence.get("task_branch") or committed_handoff.get("branch_name") or "").strip()
    task_workdir = Path(task_workdir_raw) if task_workdir_raw else None
    if task_workdir is None or not task_workdir.exists() or not task_workdir.is_dir() or not task_branch:
        return git_evidence, None

    dirty_files = _derive_files_changed_from_git_evidence(git_evidence)
    if not dirty_files:
        return git_evidence, None
    has_nontrivial_dirty_changes = any(_is_nontrivial_dev_path(item) for item in dirty_files)
    if require_nontrivial_dev_changes and not has_nontrivial_dirty_changes:
        # Allow a final checkpoint commit for trivial leftover files only when
        # the task branch already contains a real Developer handoff ahead of main.
        # This keeps docs-only branches from being promoted as Dev completion,
        # while preventing noisy reruns caused by minor uncommitted residue such as README edits.
        if not bool(committed_handoff.get("branch_ahead_of_main")):
            return git_evidence, None

    commit_sha = _commit_repo_changes_if_any(
        cwd=task_workdir,
        message=f"feat: finalize task {str(task_id or '').strip()[:8]} implementation handoff",
    )
    if not commit_sha:
        return git_evidence, None

    refreshed = _merge_git_evidence(
        dict(git_evidence),
        _collect_git_evidence_from_repo_state(
            project_name=project_name,
            project_id=project_id,
            task_id=task_id,
            title=title,
        ),
    )
    if str(git_evidence.get("before_head_sha") or "").strip():
        refreshed["before_head_sha"] = str(git_evidence.get("before_head_sha") or "").strip().lower()
    refreshed["after_is_dirty"] = False
    refreshed["after_on_task_branch"] = True
    refreshed["after_head_sha"] = str(commit_sha).strip().lower()

    return refreshed, {
        "commit_sha": str(commit_sha).strip().lower(),
        "task_branch": task_branch,
        "files_changed": dirty_files,
    }


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


def _format_dirty_handoff_preview(paths: list[str], *, limit: int = 5) -> str:
    normalized = [str(item or "").strip() for item in paths if str(item or "").strip()]
    if not normalized:
        return ""
    ordered = sorted(
        normalized,
        key=lambda item: (
            1 if _is_nontrivial_dev_path(item) else 0,
            item.replace("\\", "/").casefold(),
        ),
        reverse=True,
    )
    preview = ", ".join(ordered[:limit])
    if len(ordered) > limit:
        preview = f"{preview} ..."
    return preview


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
        and semantic_status_key(status=task_status) in {"todo", "active", "blocked"}
    )
    committed_handoff = _inspect_committed_task_branch_handoff(git_evidence)
    branch_head_sha = str(committed_handoff.get("branch_head_sha") or "").strip().lower()
    branch_ahead_of_main = bool(committed_handoff.get("branch_ahead_of_main"))
    task_branch = str(git_evidence.get("task_branch") or "").strip()
    after_head_sha = str(git_evidence.get("after_head_sha") or "").strip().lower()
    contract = (
        dict(outcome.execution_outcome_contract)
        if isinstance(outcome.execution_outcome_contract, dict)
        else None
    )
    if contract is None:
        if not developer_git_delivery_run:
            return None
        if (
            bool(committed_handoff.get("branch_exists"))
            and not bool(committed_handoff.get("after_is_dirty"))
            and bool(committed_handoff.get("after_on_task_branch"))
            and branch_ahead_of_main
        ):
            derived_commit_sha = branch_head_sha or after_head_sha
            derived_files_changed = _derive_files_changed_from_git_evidence(git_evidence)
            contract = {
                "contract_version": 1,
                "files_changed": list(derived_files_changed),
                "commit_sha": derived_commit_sha or None,
                "branch": task_branch or None,
                "tests_run": False,
                "tests_passed": False,
                "artifacts": [],
            }
        else:
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
    if developer_git_delivery_run and not commit_sha and branch_head_sha and branch_ahead_of_main:
        commit_sha = branch_head_sha
    elif developer_git_delivery_run and not commit_sha and after_head_sha and branch_ahead_of_main:
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

    if developer_git_delivery_run and not files_changed and (commit_sha or branch):
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
        dirty_files: list[str] = []
        if bool(committed_handoff.get("after_is_dirty")):
            dirty_files = _derive_files_changed_from_git_evidence(git_evidence)
        if not bool(committed_handoff.get("branch_exists")):
            return "Runner error: Developer automation requires a real task branch handoff before Lead review."
        if bool(committed_handoff.get("after_is_dirty")):
            if dirty_files:
                preview = _format_dirty_handoff_preview(dirty_files, limit=5)
                return (
                    "Runner error: Developer handoff is not committed on the task branch yet. "
                    f"Branch `{branch or task_branch or 'task/<unknown>'}` is not clean. "
                    f"Uncommitted files: {preview}"
                )
            return (
                "Runner error: Developer handoff is not committed on the task branch yet. "
                f"Branch `{branch or task_branch or 'task/<unknown>'}` still has uncommitted changes."
            )
        if not bool(committed_handoff.get("after_on_task_branch")):
            return "Runner error: Developer automation must finalize from the task branch before Lead review."
        if not branch_ahead_of_main:
            main_head_sha = str(committed_handoff.get("main_head_sha") or "").strip().lower()
            main_reachable_from_branch = bool(committed_handoff.get("main_reachable_from_branch"))
            if branch_head_sha and main_head_sha:
                if not main_reachable_from_branch:
                    return (
                        "Runner error: Developer task branch must be reconciled with the latest `main` before Lead review. "
                        f"Branch `{branch or task_branch or 'task/<unknown>'}` at `{branch_head_sha[:7]}` "
                        f"does not contain current `main` `{main_head_sha[:7]}`."
                    )
                if bool(committed_handoff.get("branch_reachable_from_main")):
                    return (
                        "Runner error: Developer handoff is not committed on a task branch ahead of main yet. "
                        f"Branch `{branch or task_branch or 'task/<unknown>'}` at `{branch_head_sha[:7]}` "
                        "has no unique commits ahead of `main`."
                    )
                return (
                    "Runner error: Developer handoff is not committed on a task branch ahead of main yet. "
                    f"Branch `{branch or task_branch or 'task/<unknown>'}` is still at `{branch_head_sha[:7]}`, "
                    f"same as `main`."
                )
            return "Runner error: Developer handoff is not committed on a task branch ahead of main yet."
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
        if branch_head_sha and commit_sha and branch_head_sha != commit_sha:
            return "Runner error: Developer automation commit_sha must match the current task branch HEAD."
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
    status_semantics = config.get("status_semantics") if isinstance(config, dict) else {}
    if not isinstance(status_semantics, dict):
        status_semantics = dict(REQUIRED_SEMANTIC_STATUSES)
    allowed, _reason = evaluate_team_mode_transition(
        status_semantics=status_semantics,
        from_status=str(from_status or "").strip(),
        to_status=str(to_status or "").strip(),
        actor_role=str(actor_role or "").strip() or None,
    )
    return bool(allowed)


def _team_mode_review_required_for_project(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return False
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
        return False
    try:
        config = json.loads(str(row[0] or "").strip() or "{}")
    except Exception:
        config = {}
    review_policy = normalize_review_policy(config.get("review_policy") if isinstance(config, dict) else {})
    return bool(review_policy.get("require_code_review"))


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
    return derive_phase_from_status_and_role(status=status, assignee_role=assignee_role)


def _effective_blocked_status_for_project(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
) -> str:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return "Blocked"
    row = db.execute(
        select(ProjectPluginConfig.config_json).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == normalized_project_id,
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        return "Blocked"
    try:
        config = json.loads(str(row[0] or "").strip() or "{}")
    except Exception:
        config = {}
    status_semantics = config.get("status_semantics") if isinstance(config, dict) else {}
    if not isinstance(status_semantics, dict):
        status_semantics = dict(REQUIRED_SEMANTIC_STATUSES)
    return str(status_semantics.get("blocked") or REQUIRED_SEMANTIC_STATUSES["blocked"]).strip() or "Blocked"


def _should_resume_team_mode_agent_task_as_active(*, assignee_role: str | None, status: str | None) -> bool:
    if canonicalize_role(assignee_role) not in {"Developer", "Lead", "QA"}:
        return False
    return semantic_status_key(status=status) in {"todo", "awaiting_decision"}


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
    build_required: bool,
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
    command_suffix = "docker compose -p {stack} up -d --build" if build_required else "docker compose -p {stack} up -d"
    command_ref = f"{_DEPLOY_COMMAND_REF_PREFIX}{command_suffix.format(stack=str(stack or '').strip())}"
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

    health_url = (
        str(http_url or "").strip()
        or f"http://gateway:{int(port)}{str(health_path or '/health').strip()}"
        if port is not None
        else ""
    )
    health_status = int(http_status or 0) if http_status is not None else 0
    health_ref = (
        f"{_DEPLOY_HEALTH_REF_PREFIX}{health_url}:http_{health_status}"
        if health_url
        else f"{_DEPLOY_HEALTH_REF_PREFIX}{str(health_path or '/health').strip()}:http_{health_status}"
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


def _build_lead_deploy_instruction_contract(
    *,
    stack: str,
    port_text: str,
    health_path: str,
    has_merge_to_main: bool,
) -> str:
    if not has_merge_to_main:
        return (
            "Lead deployment execution contract:\n"
            f"1) Probe runtime health at `http://gateway:{port_text}{health_path}` for observability only.\n"
            "2) No merge-to-main evidence exists yet: do NOT create compose and do NOT deploy.\n"
            "3) Coordinate Developer completion and deterministic merge-to-main first.\n"
            "4) Record deferred state evidence in external_refs and keep Lead task active."
        )
    return (
        "Lead deployment execution contract:\n"
        f"1) Probe runtime health at `http://gateway:{port_text}{health_path}`.\n"
        "2) If health is failing OR there is new merge-to-main evidence since last deploy evidence, prepare deterministic deployment assets before deploy:\n"
        "   - Ensure repository contains one compose manifest (`docker-compose.yml|docker-compose.yaml|compose.yml|compose.yaml`).\n"
        "   - If manifest is missing, Lead must create it from concrete repository evidence (no guessing):\n"
        "     a) If `Dockerfile` exists, compose must use `build: .` and expose configured runtime port.\n"
        "     b) Else if Node runtime files exist (`package.json` with a valid start script), create deterministic Dockerfile + compose for Node.\n"
        "     c) Else if Python runtime files exist (`pyproject.toml` or `requirements.txt` with runnable entrypoint), create deterministic Dockerfile + compose for Python.\n"
        "     d) Else if only static web assets exist (`index.html`), create deterministic nginx-based compose.\n"
        "     e) If none of the supported deterministic runtime signals exist, set task to Blocked with exact missing prerequisites (do not invent runtime).\n"
        f"3) Do NOT run `docker compose` manually from the task environment. The runner owns actual deploy execution for stack `{stack}` after deterministic asset preparation succeeds.\n"
        "4) Do NOT block this Lead response merely because runner-controlled deploy has not happened yet. "
        "If deterministic deploy prerequisites are ready, return a normal success/comment outcome and let the runner execute deploy + health evaluation.\n"
        "5) Only set Blocked when deterministic prerequisites for runner deploy are missing or ambiguous before deploy execution can begin.\n"
        "6) Record full evidence in external_refs: compose manifest path, runtime decision basis, and any concrete deploy prerequisites or blockers you identified.\n"
        "7) QA handoff is runner-controlled after successful deploy health. Do not request QA manually before runner deploy reaches HTTP 200."
    )


def _build_qa_runtime_validation_contract(
    *,
    stack: str,
    port_text: str,
    health_path: str,
) -> str:
    return (
        "QA runtime validation contract:\n"
        f"1) Validate the current deployed runtime for this Lead handoff at `http://gateway:{port_text}{health_path}` and application root `/`.\n"
        f"2) Treat the latest Lead deploy snapshot for stack `{stack}` as authoritative deployment evidence for this cycle.\n"
        "3) Do NOT run `docker compose` manually from the task environment. Do NOT rebuild, redeploy, restart, or troubleshoot by invoking Compose.\n"
        "4) If runtime validation fails, record probe evidence and block QA with the observed endpoint failure. Do not convert runtime validation into a manual deployment attempt.\n"
        "5) If gameplay/acceptance checks pass and runtime probes succeed, record QA artifacts and return the result normally."
    )


def _write_file_if_changed(*, path: Path, content: str) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _remove_path_if_exists(*, path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
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


def _repo_has_application_source_files(*, repo_root: Path) -> bool:
    patterns = [
        "src/**/*.js",
        "src/**/*.jsx",
        "src/**/*.ts",
        "src/**/*.tsx",
        "src/**/*.py",
        "src/**/*.html",
        "src/**/*.css",
        "*.js",
        "*.jsx",
        "*.ts",
        "*.tsx",
        "*.py",
        "*.html",
        "*.css",
    ]
    for pattern in patterns:
        for candidate in repo_root.glob(pattern):
            if not candidate.is_file():
                continue
            if any(part.startswith(".constructos") for part in candidate.parts):
                continue
            return True
    return False


def _looks_like_managed_static_compose_manifest(content: str) -> bool:
    normalized = str(content or "").strip().lower().replace(" ", "")
    if "image:nginx:1.27-alpine" not in normalized:
        return False
    return (
        "./nginx.constructos.conf:/etc/nginx/conf.d/default.conf:ro" in normalized
        or "./nginx/conf.d:/etc/nginx/conf.d:ro" in normalized
        or "/etc/nginx/conf.d" in normalized
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
    dockerfile = repo_root / "Dockerfile"
    package_json = repo_root / "package.json"
    pyproject = repo_root / "pyproject.toml"
    requirements = repo_root / "requirements.txt"
    index_html = repo_root / "index.html"
    manifest_path = find_project_compose_manifest(project_name=project_name, project_id=project_id)
    if manifest_path is not None:
        runtime_type = _derive_runtime_deploy_markers(project_name=project_name, project_id=project_id)[0]
        return {
            "ok": True,
            "manifest_path": str(manifest_path),
            "created_files": [],
            "commit_sha": None,
            "runtime_type": runtime_type,
        }

    try:
        if dockerfile.exists():
            runtime_type = "dockerfile_build"
        elif package_json.exists():
            package_data = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = package_data.get("scripts") if isinstance(package_data, dict) else {}
            start_script = str((scripts or {}).get("start") or "").strip() if isinstance(scripts, dict) else ""
            if start_script:
                runtime_type = "node_web"
            elif index_html.exists():
                runtime_type = "static_web"
            else:
                return {"ok": False, "error": "unsupported Node runtime: package.json is missing a non-empty scripts.start entry"}
        elif pyproject.exists() or requirements.exists():
            command = _python_runtime_entrypoint(repo_root=repo_root)
            if not command:
                return {"ok": False, "error": "unsupported Python runtime: expected main.py or app.py in repository root"}
            runtime_type = "python_web"
        elif index_html.exists():
            runtime_type = "static_web"
        else:
            return {"ok": False, "error": "unsupported runtime: repository does not contain Dockerfile, package.json, pyproject.toml, requirements.txt, or index.html"}
        return {
            "ok": False,
            "error": (
                "deploy scaffolding is missing for a recognizable "
                f"{runtime_type} runtime; create the missing deployment files on a task branch instead of modifying main directly"
            ),
        }
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"failed to parse package.json for deterministic deploy synthesis: {exc}"}
    except tomllib.TOMLDecodeError as exc:
        return {"ok": False, "error": f"failed to parse pyproject.toml for deterministic deploy synthesis: {exc}"}
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}


def _ensure_team_mode_lead_assignment(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    state: dict[str, object],
    actor_user_id: str,
) -> None:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return
    current_agent_code = str(state.get("assigned_agent_code") or "").strip()
    current_assignee_id = str(state.get("assignee_id") or "").strip()
    if current_agent_code:
        return
    lead_assignee_id, lead_agent_code = _resolve_team_agent_assignment_by_role(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        authority_role="Lead",
    )
    if not str(lead_agent_code or "").strip():
        return
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "assignee_id": lead_assignee_id or current_assignee_id or None,
            "assigned_agent_code": lead_agent_code,
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": normalized_project_id,
            "task_id": task_id,
        },
    )


def _create_lead_deploy_scaffolding_followup(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    state: dict[str, object],
    actor_user_id: str,
    port: int | None,
    health_path: str | None,
) -> str | None:
    normalized_project_id = str(project_id or "").strip()
    source_task_id = str(state.get("id") or "").strip()
    if not workspace_id or not normalized_project_id or not source_task_id:
        return None
    marker_ref = f"evidence://lead/{source_task_id}/deploy-scaffolding-followup"
    existing_tasks = db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.project_id == normalized_project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        )
    ).scalars().all()
    for task in existing_tasks:
        refs = getattr(task, "external_refs", None)
        if isinstance(refs, list):
            for item in refs:
                if isinstance(item, dict) and str(item.get("url") or "").strip() == marker_ref:
                    return str(task.id or "").strip() or None

    project_name = str(state.get("project_name") or "").strip()
    if not project_name:
        project_row = db.get(Project, normalized_project_id)
        project_name = str(getattr(project_row, "name", "") or "").strip()
    repo_root = resolve_project_repository_path(
        project_name=project_name or None,
        project_id=normalized_project_id,
    )
    if not _repo_has_application_source_files(repo_root=repo_root):
        return None

    dev_assignee_id, dev_agent_code = _resolve_team_agent_assignment_by_role(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        authority_role="Developer",
    )
    if not str(dev_agent_code or "").strip():
        return None

    port_text = str(int(port)) if port is not None else "the configured runtime port"
    normalized_health_path = str(health_path or "/health").strip() or "/health"
    source_title = str(state.get("title") or source_task_id).strip()
    instruction = (
        "Analyze the merged repository state and add only the missing deployment scaffolding required for managed Docker Compose deploy. "
        "Work only on the task branch, never on main directly. "
        f"Target runtime health endpoint `http://gateway:{port_text}{normalized_health_path}`. "
        "Add only deploy/runtime artifacts justified by the existing repository shape (for example Dockerfile, compose manifest, nginx config, or package/runtime wiring). "
        "Do not invent placeholder application files or fake product shells."
    )

    from features.tasks.application import TaskApplicationService

    actor = db.get(UserModel, actor_user_id) or db.get(UserModel, AGENT_SYSTEM_USER_ID)
    if actor is None:
        return None
    command_id = f"lead-deploy-followup-{source_task_id[:8]}"
    created = TaskApplicationService(db, actor, command_id=command_id).create_task(
        TaskCreate(
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            specification_id=str(state.get("specification_id") or "").strip() or None,
            title=f"Add deployment scaffolding for {source_title}",
            description=(
                f"Add the missing deployment/runtime scaffolding needed to unblock Lead deploy for `{source_title}`."
            ),
            status=REQUIRED_SEMANTIC_STATUSES["todo"],
            priority="High",
            assignee_id=dev_assignee_id,
            assigned_agent_code=dev_agent_code,
            instruction=instruction,
            delivery_mode=DELIVERY_MODE_MERGED_INCREMENT,
            external_refs=[
                {"url": marker_ref, "title": "Lead-created deploy scaffolding follow-up"},
            ],
            task_relationships=[
                {
                    "kind": "depends_on",
                    "task_ids": [source_task_id],
                    "match_mode": "all",
                    "statuses": ["merged"],
                }
            ],
        )
    )
    followup_task_id = str((created or {}).get("id") or "").strip()
    if not followup_task_id:
        return None
    TaskApplicationService(db, actor, command_id=f"{command_id}:run").request_automation_run(
        followup_task_id,
        TaskAutomationRun(
            instruction=instruction,
            source="runner_orchestrator",
            source_task_id=source_task_id,
        ),
        wake_runner=False,
    )
    _ensure_source_task_resumes_after_followup(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        task_id=source_task_id,
        state=state,
        actor_user_id=actor_user_id,
        followup_task_id=followup_task_id,
        instruction=(
            "Resume Lead deploy after the linked deployment scaffolding task completes. "
            "Use the current merged repository state, run the managed Docker Compose deploy, verify "
            f"`http://gateway:{port_text}{normalized_health_path}` returns HTTP 200, and confirm `/` serves application content before handing off to QA."
        ),
    )
    return followup_task_id


def _ensure_source_task_resumes_after_followup(
    *,
    db,
    workspace_id: str,
    project_id: str,
    task_id: str,
    state: dict[str, object],
    actor_user_id: str,
    followup_task_id: str,
    instruction: str,
) -> None:
    from features.tasks.command_handlers import _effective_completed_status_for_project

    completed_status = _effective_completed_status_for_project(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    current_triggers = normalize_execution_triggers(state.get("execution_triggers"))
    for trigger in current_triggers:
        if str(trigger.get("kind") or "").strip().lower() != TRIGGER_KIND_STATUS_CHANGE:
            continue
        if str(trigger.get("scope") or "").strip().lower() != STATUS_SCOPE_EXTERNAL:
            continue
        selector = trigger.get("selector")
        task_ids = selector.get("task_ids") if isinstance(selector, dict) else None
        if isinstance(task_ids, list) and str(followup_task_id) in {str(item or "").strip() for item in task_ids}:
            return
    updated_triggers = [
        *current_triggers,
        {
            "kind": TRIGGER_KIND_STATUS_CHANGE,
            "enabled": True,
            "scope": STATUS_SCOPE_EXTERNAL,
            "match_mode": STATUS_MATCH_ALL,
            "selector": {"task_ids": [followup_task_id]},
            "to_statuses": [completed_status],
            "action": "run_automation",
        },
    ]
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "execution_triggers": updated_triggers,
            "instruction": instruction,
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": task_id,
        },
    )


def _create_lead_runtime_health_followup(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    state: dict[str, object],
    actor_user_id: str,
    port: int | None,
    health_path: str | None,
) -> str | None:
    normalized_project_id = str(project_id or "").strip()
    source_task_id = str(state.get("id") or "").strip()
    if not workspace_id or not normalized_project_id or not source_task_id:
        return None
    marker_ref = f"evidence://lead/{source_task_id}/runtime-health-followup"
    existing_tasks = db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.project_id == normalized_project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        )
    ).scalars().all()
    for task in existing_tasks:
        refs = getattr(task, "external_refs", None)
        if isinstance(refs, list):
            for item in refs:
                if isinstance(item, dict) and str(item.get("url") or "").strip() == marker_ref:
                    return str(task.id or "").strip() or None

    project_name = str(state.get("project_name") or "").strip()
    if not project_name:
        project_row = db.get(Project, normalized_project_id)
        project_name = str(getattr(project_row, "name", "") or "").strip()
    repo_root = resolve_project_repository_path(
        project_name=project_name or None,
        project_id=normalized_project_id,
    )
    if not _repo_has_application_source_files(repo_root=repo_root):
        return None

    dev_assignee_id, dev_agent_code = _resolve_team_agent_assignment_by_role(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        authority_role="Developer",
    )
    if not str(dev_agent_code or "").strip():
        return None

    port_text = str(int(port)) if port is not None else "the configured runtime port"
    normalized_health_path = str(health_path or "/health").strip() or "/health"
    source_title = str(state.get("title") or source_task_id).strip()
    instruction = (
        "Analyze the merged repository state and fix only the runtime/deployment issues needed for managed Docker Compose health verification. "
        "Work only on the task branch, never on main directly. "
        f"Target runtime health endpoint `http://gateway:{port_text}{normalized_health_path}` and ensure the app also serves useful content at `/`. "
        "Use the existing repository shape to correct runtime wiring, startup command, health endpoint behavior, compose settings, or container configuration. "
        "Do not invent placeholder application files or fake product shells."
    )

    from features.tasks.application import TaskApplicationService

    actor = db.get(UserModel, actor_user_id) or db.get(UserModel, AGENT_SYSTEM_USER_ID)
    if actor is None:
        return None
    command_id = f"lead-runtime-followup-{source_task_id[:8]}"
    created = TaskApplicationService(db, actor, command_id=command_id).create_task(
        TaskCreate(
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            specification_id=str(state.get("specification_id") or "").strip() or None,
            title=f"Fix deployment runtime health for {source_title}",
            description=(
                f"Fix the runtime/deployment issues needed to unblock Lead deploy verification for `{source_title}`."
            ),
            status=REQUIRED_SEMANTIC_STATUSES["todo"],
            priority="High",
            assignee_id=dev_assignee_id,
            assigned_agent_code=dev_agent_code,
            instruction=instruction,
            delivery_mode=DELIVERY_MODE_MERGED_INCREMENT,
            external_refs=[
                {"url": marker_ref, "title": "Lead-created runtime health follow-up"},
            ],
            task_relationships=[
                {
                    "kind": "depends_on",
                    "task_ids": [source_task_id],
                    "match_mode": "all",
                    "statuses": ["merged"],
                }
            ],
        )
    )
    followup_task_id = str((created or {}).get("id") or "").strip()
    if not followup_task_id:
        return None
    TaskApplicationService(db, actor, command_id=f"{command_id}:run").request_automation_run(
        followup_task_id,
        TaskAutomationRun(
            instruction=instruction,
            source="runner_orchestrator",
            source_task_id=source_task_id,
        ),
        wake_runner=False,
    )
    _ensure_source_task_resumes_after_followup(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        task_id=source_task_id,
        state=state,
        actor_user_id=actor_user_id,
        followup_task_id=followup_task_id,
        instruction=(
            "Resume Lead deploy after the linked runtime remediation task completes. "
            "Use the current merged repository state, run the managed Docker Compose deploy, verify "
            f"`http://gateway:{port_text}{normalized_health_path}` returns HTTP 200, and confirm `/` serves application content before handing off to QA."
        ),
    )
    return followup_task_id


def _is_developer_main_reconciliation_error(error: str | None) -> bool:
    normalized_error = str(error or "").strip().lower()
    if not normalized_error:
        return False
    return (
        "developer merge to main failed" in normalized_error
        or "deterministic merge to main failed" in normalized_error
        or "automatic merge failed" in normalized_error
        or "merge conflict" in normalized_error
        or "conflict (" in normalized_error
        or "must be reconciled with the latest `main`" in normalized_error
        or "does not contain current `main`" in normalized_error
    )


def _requeue_developer_main_reconciliation(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    state: dict[str, object],
    actor_user_id: str,
    failed_at_iso: str,
    failure_reason: str,
) -> bool:
    from features.tasks.application import TaskApplicationService

    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return False
    developer_agent_code = str(state.get("assigned_agent_code") or "").strip()
    developer_assignee_id = str(state.get("assignee_id") or "").strip() or None
    if canonicalize_role(
        _resolve_assignee_project_role(
            db=db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            assignee_id=developer_assignee_id or "",
            assigned_agent_code=developer_agent_code,
            task_labels=state.get("labels"),
            task_status=str(state.get("status") or ""),
        )
    ) != "Developer":
        return False
    actor = db.get(UserModel, actor_user_id) or db.get(UserModel, AGENT_SYSTEM_USER_ID)
    if actor is None or not bool(getattr(actor, "is_active", False)):
        return False
    branch_name = _extract_task_branch_from_refs(state.get("external_refs"))
    branch_hint = f" on `{branch_name}`" if str(branch_name or "").strip() else ""
    instruction = (
        "Reconcile the latest `main` into your task branch without editing `main` directly.\n"
        f"Work only{branch_hint} inside the assigned task worktree.\n"
        "1) Bring the latest `main` changes into the task branch.\n"
        "2) Resolve all merge conflicts on the task branch.\n"
        "3) Keep the intended task behavior and preserve valid deployment/runtime files already introduced on `main` unless this task deliberately replaces them.\n"
        "4) Run the relevant tests/checks again.\n"
        "5) Commit the reconciliation on the task branch and leave the task merge-ready.\n"
        "Do not commit directly to `main`."
    )
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "assignee_id": developer_assignee_id,
            "assigned_agent_code": developer_agent_code or None,
            "status": REQUIRED_SEMANTIC_STATUSES["active"],
            **_team_mode_progress_payload(
                phase="implementation",
                blocking_gate="developer_main_reconciliation_required",
                blocked_reason=str(failure_reason or "").strip() or None,
                blocked_at=failed_at_iso,
            ),
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": normalized_project_id,
            "task_id": task_id,
        },
    )
    TaskApplicationService(db, actor, command_id=f"tm-dev-sync-{task_id[:8]}").request_automation_run(
        task_id,
        TaskAutomationRun(
            instruction=instruction,
            source="main_reconcile",
            source_task_id=task_id,
            workflow_scope="team_mode",
            execution_mode="resume_execution",
        ),
        wake_runner=False,
    )
    return True


def _requeue_developer_committed_handoff(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    state: dict[str, object],
    actor_user_id: str,
    failed_at_iso: str,
    failure_reason: str,
) -> bool:
    from features.tasks.application import TaskApplicationService

    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return False
    developer_agent_code = str(state.get("assigned_agent_code") or "").strip()
    developer_assignee_id = str(state.get("assignee_id") or "").strip() or None
    if canonicalize_role(
        _resolve_assignee_project_role(
            db=db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            assignee_id=developer_assignee_id or "",
            assigned_agent_code=developer_agent_code,
            task_labels=state.get("labels"),
            task_status=str(state.get("status") or ""),
        )
    ) != "Developer":
        return False
    actor = db.get(UserModel, actor_user_id) or db.get(UserModel, AGENT_SYSTEM_USER_ID)
    if actor is None or not bool(getattr(actor, "is_active", False)):
        return False
    branch_name = _extract_task_branch_from_refs(state.get("external_refs"))
    branch_hint = f" on `{branch_name}`" if str(branch_name or "").strip() else ""
    instruction = (
        "Continue the implementation on the assigned task branch and leave a real committed Developer handoff.\n"
        f"Work only{branch_hint} inside the assigned task worktree.\n"
        "1) Make the remaining code/content changes needed for this task.\n"
        "2) Commit the work on the task branch.\n"
        "3) Ensure the branch is ahead of `main` with a clean working tree.\n"
        "4) Run the relevant tests/checks again.\n"
        "5) Record commit + task branch evidence and leave the task merge-ready.\n"
        "Do not commit directly to `main`."
    )
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "assignee_id": developer_assignee_id,
            "assigned_agent_code": developer_agent_code or None,
            "status": REQUIRED_SEMANTIC_STATUSES["active"],
            **_team_mode_progress_payload(
                phase="implementation",
                blocking_gate="developer_handoff_not_committed",
                blocked_reason=str(failure_reason or "").strip() or None,
                blocked_at=failed_at_iso,
            ),
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": normalized_project_id,
            "task_id": task_id,
        },
    )
    TaskApplicationService(db, actor, command_id=f"tm-dev-handoff-{task_id[:8]}").request_automation_run(
        task_id,
        TaskAutomationRun(
            instruction=instruction,
            source="developer_handoff_recovery",
            source_task_id=task_id,
            workflow_scope="team_mode",
            execution_mode="resume_execution",
        ),
        wake_runner=False,
    )
    return True


def _requeue_developer_after_deploy_lock(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    state: dict[str, object],
    actor_user_id: str,
    failed_at_iso: str,
    failure_reason: str,
) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return False
    developer_agent_code = str(state.get("assigned_agent_code") or "").strip()
    developer_assignee_id = str(state.get("assignee_id") or "").strip() or None
    if canonicalize_role(
        _resolve_assignee_project_role(
            db=db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            assignee_id=developer_assignee_id or "",
            assigned_agent_code=developer_agent_code,
            task_labels=state.get("labels"),
            task_status=str(state.get("status") or ""),
        )
    ) != "Developer":
        return False
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "assignee_id": developer_assignee_id,
            "assigned_agent_code": developer_agent_code or None,
            "status": REQUIRED_SEMANTIC_STATUSES["active"],
            **_team_mode_progress_payload(
                phase="implementation",
                blocking_gate="developer_deploy_lock_waiting",
                blocked_reason=str(failure_reason or "").strip() or None,
                blocked_at=failed_at_iso,
            ),
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": normalized_project_id,
            "task_id": task_id,
        },
    )
    return True


def _translate_compose_manifest_for_host_runtime(
    *,
    manifest_path: Path,
    repo_root_host: Path,
) -> Path:
    content = manifest_path.read_text(encoding="utf-8")
    host_root_text = str(repo_root_host).rstrip("/")

    def _replace_relative_bind_source(match: re.Match[str]) -> str:
        prefix = str(match.group("prefix") or "")
        source = str(match.group("source") or "").strip()
        suffix = str(match.group("suffix") or "")
        normalized_source = source[2:] if source.startswith("./") else ""
        if normalized_source in {"", "/"}:
            translated_source = f"{host_root_text}/"
        else:
            translated_source = f"{host_root_text}/{normalized_source.lstrip('/')}"
        return f"{prefix}{translated_source}{suffix}"

    translated = re.sub(
        r"(?m)^(?P<prefix>\s*-\s*)(?P<source>\./[^:\n]*|\./)(?P<suffix>:[^\n]+)$",
        _replace_relative_bind_source,
        content,
    )
    translated = re.sub(
        r"(?m)^(?P<prefix>\s*source:\s*)(?P<source>\./[^\s#]+|\./)(?P<suffix>\s*(?:#.*)?)$",
        _replace_relative_bind_source,
        translated,
    )

    translated_manifest_path = manifest_path.parent / ".constructos.host.compose.yml"
    translated_manifest_path.write_text(translated, encoding="utf-8")
    return translated_manifest_path


def _run_docker_compose_up_with_error(
    *,
    cwd: Path,
    stack: str,
    manifest_path: Path | None = None,
    remove_orphans: bool = False,
) -> tuple[int, str, str]:
    wrapper = Path(__file__).resolve().parents[2] / "scripts" / "docker_wrapper.sh"
    env = dict(os.environ)
    env["AGENT_DOCKER_PROJECT_NAME"] = str(stack or "").strip()
    args = ["sh", str(wrapper), "compose", "-p", str(stack or "").strip()]
    if manifest_path is not None:
        args.extend(["-f", str(manifest_path)])
    manifest_text = ""
    if manifest_path is not None and manifest_path.exists():
        try:
            manifest_text = manifest_path.read_text(encoding="utf-8")
        except Exception:
            manifest_text = ""
    if re.search(r"(?m)^\s*build\s*:", manifest_text):
        args.extend(["up", "-d", "--build"])
    else:
        args.extend(["up", "-d"])
    if remove_orphans:
        args.append("--remove-orphans")
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    return int(proc.returncode), str(proc.stdout or "").strip(), str(proc.stderr or "").strip()


def _is_lead_safe_compose_orphan_error(error: str | None) -> bool:
    normalized_error = str(error or "").strip().lower()
    if not normalized_error:
        return False
    return "found orphan containers" in normalized_error and (
        "removed or renamed this service" in normalized_error
        or "remove-orphan" in normalized_error
        or "--remove-orphans" in normalized_error
    )


def _is_lead_deploy_topology_reconciliation_error(error: str | None) -> bool:
    normalized_error = str(error or "").strip().lower()
    if not normalized_error:
        return False
    if _is_lead_safe_compose_orphan_error(normalized_error):
        return True
    return (
        "lead deploy execution failed" in normalized_error
        and (
            "compose project has active orphaned service state" in normalized_error
            or "service identity changed" in normalized_error
            or "renamed this service" in normalized_error
        )
    )


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
    qa_assignee_id, qa_agent_code = _resolve_team_agent_assignment_by_role(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        authority_role="QA",
    )
    if not qa_agent_code:
        return 0
    current_automation_state = str(lead_state.get("automation_state") or "").strip().lower()
    active_same_request = (
        current_automation_state in {"queued", "running"}
        and str(lead_state.get("last_requested_source") or "").strip() == "lead_handoff"
        and str(lead_state.get("last_requested_correlation_id") or "").strip() == lead_handoff_token
        and str(lead_state.get("last_requested_source_task_id") or "").strip() == str(lead_task_id or "").strip()
    )
    if active_same_request:
        return 0
    if (
        str(lead_state.get("last_requested_source") or "").strip() == "lead_handoff"
        and str(lead_state.get("last_requested_correlation_id") or "").strip() == lead_handoff_token
        and current_automation_state == "completed"
    ):
        return 0
    instruction = (
        str(lead_state.get("instruction") or "").strip()
        or str(lead_state.get("scheduled_instruction") or "").strip()
    )
    lead_deploy_execution = (
        lead_state.get("last_deploy_execution")
        if isinstance(lead_state.get("last_deploy_execution"), dict)
        else None
    )
    if not is_strict_deploy_success_snapshot(lead_deploy_execution):
        return 0
    lead_transition = lead_deploy_success_transition()
    qa_handoff_status = str(lead_transition.get("status") or REQUIRED_SEMANTIC_STATUSES["active"])

    def _queue_handoff_for_task(*, qa_task_id: str, qa_state: dict[str, Any], same_task: bool) -> bool:
        qa_instruction = (
            str(qa_state.get("instruction") or "").strip()
            or str(qa_state.get("scheduled_instruction") or "").strip()
            or instruction
        )
        if not qa_instruction:
            return False
        qa_automation_state = str(qa_state.get("automation_state") or "").strip().lower()
        active_same_qa_request = (
            qa_automation_state in {"queued", "running"}
            and str(qa_state.get("last_requested_source") or "").strip() == "lead_handoff"
            and str(qa_state.get("last_requested_correlation_id") or "").strip() == lead_handoff_token
            and str(qa_state.get("last_requested_source_task_id") or "").strip() == str(lead_task_id or "").strip()
        )
        if active_same_qa_request:
            return False
        if (
            str(qa_state.get("last_requested_source") or "").strip() == "lead_handoff"
            and str(qa_state.get("last_requested_correlation_id") or "").strip() == lead_handoff_token
            and qa_automation_state == "completed"
        ):
            return False
        update_payload: dict[str, Any] = {
            "status": qa_handoff_status,
            **_team_mode_progress_payload(phase=str(lead_transition.get("phase") or "qa_validation")),
            "last_lead_handoff_token": lead_handoff_token,
            "last_lead_handoff_at": lead_handoff_at,
            "last_lead_handoff_refs_json": lead_handoff_refs,
            "last_lead_handoff_deploy_execution": lead_deploy_execution,
        }
        if same_task:
            update_payload["assignee_id"] = qa_assignee_id
            update_payload["assigned_agent_code"] = qa_agent_code
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=qa_task_id,
            event_type=TASK_EVENT_UPDATED,
            payload=update_payload,
            metadata={
                "actor_id": actor_user_id,
                "workspace_id": workspace_id,
                "project_id": normalized_project_id,
                "task_id": qa_task_id,
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=qa_task_id,
            event_type=EVENT_AUTOMATION_REQUESTED,
            payload={
                "requested_at": lead_handoff_at,
                "instruction": qa_instruction,
                "source": "lead_handoff",
                "source_task_id": lead_task_id,
                "reason": "lead_handoff",
                "trigger_link": f"{lead_task_id}->{qa_task_id}:QA",
                "correlation_id": lead_handoff_token,
                "trigger_task_id": lead_task_id,
                "from_status": qa_handoff_status,
                "to_status": qa_handoff_status,
                "triggered_at": lead_handoff_at,
                "lead_handoff_token": lead_handoff_token,
                "lead_handoff_at": lead_handoff_at,
                "lead_handoff_refs": lead_handoff_refs,
                "lead_handoff_deploy_execution": lead_deploy_execution,
            },
            metadata={
                "actor_id": actor_user_id,
                "workspace_id": workspace_id,
                "project_id": normalized_project_id,
                "task_id": qa_task_id,
                "trigger_task_id": lead_task_id,
                "trigger_from_status": REQUIRED_SEMANTIC_STATUSES["active"],
                "trigger_to_status": REQUIRED_SEMANTIC_STATUSES["active"],
                "triggered_at": lead_handoff_at,
            },
        )
        return True

    queued = 0
    rows = db.execute(
        select(Task.id, Task.status).where(
            Task.workspace_id == workspace_id,
            Task.project_id == normalized_project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        )
    ).all()
    for qa_task_id_value, qa_status in rows:
        qa_task_id = str(qa_task_id_value or "").strip()
        if not qa_task_id or qa_task_id == str(lead_task_id or "").strip():
            continue
        qa_state, _ = rebuild_state(db, "Task", qa_task_id)
        qa_role = _resolve_assignee_project_role(
            db=db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            assignee_id=str(qa_state.get("assignee_id") or ""),
            assigned_agent_code=str(qa_state.get("assigned_agent_code") or ""),
            task_labels=qa_state.get("labels"),
            task_status=str(qa_status or ""),
        )
        if not is_qa_role(qa_role):
            continue
        relationships = qa_state.get("task_relationships")
        if not isinstance(relationships, list):
            continue
        matches_lead_handoff = False
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            if str(relationship.get("kind") or "").strip().lower() != "hands_off_to":
                continue
            related_ids = {
                str(item or "").strip()
                for item in (relationship.get("task_ids") or [])
                if str(item or "").strip()
            }
            if str(lead_task_id or "").strip() in related_ids:
                matches_lead_handoff = True
                break
        if not matches_lead_handoff:
            continue
        if _queue_handoff_for_task(qa_task_id=qa_task_id, qa_state=qa_state, same_task=False):
            queued += 1

    if queued > 0:
        return queued

    if _queue_handoff_for_task(
        qa_task_id=str(lead_task_id),
        qa_state=lead_state,
        same_task=True,
    ):
        return 1
    return 0


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
            Task.status != REQUIRED_SEMANTIC_STATUSES["completed"],
        )
    ).all()

    merged_task_ids: list[str] = []
    merged_at = to_iso_utc(datetime.now(timezone.utc))
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
        phase = str((rebuild_state(db, "Task", task_id_text)[0] or {}).get("team_mode_phase") or "").strip()
        if role != "Lead" and phase != "deploy_ready":
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
                    payload={
                        "external_refs": merged_refs,
                        "last_merged_at": merged_at,
                        "last_merged_commit_sha": out_main_sha,
                        **_team_mode_progress_payload(phase="deploy_ready"),
                    },
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
            payload={
                "external_refs": merged_refs,
                "last_merged_at": merged_at,
                "last_merged_commit_sha": out_main_sha,
                **_team_mode_progress_payload(phase="deploy_ready"),
            },
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
    return normalized.startswith("agent runner: request accepted, leaving progress note.") or normalized.startswith(
        "codex runner: request accepted, leaving progress note."
    )


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
        or _TEAM_MODE_LEAD_COMMITTED_HANDOFF_GATED_FRAGMENT in text
    )


def _is_nonblocking_notification_gate(blocking_gate: str | None) -> bool:
    normalized_gate = str(blocking_gate or "").strip()
    return normalized_gate in {
        "lead_waiting_merge_ready_developer",
        "lead_waiting_committed_developer_handoff",
        "qa_waiting_lead_handoff",
        "qa_waiting_current_deploy_cycle",
    }


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


def _resolve_team_mode_human_owner_user_id(*, db, workspace_id: str, project_id: str | None) -> str | None:
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
    ).first()
    if row is None:
        return None
    try:
        config = json.loads(str(row[0] or "").strip() or "{}")
    except Exception:
        config = {}
    oversight = config.get("oversight") if isinstance(config, dict) and isinstance(config.get("oversight"), dict) else {}
    user_id = str(oversight.get("human_owner_user_id") or "").strip()
    return user_id or None


def _resolve_team_mode_reviewer_user_id(*, db, workspace_id: str, project_id: str | None) -> str | None:
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
    ).first()
    if row is None:
        return None
    try:
        config = json.loads(str(row[0] or "").strip() or "{}")
    except Exception:
        config = {}
    review_policy = config.get("review_policy") if isinstance(config, dict) and isinstance(config.get("review_policy"), dict) else {}
    reviewer_user_id = str(review_policy.get("reviewer_user_id") or "").strip()
    if reviewer_user_id:
        return reviewer_user_id
    oversight = config.get("oversight") if isinstance(config, dict) and isinstance(config.get("oversight"), dict) else {}
    human_owner_user_id = str(oversight.get("human_owner_user_id") or "").strip()
    return human_owner_user_id or None


def _team_mode_review_gate_pending(*, state: dict[str, Any] | None, project_requires_review: bool) -> bool:
    if not project_requires_review:
        return False
    snapshot = state if isinstance(state, dict) else {}
    review_status = str(snapshot.get("review_status") or "").strip().lower()
    return review_status != "approved"


def _resolve_notification_human_user_ids(*, db, workspace_id: str, project_id: str | None) -> list[str]:
    project_humans = _resolve_project_human_member_user_ids(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    if project_humans:
        return project_humans

    workspace_humans = [
        str(user_id or "").strip()
        for user_id in db.execute(
            select(WorkspaceMember.user_id)
            .join(UserModel, UserModel.id == WorkspaceMember.user_id)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                UserModel.is_active == True,  # noqa: E712
                UserModel.user_type != "agent",
            )
            .order_by(WorkspaceMember.id.asc())
        ).scalars().all()
        if str(user_id or "").strip()
    ]
    if workspace_humans:
        return list(dict.fromkeys(workspace_humans))

    fallback_user = db.get(UserModel, DEFAULT_USER_ID)
    if fallback_user is not None and bool(fallback_user.is_active) and str(fallback_user.user_type or "").strip().lower() != "agent":
        return [DEFAULT_USER_ID]
    return []


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
            "assigned_agent_code": current_assigned_agent_code or None,
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
    normalized_reason = str(failure_reason or "").strip()
    reason_hash = hashlib.sha1(normalized_reason.encode("utf-8")).hexdigest()[:12] if normalized_reason else "none"
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
        dedupe_key=f"runner-human-handoff:{task_id}:{reason_hash}",
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


def _handoff_failed_team_mode_task_to_lead(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    state: dict[str, object] | None,
    actor_user_id: str,
    failed_at_iso: str,
    failure_reason: str,
    failed_role: str | None,
) -> str | None:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return None
    lead_assignee_id, lead_agent_code = _resolve_team_agent_assignment_by_role(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        authority_role="Lead",
    )
    if not str(lead_agent_code or "").strip():
        return None
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "assignee_id": lead_assignee_id,
            "assigned_agent_code": lead_agent_code,
            "status": REQUIRED_SEMANTIC_STATUSES["blocked"],
            **_team_mode_progress_payload(
                phase="blocked",
                blocking_gate=_classify_team_mode_failure_gate(
                    assignee_role=failed_role,
                    error=failure_reason,
                ),
                blocked_reason=str(failure_reason or "").strip() or None,
                blocked_at=failed_at_iso,
            ),
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": normalized_project_id,
            "task_id": task_id,
        },
    )
    return str(lead_agent_code or "").strip() or None


def _resolve_team_mode_return_developer(
    *,
    db,
    workspace_id: str,
    project_id: str,
    state: dict[str, object],
) -> tuple[str | None, str | None]:
    review_source_assignee_id = str(state.get("review_source_assignee_id") or "").strip() or None
    review_source_assigned_agent_code = str(state.get("review_source_assigned_agent_code") or "").strip() or None
    if review_source_assignee_id or review_source_assigned_agent_code:
        resolved_role = canonicalize_role(
            _resolve_assignee_project_role(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                assignee_id=review_source_assignee_id or "",
                assigned_agent_code=review_source_assigned_agent_code or "",
                task_labels=state.get("labels"),
                task_status=str(state.get("status") or ""),
            )
        )
        if resolved_role == "Developer":
            return review_source_assignee_id, review_source_assigned_agent_code
    return _resolve_team_agent_assignment_by_role(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
        authority_role="Developer",
    )


def _handoff_failed_team_mode_lead_task_to_developer(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    state: dict[str, object],
    actor_user_id: str,
    failed_at_iso: str,
    failure_reason: str,
    failure_gate: str | None,
) -> bool:
    from features.tasks.application import TaskApplicationService

    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id or not task_id:
        return False
    developer_assignee_id, developer_agent_code = _resolve_team_mode_return_developer(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        state=state,
    )
    if not str(developer_agent_code or "").strip():
        return False
    actor = db.get(UserModel, actor_user_id) or db.get(UserModel, AGENT_SYSTEM_USER_ID)
    if actor is None or not bool(getattr(actor, "is_active", False)):
        return False

    normalized_gate = str(failure_gate or "").strip() or _classify_team_mode_failure_gate(
        assignee_role="Lead",
        error=failure_reason,
    )
    instruction = (
        "Lead triage found a deploy/runtime blocker that requires Developer remediation.\n"
        "Work only on the assigned task branch. Do not commit directly to `main`.\n"
        "1) Analyze the current merged repository and runtime topology.\n"
        "2) Fix the deploy/runtime artifact mismatch that blocked Lead.\n"
        "3) Keep service identity, compose topology, and runtime wiring stable across deploy cycles.\n"
        "4) Re-run the relevant checks for the task.\n"
        "5) Commit the remediation on the task branch and leave the task merge-ready for another Lead deploy cycle.\n"
        f"Lead triage finding: {str(failure_reason or '').strip()[:500]}"
    )
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "assignee_id": developer_assignee_id,
            "assigned_agent_code": developer_agent_code or None,
            "status": REQUIRED_SEMANTIC_STATUSES["blocked"],
            **_team_mode_progress_payload(
                phase="blocked",
                blocking_gate=normalized_gate,
                blocked_reason=str(failure_reason or "").strip() or None,
                blocked_at=failed_at_iso,
            ),
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": normalized_project_id,
            "task_id": task_id,
        },
    )
    TaskApplicationService(db, actor, command_id=f"lead-dev-triage-{task_id[:8]}").request_automation_run(
        task_id,
        TaskAutomationRun(
            instruction=instruction,
            source="lead_triage_return",
            source_task_id=task_id,
            workflow_scope="team_mode",
            execution_mode="resume_execution",
        ),
        wake_runner=False,
    )
    return True


def _is_blocked_outcome(*, summary: str | None, comment: str | None) -> bool:
    summary_head = str(summary or "").strip().splitlines()[0:1]
    comment_head = str(comment or "").strip().splitlines()[0:1]
    summary_first = summary_head[0].strip().upper() if summary_head else ""
    comment_first = comment_head[0].strip().upper() if comment_head else ""
    return summary_first == _AUTOMATION_BLOCKED_MARKER or comment_first == _AUTOMATION_BLOCKED_MARKER


def _team_mode_progress_comment_fingerprint(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    state: dict[str, object],
    assignee_role: str | None,
) -> str | None:
    normalized_role = str(assignee_role or "").strip()
    normalized_project_id = str(project_id or "").strip()
    if normalized_role not in TEAM_MODE_WORKFLOW_ROLES:
        return None
    if not workspace_id or not normalized_project_id or not task_id:
        return None

    gate_key = _current_nonblocking_gate_key(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        assignee_role=normalized_role,
        task_status=str(state.get("status") or "").strip(),
        task_state=state,
    ) or str(state.get("team_mode_blocking_gate") or "").strip()

    related_task_ids: set[str] = set()
    for relationship in normalize_task_relationships(state.get("task_relationships")):
        for related_task_id in relationship.get("task_ids") or []:
            normalized_related_id = str(related_task_id or "").strip()
            if normalized_related_id:
                related_task_ids.add(normalized_related_id)

    related_snapshots: list[dict[str, object]] = []
    for related_task_id in sorted(related_task_ids):
        related_state, _ = rebuild_state(db, "Task", related_task_id)
        related_snapshots.append(
            {
                "id": related_task_id,
                "status": str(related_state.get("status") or "").strip(),
                "automation_state": str(related_state.get("automation_state") or "idle").strip().lower(),
                "blocking_gate": str(related_state.get("team_mode_blocking_gate") or "").strip() or None,
                "last_requested_source": str(related_state.get("last_requested_source") or "").strip() or None,
                "last_lead_handoff_token": str(related_state.get("last_lead_handoff_token") or "").strip() or None,
            }
        )

    fingerprint_payload = {
        "task_id": task_id,
        "role": normalized_role,
        "status": str(state.get("status") or "").strip(),
        "automation_state": str(state.get("automation_state") or "idle").strip().lower(),
        "phase": str(state.get("team_mode_phase") or "").strip() or None,
        "blocking_gate": gate_key or None,
        "last_requested_source": str(state.get("last_requested_source") or "").strip() or None,
        "last_requested_source_task_id": str(state.get("last_requested_source_task_id") or "").strip() or None,
        "last_lead_handoff_token": str(state.get("last_lead_handoff_token") or "").strip() or None,
        "task_relationships": normalize_task_relationships(state.get("task_relationships")),
        "related_tasks": related_snapshots,
    }
    payload_text = json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload_text.encode("utf-8")).hexdigest()


def _should_persist_team_mode_progress_comment(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    state: dict[str, object],
    assignee_role: str | None,
) -> tuple[bool, str | None]:
    fingerprint = _team_mode_progress_comment_fingerprint(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        state=state,
        assignee_role=assignee_role,
    )
    if not fingerprint:
        return True, None
    last_fingerprint = str(state.get("last_progress_comment_fingerprint") or "").strip()
    if last_fingerprint and last_fingerprint == fingerprint:
        return False, fingerprint
    return True, fingerprint


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
        status_text = str(state.get("status") or "").strip()
        completed_at = str(state.get("completed_at") or "").strip()
        if semantic_status_key(status=status_text) == "completed" or status_text.casefold() == "done" or completed_at:
            done += 1
    total = len(task_ids)
    return {
        "all_done": bool(total > 0 and done == total),
        "total": total,
        "done": done,
        "task_ids": sorted(task_ids),
    }


def _parse_json_list_value(raw: object) -> list[dict[str, object]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _project_completion_task_snapshots(*, db, workspace_id: str, project_id: str) -> dict[str, object]:
    project = db.get(Project, project_id)
    project_name = str(getattr(project, "name", "") or "").strip() or project_id
    task_rows = db.execute(
        select(Task.id, Task.title, Task.external_refs).where(
            Task.workspace_id == workspace_id,
            Task.project_id == project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        )
    ).all()
    tasks: list[dict[str, object]] = []
    for task_id, title, external_refs_raw in task_rows:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            continue
        state, _ = rebuild_state(db, "Task", normalized_task_id)
        refs = state.get("external_refs")
        if not isinstance(refs, list):
            refs = _parse_json_list_value(external_refs_raw)
        tasks.append(
            {
                "id": normalized_task_id,
                "title": str(state.get("title") or title or normalized_task_id).strip(),
                "status": str(state.get("status") or "").strip(),
                "completed_at": str(state.get("completed_at") or "").strip() or None,
                "project_completion_finalized_at": str(state.get("project_completion_finalized_at") or "").strip()
                or None,
                "last_merged_commit_sha": str(state.get("last_merged_commit_sha") or "").strip() or None,
                "last_deploy_cycle_id": str(state.get("last_deploy_cycle_id") or "").strip() or None,
                "last_deploy_execution": state.get("last_deploy_execution")
                if isinstance(state.get("last_deploy_execution"), dict)
                else {},
                "last_tested_at": str(state.get("last_tested_at") or "").strip() or None,
                "last_human_escalated_at": str(state.get("last_human_escalated_at") or "").strip() or None,
                "external_refs": refs,
            }
        )
    return {
        "project_name": project_name,
        "project_external_refs": _parse_json_list_value(getattr(project, "external_refs", "[]") if project else "[]"),
        "tasks": sorted(tasks, key=lambda item: str(item.get("id") or "")),
    }


def _project_completion_cycle_digest(*, task_snapshots: list[dict[str, object]]) -> str:
    payload = [
        {
            "id": str(item.get("id") or "").strip(),
            "status": str(item.get("status") or "").strip(),
            "completed_at": str(item.get("completed_at") or "").strip() or None,
            "last_merged_commit_sha": str(item.get("last_merged_commit_sha") or "").strip() or None,
            "last_deploy_cycle_id": str(item.get("last_deploy_cycle_id") or "").strip() or None,
        }
        for item in task_snapshots
    ]
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()[:12]


def _derive_authoritative_completion_url(*, task_snapshots: list[dict[str, object]]) -> str | None:
    preferred_urls: list[str] = []
    generic_urls: list[str] = []
    health_urls: list[str] = []
    for task_snapshot in task_snapshots:
        refs = task_snapshot.get("external_refs")
        deploy_snapshot = derive_deploy_execution_snapshot(
            refs=refs,
            current_snapshot=task_snapshot.get("last_deploy_execution") if isinstance(task_snapshot, dict) else None,
        )
        if is_strict_deploy_success_snapshot(deploy_snapshot):
            health_url = str(deploy_snapshot.get("http_url") or "").strip()
            if health_url:
                health_urls.append(health_url)
        for item in _parse_json_list_value(refs):
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            lowered_url = url.casefold()
            if not (lowered_url.startswith("http://") or lowered_url.startswith("https://")):
                continue
            title = str(item.get("title") or "").strip().casefold()
            if any(marker in title for marker in ("live deployment", "deployment url", "release url", "production url")):
                preferred_urls.append(url)
                continue
            if "health" in title or lowered_url.endswith("/health"):
                health_urls.append(url)
                continue
            generic_urls.append(url)
    for collection in (preferred_urls, generic_urls, health_urls):
        for url in collection:
            if url:
                return url
    return None


def _note_title_key(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def _project_completion_note_id(*, project_id: str, title: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"note:{project_id}:{_note_title_key(title)}"))


def _merge_completion_external_ref(
    *,
    existing_refs: list[dict[str, object]],
    deployment_url: str | None,
) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    for item in existing_refs:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        normalized_item = {"url": url}
        title = str(item.get("title") or "").strip()
        source = str(item.get("source") or "").strip()
        if title:
            normalized_item["title"] = title
        if source:
            normalized_item["source"] = source
        merged.append(normalized_item)
    normalized_deployment_url = str(deployment_url or "").strip()
    if normalized_deployment_url and normalized_deployment_url not in seen_urls:
        merged.append(
            {
                "url": normalized_deployment_url,
                "title": "Live deployment URL",
                "source": "team_mode_completion",
            }
        )
    return merged


def _build_project_completion_report(
    *,
    project_name: str,
    finalized_at: str,
    completion_digest: str,
    task_snapshots: list[dict[str, object]],
    deployment_url: str | None,
) -> str:
    completed_tasks: list[str] = []
    merged_commits: list[str] = []
    deploy_cycle_ids: list[str] = []
    qa_evidence: list[str] = []
    escalations: list[str] = []
    seen_commits: set[str] = set()
    seen_cycles: set[str] = set()
    for task_snapshot in task_snapshots:
        title = str(task_snapshot.get("title") or task_snapshot.get("id") or "").strip()
        task_id = str(task_snapshot.get("id") or "").strip()
        completed_tasks.append(f"- {title} (`{task_id}`)")
        commit_sha = str(task_snapshot.get("last_merged_commit_sha") or "").strip().lower()
        if commit_sha and commit_sha not in seen_commits:
            seen_commits.add(commit_sha)
            merged_commits.append(f"- `{commit_sha}`")
        refs = task_snapshot.get("external_refs")
        for commit in sorted(_extract_commit_shas_from_refs(refs)):
            normalized_commit = str(commit or "").strip().lower()
            if not normalized_commit or normalized_commit in seen_commits:
                continue
            seen_commits.add(normalized_commit)
            merged_commits.append(f"- `{normalized_commit}`")
        deploy_cycle_id = str(task_snapshot.get("last_deploy_cycle_id") or "").strip()
        if deploy_cycle_id and deploy_cycle_id not in seen_cycles:
            seen_cycles.add(deploy_cycle_id)
            deploy_cycle_ids.append(f"- `{deploy_cycle_id}`")
        tested_at = str(task_snapshot.get("last_tested_at") or "").strip()
        if tested_at:
            qa_evidence.append(f"- {title}: tested at `{tested_at}`")
        escalated_at = str(task_snapshot.get("last_human_escalated_at") or "").strip()
        if escalated_at:
            escalations.append(f"- {title}: escalated at `{escalated_at}`")

    lines = [
        "# Project Completion Report",
        "",
        f"- Project: **{project_name}**",
        f"- Completion timestamp: `{finalized_at}`",
        f"- Completion cycle: `{completion_digest}`",
    ]
    if deployment_url:
        lines.append(f"- Deployment URL: {deployment_url}")
    lines.extend(
        [
            "",
            "## Completed Tasks",
            *(completed_tasks or ["- None"]),
            "",
            "## Merged Commits",
            *(merged_commits or ["- None"]),
            "",
            "## Deploy Cycles",
            *(deploy_cycle_ids or ["- None"]),
            "",
            "## QA Evidence Summary",
            *(qa_evidence or ["- None recorded"]),
            "",
            "## Blocker And Escalation Summary",
            *(escalations or ["- No human escalations were recorded"]),
        ]
    )
    return "\n".join(lines)


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
    blocking_gate: str | None = None,
    phase: str | None = None,
) -> None:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return
    if _is_nonblocking_notification_gate(blocking_gate):
        return
    human_ids = _resolve_notification_human_user_ids(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    if not human_ids:
        return
    normalized_gate = str(blocking_gate or "").strip() or "unspecified"
    normalized_phase = str(phase or "").strip() or "active"
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
            dedupe_key=f"automation-blocked:{task_id}:{normalized_phase}:{normalized_gate}",
            payload={
                "kind": "automation_blocked",
                "task_id": task_id,
                "blocking_gate": normalized_gate,
                "phase": normalized_phase,
                "summary": str(summary or "").strip(),
                "comment": str(comment or "").strip() or None,
            },
            source_event="agents.runner.automation_blocked",
        )


def _should_notify_humans_about_blocked_automation(
    *,
    team_mode_enabled: bool,
    should_retry: bool,
    non_blocking_gate_failure: bool,
    lead_triage_handoff: bool,
    lead_scaffolding_followup_task_id: str | None,
    developer_main_reconciliation_queued: bool,
    developer_handoff_recovery_queued: bool,
    developer_deploy_lock_waiting: bool,
    lead_developer_triage_queued: bool = False,
    lead_human_escalation: bool = False,
) -> bool:
    if team_mode_enabled:
        return False
    if should_retry or non_blocking_gate_failure or lead_triage_handoff:
        return False
    if str(lead_scaffolding_followup_task_id or "").strip():
        return False
    if lead_developer_triage_queued:
        return False
    if lead_human_escalation:
        return False
    if developer_main_reconciliation_queued:
        return False
    if developer_handoff_recovery_queued:
        return False
    if developer_deploy_lock_waiting:
        return False
    return True


def _notify_humans_team_mode_triage_needed(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    actor_user_id: str,
    gate: str | None,
    task_id: str,
    task_title: str,
) -> None:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return
    normalized_gate = str(gate or "").strip() or "unspecified"
    human_ids = _resolve_notification_human_user_ids(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    if not human_ids:
        return
    message = (
        "One or more Team Mode tasks require Lead triage before automation can continue.\n\n"
        f"Latest task: **{task_title or task_id}**\n"
        f"Gate: `{normalized_gate}`"
    )
    for human_id in human_ids:
        append_notification_created_event(
            db,
            append_event_fn=append_event,
            user_id=human_id,
            message=message,
            actor_id=actor_user_id,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            notification_type="ManualMessage",
            severity="warning",
            dedupe_key=f"team-mode-triage:{normalized_project_id}:{normalized_gate}",
            payload={
                "kind": "team_mode_triage_required",
                "project_id": normalized_project_id,
                "task_id": task_id,
                "gate": normalized_gate,
            },
            source_event="agents.runner.team_mode_triage_required",
        )


def _finalize_project_completion(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    actor_user_id: str,
) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return False
    snapshot = _project_completion_snapshot(db=db, workspace_id=workspace_id, project_id=normalized_project_id)
    if not bool(snapshot.get("all_done")):
        return False
    detail_snapshot = _project_completion_task_snapshots(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    task_snapshots = list(detail_snapshot.get("tasks") or [])
    if not task_snapshots:
        return False
    completion_digest = _project_completion_cycle_digest(task_snapshots=task_snapshots)
    note_title = f"Project Completion Report ({completion_digest})"
    note_id = _project_completion_note_id(project_id=normalized_project_id, title=note_title)
    existing_note = db.get(Note, note_id)
    if existing_note is not None and not bool(existing_note.is_deleted):
        return False
    finalized_at = to_iso_utc(datetime.now(timezone.utc))
    deployment_url = _derive_authoritative_completion_url(task_snapshots=task_snapshots)
    report_body = _build_project_completion_report(
        project_name=str(detail_snapshot.get("project_name") or normalized_project_id),
        finalized_at=finalized_at,
        completion_digest=completion_digest,
        task_snapshots=task_snapshots,
        deployment_url=deployment_url,
    )
    existing_project_refs = list(detail_snapshot.get("project_external_refs") or [])
    merged_project_refs = _merge_completion_external_ref(
        existing_refs=existing_project_refs,
        deployment_url=deployment_url,
    )
    if merged_project_refs != existing_project_refs:
        append_event(
            db,
            aggregate_type="Project",
            aggregate_id=normalized_project_id,
            event_type=PROJECT_EVENT_UPDATED,
            payload={
                "external_refs": merged_project_refs,
                "updated_fields": ["external_refs"],
            },
            metadata={
                "actor_id": actor_user_id,
                "workspace_id": workspace_id,
                "project_id": normalized_project_id,
            },
        )
    for task_snapshot in task_snapshots:
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=str(task_snapshot.get("id") or "").strip(),
            event_type=TASK_EVENT_UPDATED,
            payload={"project_completion_finalized_at": finalized_at},
            metadata={
                "actor_id": actor_user_id,
                "workspace_id": workspace_id,
                "project_id": normalized_project_id,
                "task_id": str(task_snapshot.get("id") or "").strip(),
            },
        )
    append_event(
        db,
        aggregate_type="Note",
        aggregate_id=note_id,
        event_type=NOTE_EVENT_CREATED,
        payload={
            "workspace_id": workspace_id,
            "project_id": normalized_project_id,
            "note_group_id": None,
            "task_id": None,
            "specification_id": None,
            "title": note_title,
            "body": report_body,
            "tags": ["completion-report", "team-mode"],
            "external_refs": _merge_completion_external_ref(existing_refs=[], deployment_url=deployment_url),
            "attachment_refs": [],
            "pinned": False,
            "archived": False,
            "created_by": actor_user_id,
            "updated_by": actor_user_id,
            "created_at": finalized_at,
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": normalized_project_id,
            "note_id": note_id,
        },
    )
    human_ids = _resolve_notification_human_user_ids(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    for human_id in human_ids:
        append_notification_created_event(
            db,
            append_event_fn=append_event,
            user_id=human_id,
            message=(
                "Project workflow reached completion and a final report note was created."
                + (f"\n\nDeployment URL: {deployment_url}" if deployment_url else "")
            ),
            actor_id=actor_user_id,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            notification_type="ManualMessage",
            severity="info",
            dedupe_key=f"project-completed:{normalized_project_id}:{completion_digest}",
            payload={
                "kind": "project_completed",
                "project_id": normalized_project_id,
                "done_tasks": int(snapshot.get("done") or 0),
                "total_tasks": int(snapshot.get("total") or 0),
                "completion_cycle_id": completion_digest,
                "project_completion_finalized_at": finalized_at,
                "note_id": note_id,
                "deployment_url": deployment_url,
            },
            source_event="agents.runner.project_completed",
        )
    return True


def _finalize_project_completion_post_commit(
    *,
    workspace_id: str,
    project_id: str | None,
    actor_user_id: str,
) -> None:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return
    with SessionLocal() as db:
        _finalize_project_completion(
            db=db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            actor_user_id=actor_user_id,
        )
        db.commit()


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
    effective_blocked_status = _effective_blocked_status_for_project(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
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
        )
        .order_by(Task.created_at.asc())
    ).scalars().all()
    all_tasks = [
        task
        for task in all_tasks
        if semantic_status_key(status=getattr(task, "status", None)) != "completed"
    ]
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
        current_automation_state = str(lead_state.get("automation_state") or "").strip().lower()
        active_same_request = (
            current_automation_state in {"queued", "running"}
            and str(lead_state.get("last_requested_source") or "").strip() == "blocker_escalation"
            and str(lead_state.get("last_requested_source_task_id") or "").strip() == str(blocked_task_id or "").strip()
        )
        if active_same_request:
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
                "source_task_id": blocked_task_id,
                "trigger_task_id": blocked_task_id,
                "to_status": blocked_status or effective_blocked_status,
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
                    "source_task_id": blocked_task_id,
                    "blocked_task_id": blocked_task_id,
                    "blocked_status": blocked_status or effective_blocked_status,
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
    blocked_gate = _classify_team_mode_failure_gate(
        assignee_role=blocked_role,
        error=str(blocked_error or "").strip(),
    )
    human_ids = _resolve_notification_human_user_ids(
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
            f"({blocked_role or 'agent'}, status={blocked_status or effective_blocked_status}). "
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
            dedupe_key=f"{dedupe_prefix}:{blocked_task_id}:{blocked_status or effective_blocked_status}:{blocked_gate or 'unspecified'}",
            payload={
                "kind": kind,
                "blocked_task_id": blocked_task_id,
                "blocked_role": blocked_role,
                "blocked_status": blocked_status,
                "queued_lead_tasks": queued,
                "blocking_gate": blocked_gate or None,
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
        resumed_status: str | None = None
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
            if _should_resume_team_mode_agent_task_as_active(
                assignee_role=claim_assignee_role,
                status=str(state.get("status") or ""),
            ):
                resumed_status = REQUIRED_SEMANTIC_STATUSES["active"]
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=task_id,
                    event_type=TASK_EVENT_UPDATED,
                    payload={
                        "status": resumed_status,
                        **_team_mode_progress_payload(
                            phase=_derive_team_mode_phase(
                                assignee_role=claim_assignee_role,
                                status=resumed_status,
                            )
                        ),
                    },
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
    if resumed_status:
        state = dict(state)
        state["status"] = resumed_status
        state["team_mode_phase"] = _derive_team_mode_phase(
            assignee_role=claim_assignee_role,
            status=resumed_status,
        )
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
        and semantic_status_key(status=state.get("status")) in {"todo", "active", "blocked"}
        and _project_has_git_delivery_skill(db=db, workspace_id=workspace_id, project_id=project_id)
    ):
        stack, host, port, health_path, runtime_required = _effective_runtime_deploy_target_for_task(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            delivery_mode=state.get("delivery_mode"),
        )
        if runtime_required:
            port_text = str(port) if port is not None else "UNSET"
            has_merge_to_main = _project_has_merge_to_main_evidence(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            deploy_steps = _build_lead_deploy_instruction_contract(
                stack=stack,
                port_text=port_text,
                health_path=health_path,
                has_merge_to_main=has_merge_to_main,
            )
            instruction = f"{str(instruction or '').strip()}\n\n{deploy_steps}".strip()
    elif (
        is_qa_role(assignee_role)
        and semantic_status_key(status=state.get("status")) in {"active", "blocked"}
        and _project_has_git_delivery_skill(db=db, workspace_id=workspace_id, project_id=project_id)
    ):
        stack, host, port, health_path, runtime_required = _effective_runtime_deploy_target_for_task(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            delivery_mode=state.get("delivery_mode"),
        )
        if runtime_required:
            port_text = str(port) if port is not None else "UNSET"
            qa_steps = _build_qa_runtime_validation_contract(
                stack=stack,
                port_text=port_text,
                health_path=health_path,
            )
            instruction = f"{str(instruction or '').strip()}\n\n{qa_steps}".strip()
    if not instruction:
        return None
    return QueuedAutomationRun(
        task_id=task_id,
        workspace_id=workspace_id,
        project_id=project_id,
        title=str(state.get("title") or ""),
        description=str(state.get("description") or ""),
        status=str(state.get("status") or "To Do"),
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
    completion_check_workspace_id: str | None = None
    completion_check_project_id: str | None = None
    completion_check_actor_user_id: str | None = None
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
            and semantic_status_key(status=state.get("status")) in {"todo", "active", "blocked"}
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
            tests_run = bool(contract.get("tests_run")) if isinstance(contract.get("tests_run"), bool) else False
            tests_passed = bool(contract.get("tests_passed")) if isinstance(contract.get("tests_passed"), bool) else False
            task_branch = str(git_evidence.get("task_branch") or "").strip()
            before_head_sha = str(git_evidence.get("before_head_sha") or "").strip().lower()
            after_head_sha = str(git_evidence.get("after_head_sha") or "").strip().lower()
            after_on_task_branch = bool(git_evidence.get("after_on_task_branch"))
            after_is_dirty = bool(git_evidence.get("after_is_dirty"))
            committed_handoff = _inspect_committed_task_branch_handoff(git_evidence)
            branch_head_sha = str(committed_handoff.get("branch_head_sha") or "").strip().lower()
            branch_ahead_of_main = bool(committed_handoff.get("branch_ahead_of_main"))
            git_evidence, auto_commit = _finalize_developer_handoff_commit_if_safe(
                project_name=project_name,
                project_id=project_id,
                task_id=run.task_id,
                title=str(state.get("title") or run.title or ""),
                git_evidence=git_evidence,
                require_nontrivial_dev_changes=require_nontrivial_dev_changes,
                tests_run=tests_run,
                tests_passed=tests_passed,
            )
            if auto_commit:
                contract.setdefault("commit_sha", str(auto_commit.get("commit_sha") or "").strip().lower())
                contract.setdefault("branch", str(auto_commit.get("task_branch") or "").strip())
                files_changed_list = contract.get("files_changed")
                if not isinstance(files_changed_list, list) or not any(str(item or "").strip() for item in files_changed_list):
                    contract["files_changed"] = list(auto_commit.get("files_changed") or [])
                outcome = AutomationOutcome(
                    action=outcome.action,
                    summary=outcome.summary,
                    comment=outcome.comment,
                    execution_outcome_contract=contract,
                    usage=outcome.usage,
                    codex_session_id=outcome.codex_session_id,
                    resume_attempted=outcome.resume_attempted,
                    resume_succeeded=outcome.resume_succeeded,
                    resume_fallback_used=outcome.resume_fallback_used,
                )
            task_branch = str(git_evidence.get("task_branch") or "").strip()
            before_head_sha = str(git_evidence.get("before_head_sha") or "").strip().lower()
            after_head_sha = str(git_evidence.get("after_head_sha") or "").strip().lower()
            after_on_task_branch = bool(git_evidence.get("after_on_task_branch"))
            after_is_dirty = bool(git_evidence.get("after_is_dirty"))
            committed_handoff = _inspect_committed_task_branch_handoff(git_evidence)
            branch_head_sha = str(committed_handoff.get("branch_head_sha") or "").strip().lower()
            branch_ahead_of_main = bool(committed_handoff.get("branch_ahead_of_main"))
            evidence_missing = not _task_has_git_delivery_completion_evidence(
                state=state,
                summary="",
                comment=None,
                assignee_role=assignee_role,
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
            can_promote_candidate = bool(
                commit_candidate
                and branch_candidate
                and bool(committed_handoff.get("branch_exists"))
                and bool(committed_handoff.get("after_on_task_branch"))
                and not bool(committed_handoff.get("after_is_dirty"))
                and branch_ahead_of_main
                and (not branch_head_sha or commit_candidate == branch_head_sha)
            )
            if can_promote_candidate:
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
        merge_result: dict[str, object] = {}
        action, summary, comment = normalize_success_outcome(
            action=action,
            summary=summary,
            comment=comment,
            instruction=str(run.instruction or "").strip(),
            assignee_role=assignee_role,
            task_state=state,
        )
        normalized_assignee_role = canonicalize_role(assignee_role)
        if team_mode_enabled and normalized_assignee_role in {"Developer", "QA"} and action == "complete":
            action = "comment"
        if (
            action != "complete"
            and git_delivery_enabled
            and not team_mode_enabled
            and semantic_status_key(status=state.get("status")) != "completed"
            and _task_has_git_delivery_completion_evidence(
                state=state,
                summary=summary,
                comment=comment,
                assignee_role=assignee_role,
            )
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

        persist_comment = bool(comment)
        progress_comment_fingerprint: str | None = None
        if persist_comment and team_mode_enabled:
            persist_comment, progress_comment_fingerprint = _should_persist_team_mode_progress_comment(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=run.task_id,
                state=state,
                assignee_role=assignee_role,
            )

        if AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS:
            if action == "complete" and semantic_status_key(status=state.get("status")) != "completed":
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
            if persist_comment and comment:
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
            if progress_comment_fingerprint:
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=TASK_EVENT_UPDATED,
                    payload={
                        "last_progress_comment_fingerprint": progress_comment_fingerprint,
                        "last_progress_comment_at": completed_at,
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
                (is_developer_role(assignee_role) and semantic_status_key(status=current_status) in {"todo", "active", "blocked"} and not commit_shas)
                or (
                    is_qa_role(assignee_role)
                    and semantic_status_key(status=current_status) in {"active", "blocked"}
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
            and semantic_status_key(status=state.get("status")) in {"todo", "active", "blocked"}
            and _task_has_git_delivery_completion_evidence(
                state=state,
                summary=summary,
                comment=comment,
                assignee_role=assignee_role,
            )
        ):
            project_requires_review = _team_mode_review_required_for_project(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            review_required = _team_mode_review_gate_pending(
                state=state,
                project_requires_review=project_requires_review,
            )
            review_requested_at = completed_at
            developer_assignee_id = str(state.get("assignee_id") or "").strip() or None
            developer_agent_code = str(state.get("assigned_agent_code") or "").strip() or None
            delivery_mode = normalize_delivery_mode(state.get("delivery_mode"))
            requires_deploy = task_requires_deploy(delivery_mode)
            from features.tasks.command_handlers import _effective_completed_status_for_project

            completed_status = _effective_completed_status_for_project(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            transition = developer_success_transition(
                review_required=review_required,
                requires_deploy=requires_deploy,
                completed_status=completed_status,
            )
            lead_assignee_id, lead_agent_code = _resolve_team_agent_assignment_by_role(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                authority_role="Lead",
            )
            if not review_required:
                merge_result = _merge_current_task_branch_to_main(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=str(project_id or "").strip(),
                    task_id=run.task_id,
                    actor_user_id=actor_user_id,
                )
                if not bool((merge_result or {}).get("ok")):
                    raise RuntimeError(str((merge_result or {}).get("error") or "Runner error: Developer merge to main failed."))
                state = dict(state)
                state["external_refs"] = list((merge_result or {}).get("external_refs") or state.get("external_refs") or [])
                state["last_merged_commit_sha"] = str((merge_result or {}).get("merge_sha") or "").strip() or None
                state["last_merged_at"] = str((merge_result or {}).get("merged_at") or "").strip() or completed_at
            if review_required:
                reviewer_user_id = _resolve_team_mode_reviewer_user_id(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                ) or DEFAULT_USER_ID
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=TASK_EVENT_UPDATED,
                    payload={
                        "assignee_id": reviewer_user_id,
                        "assigned_agent_code": None,
                        "status": REQUIRED_SEMANTIC_STATUSES["in_review"],
                        "review_required": True,
                        "review_status": "pending",
                        "review_requested_at": review_requested_at,
                        "review_source_assignee_id": developer_assignee_id,
                        "review_source_assigned_agent_code": developer_agent_code,
                        "review_next_lead_assignee_id": lead_assignee_id,
                        "review_next_lead_assigned_agent_code": lead_agent_code,
                        **_team_mode_progress_payload(phase="in_review"),
                    },
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": run.task_id,
                    },
                )
                state = dict(state)
                state["assignee_id"] = reviewer_user_id
                state["assigned_agent_code"] = None
                state["status"] = REQUIRED_SEMANTIC_STATUSES["in_review"]
                state["review_required"] = True
                state["review_status"] = "pending"
                state["review_requested_at"] = review_requested_at
                state["review_source_assignee_id"] = developer_assignee_id
                state["review_source_assigned_agent_code"] = developer_agent_code
                state["review_next_lead_assignee_id"] = lead_assignee_id
                state["review_next_lead_assigned_agent_code"] = lead_agent_code
                state["team_mode_phase"] = "in_review"
            elif bool(transition.get("terminal")):
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=TASK_EVENT_UPDATED,
                    payload={
                        "last_merged_at": str((merge_result or {}).get("merged_at") or "").strip() or completed_at,
                        "last_merged_commit_sha": str((merge_result or {}).get("merge_sha") or "").strip() or None,
                        **_team_mode_progress_payload(phase="completed"),
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
                    event_type=TASK_EVENT_COMPLETED,
                    payload={
                        "completed_at": completed_at,
                        "status": str(transition.get("status") or completed_status),
                    },
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": run.task_id,
                    },
                )
                state = dict(state)
                state["status"] = str(transition.get("status") or completed_status)
                state["completed_at"] = completed_at
                state["last_merged_at"] = str((merge_result or {}).get("merged_at") or "").strip() or completed_at
                state["last_merged_commit_sha"] = str((merge_result or {}).get("merge_sha") or "").strip() or None
                state["team_mode_phase"] = str(transition.get("phase") or "completed")
                queued_followup_developer_dispatches = _queue_team_mode_dispatches(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    source="runner_orchestrator",
                    source_task_id=run.task_id,
                    exclude_task_ids={run.task_id},
                    allowed_roles={"Developer"},
                )
            elif lead_agent_code:
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=TASK_EVENT_UPDATED,
                    payload={
                        "assignee_id": lead_assignee_id,
                        "assigned_agent_code": lead_agent_code,
                        "status": str(transition.get("status") or REQUIRED_SEMANTIC_STATUSES["awaiting_decision"]),
                        "last_merged_at": str((merge_result or {}).get("merged_at") or "").strip() or completed_at,
                        "last_merged_commit_sha": str((merge_result or {}).get("merge_sha") or "").strip() or None,
                        **_team_mode_progress_payload(phase=str(transition.get("phase") or "deploy_ready")),
                    },
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": run.task_id,
                    },
                )
                state = dict(state)
                state["assignee_id"] = lead_assignee_id
                state["assigned_agent_code"] = lead_agent_code
                state["status"] = str(transition.get("status") or REQUIRED_SEMANTIC_STATUSES["awaiting_decision"])
                state["last_merged_at"] = str((merge_result or {}).get("merged_at") or "").strip() or completed_at
                state["last_merged_commit_sha"] = str((merge_result or {}).get("merge_sha") or "").strip() or None
                state["team_mode_phase"] = str(transition.get("phase") or "deploy_ready")
                instruction = (
                    str(run.instruction or "").strip()
                    or str(state.get("instruction") or "").strip()
                    or str(state.get("scheduled_instruction") or "").strip()
                )
                if instruction:
                    append_event(
                        db,
                        aggregate_type="Task",
                        aggregate_id=run.task_id,
                        event_type=EVENT_AUTOMATION_REQUESTED,
                        payload={
                            "requested_at": completed_at,
                            "instruction": instruction,
                            "source": "developer_handoff",
                            "source_task_id": run.task_id,
                        },
                        metadata={
                            "actor_id": actor_user_id,
                            "workspace_id": workspace_id,
                            "project_id": project_id,
                            "task_id": run.task_id,
                        },
                    )
                    state["last_requested_source"] = "developer_handoff"
                    state["last_requested_source_task_id"] = run.task_id
                _rearm_blocked_team_mode_lead_tasks(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                )
                queued_followup_lead_dispatches = _queue_team_mode_dispatches(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    source="developer_handoff",
                    source_task_id=run.task_id,
                    exclude_task_ids={run.task_id},
                    allowed_roles={"Lead"},
                )
                queued_followup_developer_dispatches = _queue_team_mode_dispatches(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    source="runner_orchestrator",
                    source_task_id=run.task_id,
                    exclude_task_ids={run.task_id},
                    allowed_roles={"Developer"},
                )
        if (
            team_mode_enabled
            and git_delivery_enabled
            and canonicalize_role(assignee_role) == "Lead"
            and semantic_status_key(status=state.get("status")) in {"todo", "active", "blocked"}
            and not is_team_mode_kickoff_run
        ):
            if not _task_state_has_merge_to_main_evidence(
                project_name=project_name,
                project_id=str(project_id or "").strip() or None,
                state=state,
            ):
                raise RuntimeError(
                    "Lead handoff is blocked: merge-to-main evidence is missing for the current task."
                )
            lock_info = _acquire_project_deploy_lock(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=run.task_id,
                actor_user_id=actor_user_id,
                acquired_at_iso=completed_at,
            )
            if not bool(lock_info.get("ok")):
                raise RuntimeError(str(lock_info.get("error") or "Runner error: failed to acquire project deploy lock."))
            deploy_lock_id = str(lock_info.get("lock_id") or "").strip() or None
            deploy_cycle_id = str(lock_info.get("deploy_cycle_id") or "").strip() or None
            stack, host, port, health_path, runtime_required = _effective_runtime_deploy_target_for_task(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                delivery_mode=state.get("delivery_mode"),
            )
            runtime_check_ok = True
            try:
                if runtime_required and port is None:
                    raise RuntimeError(
                        "Lead deploy gate failed: runtime_deploy_health.port is required but missing."
                    )
                manifest_path = find_project_compose_manifest(
                    project_name=project_name,
                    project_id=str(project_id or "").strip() or None,
                )
                if runtime_required:
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
                    deploy_snapshot = derive_deploy_execution_snapshot(
                        refs=state.get("external_refs"),
                        current_snapshot=state.get("last_deploy_execution") if isinstance(state.get("last_deploy_execution"), dict) else {},
                    )
                    deploy_snapshot.update(
                        {
                            "manifest_path": manifest_path_raw,
                            "runtime_type": str(synthesis.get("runtime_type") or "").strip() or None,
                            "synthesized": bool(list(synthesis.get("created_files") or [])),
                            "synthesized_files": list(synthesis.get("created_files") or []),
                            "synthesis_commit_sha": str(synthesis.get("commit_sha") or "").strip() or None,
                            "deploy_cycle_id": deploy_cycle_id,
                            "deploy_lock_id": deploy_lock_id,
                            "deploy_lock_acquired_at": completed_at,
                        }
                    )
                    state["last_deploy_execution"] = deploy_snapshot
                if runtime_required and manifest_path is not None:
                    repo_root = resolve_project_repository_path(
                        project_name=str(project_name or "").strip() or None,
                        project_id=str(project_id or "").strip() or None,
                    )
                    repo_root_host = resolve_project_repository_host_path(
                        project_name=str(project_name or "").strip() or None,
                        project_id=str(project_id or "").strip() or None,
                    )
                    translated_manifest_path = _translate_compose_manifest_for_host_runtime(
                        manifest_path=Path(manifest_path),
                        repo_root_host=repo_root_host,
                    )
                    compose_requires_build = False
                    try:
                        compose_requires_build = bool(
                            re.search(r"(?m)^\s*build\s*:", translated_manifest_path.read_text(encoding="utf-8"))
                        )
                    except Exception:
                        compose_requires_build = False
                    compose_up_command = (
                        f"docker compose -f {translated_manifest_path} -p {stack} up -d --build"
                        if compose_requires_build
                        else f"docker compose -f {translated_manifest_path} -p {stack} up -d"
                    )
                    remove_orphans_command = (
                        f"{compose_up_command} --remove-orphans"
                    )
                    code_deploy, _out_deploy, err_deploy = _run_docker_compose_up_with_error(
                        cwd=repo_root,
                        stack=stack,
                        manifest_path=translated_manifest_path,
                    )
                    if code_deploy != 0 and _is_lead_safe_compose_orphan_error(err_deploy):
                        retry_code_deploy, _retry_out_deploy, retry_err_deploy = _run_docker_compose_up_with_error(
                            cwd=repo_root,
                            stack=stack,
                            manifest_path=translated_manifest_path,
                            remove_orphans=True,
                        )
                        if retry_code_deploy == 0:
                            code_deploy = 0
                            err_deploy = ""
                            compose_up_command = remove_orphans_command
                        else:
                            code_deploy = retry_code_deploy
                            err_deploy = str(retry_err_deploy or "").strip() or str(err_deploy or "").strip()
                    if code_deploy != 0:
                        deploy_snapshot = derive_deploy_execution_snapshot(
                            refs=state.get("external_refs"),
                            current_snapshot=state.get("last_deploy_execution") if isinstance(state.get("last_deploy_execution"), dict) else {},
                        )
                        deploy_snapshot.update(
                            {
                                "executed_at": completed_at,
                                "stack": stack,
                                "port": int(port) if port is not None else None,
                                "health_path": health_path,
                                "command": compose_up_command,
                                "manifest_path": str(manifest_path),
                                "runtime_type": deploy_snapshot.get("runtime_type")
                                or _derive_runtime_deploy_markers(
                                    project_name=str(project_name or "").strip() or None,
                                    project_id=str(project_id or "").strip() or None,
                                )[0],
                                "runtime_ok": False,
                                "error": str(err_deploy or "").strip()[:500] or None,
                                "deploy_cycle_id": deploy_cycle_id,
                                "deploy_lock_id": deploy_lock_id,
                                "deploy_lock_acquired_at": completed_at,
                            }
                        )
                        append_event(
                            db,
                            aggregate_type="Task",
                            aggregate_id=run.task_id,
                            event_type=TASK_EVENT_UPDATED,
                            payload={"last_deploy_execution": deploy_snapshot},
                            metadata={
                                "actor_id": actor_user_id,
                                "workspace_id": workspace_id,
                                "project_id": project_id,
                                "task_id": run.task_id,
                            },
                        )
                        state = dict(state)
                        state["last_deploy_execution"] = deploy_snapshot
                        if _is_lead_safe_compose_orphan_error(err_deploy):
                            raise RuntimeError(
                                "Lead deploy execution failed: docker compose up -d detected stale orphaned service state "
                                "after a service rename/removal. Lead retried with --remove-orphans but the deploy still failed. "
                                + str(err_deploy or "")[:240]
                            )
                        raise RuntimeError(
                            "Lead deploy execution failed: docker compose up -d did not succeed. "
                            + str(err_deploy or "")[:240]
                        )
                if runtime_required and port is not None:
                    runtime_check = _probe_runtime_health_with_retry(
                        stack=stack,
                        port=port,
                        health_path=health_path,
                        require_http_200=True,
                        host=host,
                    )
                    deploy_refs = _append_lead_deploy_external_refs(
                        refs=state.get("external_refs"),
                        stack=stack,
                        build_required=compose_requires_build,
                        port=port,
                        health_path=health_path,
                        runtime_ok=bool(runtime_check.get("ok")),
                        http_url=str(runtime_check.get("http_url") or "").strip() or None,
                        http_status=int(runtime_check.get("http_status") or 0) if runtime_check.get("http_status") is not None else None,
                        project_name=str(project_name or "").strip() or None,
                        project_id=str(project_id or "").strip() or None,
                    )
                    deploy_snapshot = derive_deploy_execution_snapshot(
                        refs=state.get("external_refs"),
                        current_snapshot=state.get("last_deploy_execution") if isinstance(state.get("last_deploy_execution"), dict) else {},
                    )
                    deploy_snapshot.update(
                        {
                            "executed_at": completed_at,
                            "stack": stack,
                            "port": int(port),
                            "health_path": health_path,
                            "command": compose_up_command,
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
                            "deploy_cycle_id": deploy_cycle_id,
                            "deploy_lock_id": deploy_lock_id,
                            "deploy_lock_acquired_at": completed_at,
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
                    state["team_mode_phase"] = "deployment"
                    runtime_check_ok = bool(runtime_check.get("ok"))
                    if not runtime_check_ok:
                        runtime_error = str(runtime_check.get("error") or "").strip()
                        raise RuntimeError(
                            "Lead deploy gate failed: runtime health check did not pass "
                            f"(stack={stack}, port={int(port)}, path={health_path})"
                            + (f"; error={runtime_error}" if runtime_error else "")
                        )
            except Exception:
                _release_project_deploy_lock(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    task_id=run.task_id,
                    actor_user_id=actor_user_id,
                    released_at_iso=completed_at,
                    lock_id=deploy_lock_id,
                )
                raise

            lead_handoff_at = completed_at
            lead_handoff_token = f"lead:{run.task_id}:{lead_handoff_at}"
            handoff_refs = _collect_handoff_refs_from_tasks(
                db=db,
                task_ids=[run.task_id, *[str(item or "").strip() for item in (merge_result.get("merged_task_ids") or [])]],
            )
            if task_requires_deploy(normalize_delivery_mode(state.get("delivery_mode"))) and not is_strict_deploy_success_snapshot(
                state.get("last_deploy_execution") if isinstance(state.get("last_deploy_execution"), dict) else {}
            ):
                raise RuntimeError(
                    "Lead handoff failed: strict deploy evidence is missing for the current deployable slice."
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
            lead_transition = lead_deploy_success_transition()
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=TASK_EVENT_UPDATED,
                payload={
                    **_team_mode_progress_payload(phase=str(lead_transition.get("phase") or "qa_validation")),
                    "last_deploy_execution": state.get("last_deploy_execution"),
                    "last_deploy_cycle_id": deploy_cycle_id,
                    "deploy_lock_id": deploy_lock_id,
                    "deploy_lock_acquired_at": completed_at,
                    "deploy_lock_released_at": completed_at,
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
            state["team_mode_phase"] = str(lead_transition.get("phase") or "qa_validation")
            state["last_deploy_cycle_id"] = deploy_cycle_id
            state["deploy_lock_id"] = deploy_lock_id
            state["deploy_lock_acquired_at"] = completed_at
            state["deploy_lock_released_at"] = completed_at
            state["last_lead_handoff_token"] = lead_handoff_token
            state["last_lead_handoff_at"] = lead_handoff_at
            state["last_lead_handoff_refs_json"] = handoff_refs
            state["last_lead_handoff_deploy_execution"] = state.get("last_deploy_execution")
            _release_project_deploy_lock(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=run.task_id,
                actor_user_id=actor_user_id,
                released_at_iso=completed_at,
                lock_id=deploy_lock_id,
            )

        if (
            team_mode_enabled
            and is_qa_role(assignee_role)
            and semantic_status_key(status=state.get("status")) in {"todo", "active", "blocked"}
            and str(state.get("last_lead_handoff_token") or "").strip()
            and task_requires_deploy(normalize_delivery_mode(state.get("delivery_mode")))
        ):
            if not is_strict_deploy_success_snapshot(
                state.get("last_lead_handoff_deploy_execution")
                if isinstance(state.get("last_lead_handoff_deploy_execution"), dict)
                else state.get("last_deploy_execution")
                if isinstance(state.get("last_deploy_execution"), dict)
                else {}
            ):
                raise RuntimeError(
                    "QA completion is blocked: strict deploy evidence is missing for the current deployable slice."
                )
            from features.tasks.command_handlers import _effective_completed_status_for_project

            completed_status = _effective_completed_status_for_project(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            qa_transition = qa_success_transition(completed_status=completed_status)
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=TASK_EVENT_UPDATED,
                payload={
                    **_team_mode_progress_payload(phase=str(qa_transition.get("phase") or "completed")),
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
                    event_type=TASK_EVENT_COMPLETED,
                    payload={
                        "completed_at": completed_at,
                        "status": str(qa_transition.get("status") or completed_status),
                    },
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
            )
            state = dict(state)
            state["status"] = str(qa_transition.get("status") or completed_status)
            state["completed_at"] = completed_at
            state["team_mode_phase"] = str(qa_transition.get("phase") or "completed")
            queued_followup_developer_dispatches = _queue_team_mode_dispatches(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                source="runner_orchestrator",
                source_task_id=run.task_id,
                exclude_task_ids={run.task_id},
                allowed_roles={"Developer"},
            )

        effective_blocked_status = _effective_blocked_status_for_project(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if is_blocker_source_role(assignee_role) and str(
            state.get("status") or ""
        ).strip() == effective_blocked_status:
            queued_blocker_escalations = _enqueue_team_lead_blocker_escalation(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                blocked_task_id=run.task_id,
                blocked_title=str(state.get("title") or ""),
                blocked_role=assignee_role,
                blocked_status=effective_blocked_status,
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
                blocking_gate=str(state.get("team_mode_blocking_gate") or "").strip() or None,
                phase=str(state.get("team_mode_phase") or "").strip()
                or _derive_team_mode_phase(
                    assignee_role=assignee_role,
                    status=str(state.get("status") or run.status or ""),
                ),
            )
        completion_check_workspace_id = workspace_id
        completion_check_project_id = project_id
        completion_check_actor_user_id = actor_user_id
        db.commit()
    if (
        completion_check_workspace_id
        and completion_check_actor_user_id
    ):
        _finalize_project_completion_post_commit(
            workspace_id=completion_check_workspace_id,
            project_id=completion_check_project_id,
            actor_user_id=completion_check_actor_user_id,
        )
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
    developer_main_reconciliation_queued = False
    developer_handoff_recovery_queued = False
    developer_deploy_lock_waiting = False
    lead_developer_triage_queued = False
    queued_blocker_escalations = 0
    with SessionLocal() as db:
        state, _ = rebuild_state(db, "Task", run.task_id)
        workspace_id = str(state.get("workspace_id") or run.workspace_id or "").strip()
        if not workspace_id:
            return
        project_id = str(state.get("project_id") or run.project_id or "").strip() or None
        team_mode_enabled = _project_has_team_mode_skill(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        effective_blocked_status = _effective_blocked_status_for_project(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
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
        effective_assignee_role = assignee_role
        if (
            team_mode_enabled
            and str(state.get("team_mode_phase") or "").strip() in {"deploy_ready", "deployment", "qa_validation", "lead_triage"}
            and not str(state.get("assigned_agent_code") or "").strip()
        ):
            _ensure_team_mode_lead_assignment(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=run.task_id,
                state=state,
                actor_user_id=actor_user_id,
            )
            state, _ = rebuild_state(db, "Task", run.task_id)
            effective_assignee_role = _resolve_assignee_project_role(
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
        lead_triage_handoff = False
        if (
            AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS
            and is_blocker_source_role(assignee_role)
            and str(state.get("status") or "").strip() != effective_blocked_status
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
                to_status=effective_blocked_status,
            )
            if transitioned:
                state = dict(state)
                state["status"] = effective_blocked_status
        queued_blocker_escalations = 0
        failure_gate = _classify_team_mode_failure_gate(
            assignee_role=effective_assignee_role,
            error=str(error),
        )
        lead_scaffolding_followup_task_id: str | None = None
        developer_main_reconciliation_queued = False
        developer_handoff_recovery_queued = False
        developer_deploy_lock_waiting = False
        lead_developer_triage_queued = False
        lead_human_escalation = False
        if (
            team_mode_enabled
            and canonicalize_role(effective_assignee_role) == "Developer"
            and _is_developer_main_reconciliation_error(str(error))
        ):
            developer_main_reconciliation_queued = _requeue_developer_main_reconciliation(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=run.task_id,
                state=state,
                actor_user_id=actor_user_id,
                failed_at_iso=failed_at,
                failure_reason=str(error),
            )
        if (
            team_mode_enabled
            and canonicalize_role(effective_assignee_role) == "Developer"
            and failure_gate == "developer_handoff_not_committed"
        ):
            developer_handoff_recovery_queued = _requeue_developer_committed_handoff(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=run.task_id,
                state=state,
                actor_user_id=actor_user_id,
                failed_at_iso=failed_at,
                failure_reason=str(error),
            )
        if (
            team_mode_enabled
            and canonicalize_role(effective_assignee_role) == "Developer"
            and failure_gate == "developer_deploy_lock_waiting"
        ):
            developer_deploy_lock_waiting = _requeue_developer_after_deploy_lock(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=run.task_id,
                state=state,
                actor_user_id=actor_user_id,
                failed_at_iso=failed_at,
                failure_reason=str(error),
            )
        if (
            team_mode_enabled
            and canonicalize_role(effective_assignee_role) == "Lead"
            and "compose manifest is missing and deterministic synthesis failed" in str(error).lower()
        ):
            _stack, _host, runtime_port, runtime_health_path, _required = _project_runtime_deploy_target(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            lead_scaffolding_followup_task_id = _create_lead_deploy_scaffolding_followup(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                state=state,
                actor_user_id=actor_user_id,
                port=runtime_port,
                health_path=runtime_health_path,
            )
            if lead_scaffolding_followup_task_id:
                failure_gate = "lead_deploy_scaffolding"
        if (
            team_mode_enabled
            and canonicalize_role(effective_assignee_role) == "Lead"
            and "runtime health check did not pass" in str(error).lower()
            and not lead_scaffolding_followup_task_id
        ):
            _stack, _host, runtime_port, runtime_health_path, _required = _project_runtime_deploy_target(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            lead_scaffolding_followup_task_id = _create_lead_runtime_health_followup(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                state=state,
                actor_user_id=actor_user_id,
                port=runtime_port,
                health_path=runtime_health_path,
            )
            if lead_scaffolding_followup_task_id:
                failure_gate = "lead_runtime_health_failed"
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
            and not developer_main_reconciliation_queued
            and not developer_handoff_recovery_queued
            and not developer_deploy_lock_waiting
            and is_blocker_source_role(effective_assignee_role)
        ):
            if team_mode_enabled and canonicalize_role(effective_assignee_role) in {"Developer", "QA"}:
                handoff_assignee_id = _handoff_failed_team_mode_task_to_lead(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    task_id=run.task_id,
                    state=state,
                    actor_user_id=actor_user_id,
                    failed_at_iso=failed_at,
                    failure_reason=str(error),
                    failed_role=effective_assignee_role,
                )
                lead_triage_handoff = bool(handoff_assignee_id)
            elif team_mode_enabled and canonicalize_role(effective_assignee_role) == "Lead":
                lead_developer_triage_queued = _handoff_failed_team_mode_lead_task_to_developer(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    task_id=run.task_id,
                    state=state,
                    actor_user_id=actor_user_id,
                    failed_at_iso=failed_at,
                    failure_reason=str(error),
                    failure_gate=failure_gate,
                )
                if not lead_developer_triage_queued:
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
                    lead_human_escalation = bool(str(handoff_assignee_id or "").strip())
            if not handoff_assignee_id and not (
                team_mode_enabled and canonicalize_role(effective_assignee_role) == "Lead"
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
        if lead_developer_triage_queued or lead_human_escalation:
            state, _ = rebuild_state(db, "Task", run.task_id)
        lead_workflow_resolved = bool(
            team_mode_enabled
            and canonicalize_role(effective_assignee_role) == "Lead"
            and (
                str(lead_scaffolding_followup_task_id or "").strip()
                or lead_developer_triage_queued
                or lead_human_escalation
            )
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=run.task_id,
            event_type=EVENT_AUTOMATION_COMPLETED if lead_workflow_resolved else EVENT_AUTOMATION_FAILED,
            payload=(
                {
                    "completed_at": failed_at,
                    "summary": (
                        "Lead workflow triage queued."
                        if lead_developer_triage_queued
                        else "Lead remediation follow-up queued."
                        if lead_scaffolding_followup_task_id
                        else "Lead escalated to human decision."
                        if lead_human_escalation
                        else "Automation deferred to workflow resolution."
                    ),
                }
                if lead_workflow_resolved
                else {"failed_at": failed_at, "error": str(error), "summary": "Automation runner failed."}
            ),
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
                "last_agent_stream_status": (
                    "Lead returned the task to Developer for remediation."
                    if lead_developer_triage_queued
                    else "Lead queued remediation follow-up work."
                    if lead_scaffolding_followup_task_id
                    else "Lead escalated the task for human decision."
                    if lead_human_escalation
                    else "Automation run failed."
                ),
                "last_agent_stream_updated_at": failed_at,
                **_team_mode_progress_payload(
                    phase=str(state.get("team_mode_phase") or "").strip()
                    or _derive_team_mode_phase(
                        assignee_role=effective_assignee_role,
                        status=str(state.get("status") or run.status or ""),
                    ),
                    blocking_gate=failure_gate,
                    blocked_reason=(
                        f"{str(error)} Follow-up task queued: {lead_scaffolding_followup_task_id}."
                        if lead_scaffolding_followup_task_id
                        else str(error)
                    ),
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
        _requeue_pending_status_change_request(
            db=db,
            run=run,
            state=state,
            workspace_id=workspace_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            requested_at_iso=failed_at,
        )
        if is_blocker_source_role(effective_assignee_role) and not non_blocking_gate_failure:
            if (
                not should_retry
                and not lead_triage_handoff
                and not lead_scaffolding_followup_task_id
                and not developer_main_reconciliation_queued
                and not developer_handoff_recovery_queued
                and not developer_deploy_lock_waiting
                and not lead_developer_triage_queued
                and not lead_human_escalation
            ):
                queued_blocker_escalations = _enqueue_team_lead_blocker_escalation(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    blocked_task_id=run.task_id,
                    blocked_title=str(state.get("title") or ""),
                    blocked_role=effective_assignee_role,
                    blocked_status=str(state.get("status") or "").strip() or effective_blocked_status,
                    blocked_error=str(error),
                )
        if _should_notify_humans_about_blocked_automation(
            team_mode_enabled=team_mode_enabled,
            should_retry=should_retry,
            non_blocking_gate_failure=non_blocking_gate_failure,
            lead_triage_handoff=lead_triage_handoff,
            lead_scaffolding_followup_task_id=lead_scaffolding_followup_task_id,
            developer_main_reconciliation_queued=developer_main_reconciliation_queued,
            developer_handoff_recovery_queued=developer_handoff_recovery_queued,
            developer_deploy_lock_waiting=developer_deploy_lock_waiting,
            lead_developer_triage_queued=lead_developer_triage_queued,
            lead_human_escalation=lead_human_escalation,
        ):
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
                blocking_gate=failure_gate,
                phase=str(state.get("team_mode_phase") or "").strip()
                or _derive_team_mode_phase(
                    assignee_role=effective_assignee_role,
                    status=str(state.get("status") or run.status or ""),
                ),
            )
        db.commit()
    if (
        queued_blocker_escalations > 0
        or developer_main_reconciliation_queued
        or developer_handoff_recovery_queued
        or developer_deploy_lock_waiting
        or lead_developer_triage_queued
    ):
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
            _project_has_team_mode_skill(db=db, workspace_id=workspace_id, project_id=project_id)
            and canonicalize_role(assignee_role) in {"Developer", "Lead", "QA"}
        ):
            dependency_ready, dependency_reason = _team_mode_dispatch_dependency_ready(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=run.task_id,
                state=state,
            )
            if not dependency_ready:
                return (
                    "Team Mode execution is gated by structural dependencies: "
                    + str(dependency_reason or "dependency requirements are not satisfied.")
                )
        if (
            is_qa_role(assignee_role)
            and semantic_status_key(status=state.get("status")) in {"active", "blocked"}
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
                    "the task has not received a valid Lead handoff yet."
                )
        if (
            is_lead_role(assignee_role)
            and semantic_status_key(status=state.get("status")) in {"todo", "active", "blocked", "awaiting_decision"}
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
                    "Lead automation is gated until the Developer handoff is committed on a task branch and becomes merge-ready; "
                    "do not evaluate compose/deploy gates before a committed Developer handoff produces merge-to-main evidence."
                )
        if (
            is_lead_role(assignee_role)
            and semantic_status_key(status=state.get("status")) in {"todo", "active", "blocked", "awaiting_decision"}
            and _project_requires_runtime_deploy_health(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
        ):
            _stack, _host, runtime_port, _health_path, _required = _project_runtime_deploy_target(
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


def _classify_team_mode_failure_gate(
    *,
    assignee_role: str | None,
    error: str | None,
) -> str | None:
    normalized_role = canonicalize_role(assignee_role)
    normalized_error = str(error or "").strip().lower()
    if not normalized_error:
        return None
    if "team mode execution is gated by structural dependencies" in normalized_error:
        return "team_mode_dependency_waiting"
    if normalized_role == "Lead":
        if (
            "developer handoff is not committed on the task branch yet" in normalized_error
            or "developer handoff is not committed on a task branch ahead of main yet" in normalized_error
            or "real task branch handoff before lead review" in normalized_error
        ):
            return "lead_waiting_committed_developer_handoff"
        if "merge-to-main evidence is missing" in normalized_error:
            return "lead_waiting_committed_developer_handoff"
        if "compose manifest is missing" in normalized_error:
            return "lead_compose_manifest_missing"
        if "runtime health check did not pass" in normalized_error or "curl(56)" in normalized_error:
            return "lead_runtime_health_failed"
        if _is_lead_deploy_topology_reconciliation_error(normalized_error):
            return "lead_deploy_topology_reconciliation_required"
        if "no such file or directory" in normalized_error and "repos/" in normalized_error:
            return "lead_repository_path_resolution_failed"
    if normalized_role == "Developer" and (
        "developer handoff is not committed on the task branch yet" in normalized_error
        or "developer handoff is not committed on a task branch ahead of main yet" in normalized_error
        or "real task branch handoff before lead review" in normalized_error
    ):
        return "developer_handoff_not_committed"
    if normalized_role == "Developer" and "deployment in progress; merge to main is temporarily frozen" in normalized_error:
        return "developer_deploy_lock_waiting"
    if normalized_role == "Developer" and _is_developer_main_reconciliation_error(normalized_error):
        return "developer_main_reconciliation_required"
    return None


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

            _rearm_blocked_team_mode_lead_tasks(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            parallel_limit = _project_automation_parallel_limit(db=db, project_id=project_id)
            dispatch_candidates, candidate_map = _build_team_mode_dispatch_candidates(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            eligible_candidates: list[dict[str, object]] = []
            for candidate in dispatch_candidates:
                task_id = str(candidate.get("id") or "").strip()
                normalized_role = str(candidate.get("role") or "").strip()
                if normalized_role not in {"Developer", "QA"}:
                    continue
                candidate_bundle = candidate_map.get(task_id)
                if candidate_bundle is None:
                    continue
                _task, state, _target_slot = candidate_bundle
                if not _eligible_for_team_mode_auto_queue(
                    state,
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    assignee_role=normalized_role,
                    now_utc=now_utc,
                ):
                    continue
                eligible_candidates.append(candidate)

            plan = plan_team_mode_dispatch(
                eligible_candidates,
                max_parallel_dispatch=parallel_limit,
            )

            from features.tasks.application import TaskApplicationService
            from shared.core import TaskAutomationRun

            for task_id in list(plan.get("queue_task_ids") or []):
                if queued >= limit:
                    break
                candidate_bundle = candidate_map.get(str(task_id or "").strip())
                if candidate_bundle is None:
                    continue
                task, state, target_slot = candidate_bundle
                task_id = str(task.id or "").strip()
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
                normalized_role = _resolve_assignee_project_role(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    assignee_id=str(state.get("assignee_id") or getattr(task, "assignee_id", "") or ""),
                    assigned_agent_code=str(state.get("assigned_agent_code") or getattr(task, "assigned_agent_code", "") or ""),
                    task_labels=state.get("labels") if state.get("labels") is not None else getattr(task, "labels", None),
                    task_status=str(state.get("status") or getattr(task, "status", "") or ""),
                )
                inferred_source_task_id = _infer_team_mode_dispatch_source_task_id(
                    db=db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    task_id=task_id,
                    assignee_role=normalized_role,
                )
                current_automation_state = str(state.get("automation_state") or "idle").strip().lower()
                if current_automation_state in {"queued", "running"}:
                    continue
                if (
                    current_automation_state == "completed"
                    and str(state.get("last_requested_source") or "").strip() == "runner_orchestrator"
                    and str(state.get("last_requested_source_task_id") or "").strip() == str(inferred_source_task_id or "").strip()
                ):
                    continue
                try:
                    TaskApplicationService(db, actor, command_id=command_id).request_automation_run(
                        task_id,
                        TaskAutomationRun(
                            instruction=instruction,
                            source="runner_orchestrator",
                            source_task_id=inferred_source_task_id,
                        ),
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
                            "source": "runner_orchestrator",
                            "mode": str(plan.get("mode") or "").strip() or None,
                            "role": normalized_role,
                            "priority": str(getattr(task, "priority", "") or "").strip() or None,
                            "slot": target_slot or None,
                            "selected_at": to_iso_utc(now_utc),
                            "available_slots": int((plan.get("counts") or {}).get("available_slots") or 0),
                            "source_task_id": str(inferred_source_task_id or "").strip() or None,
                        },
                    },
                    metadata={
                        "actor_id": AGENT_SYSTEM_USER_ID,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": task_id,
                    },
                )
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
                if semantic_status_key(status=state.get("status") or task.status) == "completed":
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
